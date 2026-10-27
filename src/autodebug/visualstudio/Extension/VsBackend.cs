// Visual Studio's side of the relay: launch targets from the startup project, the
// Approve dialog, builds, breakpoints, and the debugger, shaped as Debug Adapter
// Protocol requests and events. It only reads values the debugger already shows
// (locals and their members); it never evaluates an expression or changes a value.
//
// Visual Studio's automation objects must be used on its main thread. The relay
// calls in from background threads, so every call goes through OnMain.

using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
using EnvDTE;
using EnvDTE80;
using EnvDTE90a;
using Microsoft.VisualStudio;
using Microsoft.VisualStudio.Debugger.Interop;
using Microsoft.VisualStudio.Shell;
using Microsoft.VisualStudio.Shell.Interop;
using DteThread = EnvDTE.Thread;
using Task = System.Threading.Tasks.Task;

// Every Visual Studio object below is used inside OnMain (on the main thread) or in an event
// handler Visual Studio calls on the main thread; the analyzer cannot see through OnMain.
#pragma warning disable VSTHRD010

namespace AutoDebug.VisualStudio
{
    sealed class VsBackend : IBackend, IDebugEventCallback2, IDisposable
    {
        static readonly Guid NativeEngine = new Guid("3B476D35-A401-11D2-AAD4-00C04F990171");
        static readonly Guid PaneGuid = new Guid("0d3a3b9f-7c1e-4f55-9f3e-6b8e5c2a1d44");
        const int MaxChildren = 200;

        readonly AsyncPackage package;
        DTE2 dte;
        IVsDebugger debugger;
        IVsOutputWindowPane pane;
        DebuggerEvents debuggerEvents;
        SolutionEvents solutionEvents;
        BuildEvents buildEvents;
        volatile string solutionFolder;
        volatile IBackendEvents session;
        ManualResetEventSlim buildDone;
        long? exitCode;
        Dictionary<string, object> lastException;
        readonly Dictionary<string, (string UniqueName, string Configuration)> buildTargets = new Dictionary<string, (string, string)>();
        // Frames and values the server may ask about; cleared whenever the program runs again.
        readonly Dictionary<long, object> references = new Dictionary<long, object>();
        long nextReference = 1;

        public Action FoldersChanged { get; set; }

        VsBackend(AsyncPackage package) { this.package = package; }

        public static async System.Threading.Tasks.Task<VsBackend> CreateAsync(AsyncPackage package)
        {
            await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();
            var backend = new VsBackend(package);
            backend.dte = await package.GetServiceAsync(typeof(DTE)) as DTE2 ?? throw new InvalidOperationException("no DTE service");
            backend.debugger = await package.GetServiceAsync(typeof(SVsShellDebugger)) as IVsDebugger ?? throw new InvalidOperationException("no debugger service");
            var output = await package.GetServiceAsync(typeof(SVsOutputWindow)) as IVsOutputWindow ?? throw new InvalidOperationException("no output window");
            var guid = PaneGuid;
            output.CreatePane(ref guid, "AutoDebug", 1, 1);
            output.GetPane(ref guid, out backend.pane);
            backend.Subscribe();
            return backend;
        }

        void Subscribe()
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            debuggerEvents = dte.Events.DebuggerEvents;
            debuggerEvents.OnEnterBreakMode += OnBreak;
            debuggerEvents.OnEnterRunMode += OnRun;
            debuggerEvents.OnEnterDesignMode += OnDesign;
            debuggerEvents.OnExceptionThrown += OnException;
            debuggerEvents.OnExceptionNotHandled += OnException;
            solutionEvents = dte.Events.SolutionEvents;
            solutionEvents.Opened += OnSolutionChanged;
            solutionEvents.AfterClosing += OnSolutionChanged;
            buildEvents = dte.Events.BuildEvents;
            buildEvents.OnBuildDone += (scope, action) => buildDone?.Set();
            debugger.AdviseDebugEventCallback(this);
            OnSolutionChanged();
        }

        public void Dispose()
        {
            ThreadHelper.JoinableTaskFactory.Run(async () =>
            {
                await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();
                try { debugger?.UnadviseDebugEventCallback(this); } catch (COMException) { /* Visual Studio is closing */ }
            });
        }

        static T OnMain<T>(Func<T> work) => ThreadHelper.JoinableTaskFactory.Run(async () =>
        {
            await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();
            return work();
        });

        static void OnMain(Action work) => OnMain(() => { work(); return true; });

        // -- the window ---------------------------------------------------------------------

        public string Ide => "visualstudio";
        public string IdeVersion { get; private set; } = "";
        public string Platform => "win32";
        public IList<string> DebuggerTypes() => new List<string> { "visualstudio" };

        public IList<string> Folders()
        {
            var folder = solutionFolder;
            return string.IsNullOrEmpty(folder) ? new List<string>() : new List<string> { folder };
        }

        void OnSolutionChanged()
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            IdeVersion = dte.Version;
            var full = dte.Solution?.FullName;
            solutionFolder = string.IsNullOrEmpty(full) ? null : SourceFolder(Path.GetDirectoryName(full));
            FoldersChanged?.Invoke();
        }

        // A CMake build folder (like Blender's) keeps the solution away from the source; the
        // workspace is the source folder CMake recorded, so breakpoints use source paths.
        static string SourceFolder(string solutionFolder)
        {
            try
            {
                var cache = Path.Combine(solutionFolder, "CMakeCache.txt");
                if (File.Exists(cache))
                    foreach (var line in File.ReadLines(cache))
                        if (line.StartsWith("CMAKE_HOME_DIRECTORY:", StringComparison.Ordinal))
                        {
                            var source = line.Substring(line.IndexOf('=') + 1).Trim();
                            if (Directory.Exists(source)) return Path.GetFullPath(source);
                        }
            }
            catch (IOException) { /* fall back to the solution's folder */ }
            catch (UnauthorizedAccessException) { /* fall back to the solution's folder */ }
            return solutionFolder;
        }

        public void Log(string line) => pane?.OutputStringThreadSafe($"{DateTime.Now:HH:mm:ss} {line}{System.Environment.NewLine}");

        public void Notify(string text)
        {
            Log(text);
            OnMain(() =>
            {
                dte.StatusBar.Text = text;
                pane?.Activate();
            });
        }

        // -- launch targets: the startup project's debug settings --------------------------------

        public Dictionary<string, object> Workspace(string folder) => OnMain(() =>
        {
            var launch = new List<object>();
            var tasks = new List<object>();
            var solution = dte.Solution;
            var solutionConfig = solution?.SolutionBuild?.ActiveConfiguration as SolutionConfiguration2;
            var solutionName = solutionConfig == null ? "" : $"{solutionConfig.Name}|{solutionConfig.PlatformName}";
            foreach (var uniqueName in ((solution?.SolutionBuild?.StartupProjects as object[]) ?? new object[0]).OfType<string>())
            {
                var target = Target(uniqueName);
                if (target == null) continue;
                launch.Add(target);
                var label = $"Build {target["project"]} ({target["configuration"]})";
                lock (buildTargets) buildTargets[label] = (uniqueName, (string)target["configuration"]);
                tasks.Add(Json.Make("label", label, "command", $"build project {target["project"]} ({target["configuration"]})"));
            }
            if (solutionConfig != null)
            {
                var label = $"Build solution ({solutionName})";
                lock (buildTargets) buildTargets[label] = (null, solutionName);
                tasks.Add(Json.Make("label", label, "command", $"build the solution ({solutionName})"));
            }
            launch.Add(Json.Make("name", "Attach to a process (native)", "type", "visualstudio", "request", "attach",
                "processId", "${command:pickProcess}", "engine", "native"));
            return Json.Make("folder", solutionFolder ?? folder, "launch", launch, "tasks", tasks);
        });

        Dictionary<string, object> Target(string uniqueName)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            var solution = (IVsSolution)Package.GetGlobalService(typeof(SVsSolution));
            if (solution == null || solution.GetProjectOfUniqueName(uniqueName, out var hierarchy) != VSConstants.S_OK) return null;
            hierarchy.GetProperty((uint)VSConstants.VSITEMID.Root, (int)__VSHPROPID.VSHPROPID_ExtObject, out var extObject);
            var project = extObject as Project;
            var active = project?.ConfigurationManager?.ActiveConfiguration;
            if (project == null || active == null) return null;
            var configuration = $"{active.ConfigurationName}|{active.PlatformName}";
            var storage = hierarchy as IVsBuildPropertyStorage;
            string Read(string name, _PersistStorageType where)
            {
                if (storage == null) return null;
                return storage.GetPropertyValue(name, configuration, (uint)where, out var value) == VSConstants.S_OK ? value : null;
            }
            var targetPath = Read("TargetPath", _PersistStorageType.PST_PROJECT_FILE);
            var projectDir = Path.GetDirectoryName(project.FullName) ?? "";
            string Expand(string value) => (value ?? "")
                .Replace("$(TargetPath)", targetPath ?? "")
                .Replace("$(ProjectDir)", projectDir.EndsWith("\\") ? projectDir : projectDir + "\\")
                .Replace("$(SolutionDir)", (solutionFolder ?? "") + "\\");
            var program = Expand(Read("LocalDebuggerCommand", _PersistStorageType.PST_USER_FILE));
            if (string.IsNullOrWhiteSpace(program)) program = targetPath;
            if (string.IsNullOrWhiteSpace(program)) return null;
            var arguments = Expand(Read("LocalDebuggerCommandArguments", _PersistStorageType.PST_USER_FILE));
            var cwd = Expand(Read("LocalDebuggerWorkingDirectory", _PersistStorageType.PST_USER_FILE));
            var env = new Dictionary<string, object>();
            foreach (var line in Expand(Read("LocalDebuggerEnvironment", _PersistStorageType.PST_USER_FILE)).Split('\n'))
            {
                var equals = line.IndexOf('=');
                if (equals > 0) env[line.Substring(0, equals).Trim()] = line.Substring(equals + 1).TrimEnd('\r');
            }
            return Json.Make("name", $"{project.Name} ({configuration})", "type", "visualstudio", "request", "launch",
                "program", program, "args", string.IsNullOrWhiteSpace(arguments) ? new List<object>() : new List<object> { arguments },
                "cwd", string.IsNullOrWhiteSpace(cwd) ? projectDir : cwd, "env", env, "project", project.Name,
                "configuration", configuration, "engine", "native");
        }

        // -- approval and builds ------------------------------------------------------------------

        public Action Ask(string title, string detail, Action<bool, string> answer)
        {
            // Both closures run on the main thread, so these two need no lock.
            System.Windows.Window open = null;
            var closed = false;
            _ = ThreadHelper.JoinableTaskFactory.RunAsync(async () =>
            {
                await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();
                bool approved = false;
                string reason = "the developer did not approve";
                try
                {
                    var window = ApprovalDialog.Create(title, detail);
                    if (!closed)
                    {
                        BringToFront();
                        Log("waiting for Approve or Deny in the AutoDebug dialog");
                        open = window;
                        approved = window.ShowModal() == true;
                        open = null;
                    }
                }
                catch (Exception error)
                {
                    Log($"the Approve dialog failed: {error.Message}");
                    reason = $"the Approve dialog could not be shown: {error.Message}";
                }
                answer(approved, approved ? null : reason);
            });
            return () => _ = ThreadHelper.JoinableTaskFactory.RunAsync(async () =>
            {
                await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();
                closed = true;
                if (open == null) return;
                Log("no answer within 2 minutes; the Approve dialog was closed and nothing ran");
                open.Close();
            });
        }

        // The agent usually runs in another app, so Visual Studio may be behind it or minimized.
        // Windows may refuse to move a background app to the front; then it flashes the taskbar
        // button instead, and the dialog itself stays above other windows.
        void BringToFront()
        {
            try
            {
                var main = dte.MainWindow;
                if (main.WindowState == vsWindowState.vsWindowStateMinimize) main.WindowState = vsWindowState.vsWindowStateNormal;
                main.Activate();
            }
            catch (Exception error) { Log($"could not bring Visual Studio to the front: {error.Message}"); }
        }

        public BuildResult Build(string label, int timeoutMs)
        {
            (string UniqueName, string Configuration) target;
            lock (buildTargets)
                if (!buildTargets.TryGetValue(label, out target)) return new BuildResult { Status = "unavailable" };
            var done = new ManualResetEventSlim(false);
            buildDone = done;
            OnMain(() =>
            {
                var build = dte.Solution.SolutionBuild;
                if (target.UniqueName == null) build.Build(false);
                else build.BuildProject(target.Configuration, target.UniqueName, false);
            });
            if (!done.Wait(timeoutMs))
            {
                CancelBuild();
                return new BuildResult { Status = "timeout" };
            }
            var failed = OnMain(() => dte.Solution.SolutionBuild.LastBuildInfo);
            return new BuildResult { Status = failed == 0 ? "succeeded" : "failed", ExitCode = failed };
        }

        public void CancelBuild() => OnMain(() =>
        {
            try { dte.ExecuteCommand("Build.Cancel"); } catch (COMException) { /* no build is running */ }
        });

        // -- breakpoints ------------------------------------------------------------------------

        public object AddBreakpoint(string file, int line, string condition) => OnMain(() =>
            (object)dte.Debugger.Breakpoints.Add(File: file, Line: line, Condition: condition ?? "",
                ConditionType: dbgBreakpointConditionType.dbgBreakpointConditionTypeWhenTrue).Item(1));

        public object AddFunctionBreakpoint(string name) => OnMain(() => (object)dte.Debugger.Breakpoints.Add(Function: name).Item(1));

        public void RemoveBreakpoint(object handle) => OnMain(() => ((Breakpoint)handle).Delete());

        public Binding Binding(object handle) => OnMain(() =>
        {
            var breakpoint = (Breakpoint)handle;
            var children = breakpoint.Children;
            var bound = children != null && children.Count > 0;
            return new Binding { Verified = bound, Line = bound ? children.Item(1).FileLine : breakpoint.FileLine };
        });

        public IList<Dictionary<string, object>> EditorBreakpoints(ICollection<object> own) => OnMain(() =>
        {
            string Key(Breakpoint b) => $"{b.File}|{b.FileLine}|{b.FunctionName}";
            var mine = new HashSet<string>(own.OfType<Breakpoint>().Select(Key), StringComparer.OrdinalIgnoreCase);
            var found = new List<Dictionary<string, object>>();
            foreach (Breakpoint b in dte.Debugger.Breakpoints)
            {
                if (!b.Enabled || mine.Contains(Key(b))) continue;
                if (b.LocationType == dbgBreakpointLocationType.dbgBreakpointLocationTypeFile && !string.IsNullOrEmpty(b.File))
                    found.Add(Json.Make("file", b.File, "line", (long)b.FileLine));
                else if (b.LocationType == dbgBreakpointLocationType.dbgBreakpointLocationTypeFunction)
                    found.Add(Json.Make("function", b.FunctionName));
            }
            return (IList<Dictionary<string, object>>)found;
        });

        // -- the debug session ------------------------------------------------------------------

        public Dictionary<string, object> Capabilities() => Json.Make(
            "supportsExceptionInfoRequest", true, "supportsFunctionBreakpoints", true,
            "exceptionBreakpointFilters", new List<object>());

        public bool Launch(Dictionary<string, object> configuration, IBackendEvents events)
        {
            exitCode = null;
            lastException = null;
            session = events;
            var attach = Json.Str(configuration, "request") == "attach";
            var info = new VsDebugTargetInfo4
            {
                guidLaunchDebugEngine = NativeEngine,
                dwDebugEngineCount = 1,
                bstrExe = Json.Str(configuration, "program"),
                bstrCurDir = Json.Str(configuration, "cwd"),
                bstrArg = string.Join(" ", Json.List(Json.Get(configuration, "args")).Select(a => Convert.ToString(a))),
            };
            if (attach)
            {
                var pid = (uint)(Json.Long(configuration, "processId") ?? Json.Long(configuration, "pid") ?? 0);
                if (pid == 0) return false;
                info.dlo = (uint)DEBUG_LAUNCH_OPERATION.DLO_AlreadyRunning;
                info.dwProcessId = pid;
                info.bstrExe = ProcessPath((int)pid);
            }
            else
            {
                info.dlo = (uint)DEBUG_LAUNCH_OPERATION.DLO_CreateProcess;
                info.bstrEnv = EnvironmentBlock(Json.Obj(Json.Get(configuration, "env")));
            }
            var engines = Marshal.AllocCoTaskMem(Marshal.SizeOf(typeof(Guid)));
            try
            {
                Marshal.StructureToPtr(NativeEngine, engines, false);
                info.pDebugEngines = engines;
                return OnMain(() =>
                {
                    ((IVsDebugger4)debugger).LaunchDebugTargets4(1, new[] { info }, new VsDebugTargetProcessInfo[1]);
                    return true;
                });
            }
            catch (COMException error)
            {
                Log($"the debugger did not start: {error.Message}");
                session = null;
                return false;
            }
            finally
            {
                Marshal.FreeCoTaskMem(engines);
            }
        }

        static string ProcessPath(int pid)
        {
            try { return System.Diagnostics.Process.GetProcessById(pid).MainModule?.FileName ?? $"process {pid}"; }
            catch (Exception) { return $"process {pid}"; }
        }

        // The program's environment with the configuration's variables added; null keeps it unchanged.
        static string EnvironmentBlock(Dictionary<string, object> added)
        {
            if (added.Count == 0) return null;
            var variables = new SortedDictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (DictionaryEntry pair in System.Environment.GetEnvironmentVariables()) variables[(string)pair.Key] = (string)pair.Value;
            foreach (var pair in added) variables[pair.Key] = Convert.ToString(pair.Value);
            return string.Concat(variables.Select(p => $"{p.Key}={p.Value}\0")) + "\0";
        }

        public void Stop(bool detach) => OnMain(() =>
        {
            if (detach) dte.Debugger.DetachAll();
            else dte.Debugger.Stop(false);
        });

        void Forget()
        {
            lock (references) { references.Clear(); }
        }

        long Remember(object value)
        {
            lock (references)
            {
                var id = nextReference++;
                references[id] = value;
                return id;
            }
        }

        object Recall(long? id)
        {
            lock (references) return id != null && references.TryGetValue(id.Value, out var value) ? value : null;
        }

        sealed class FrameRef { public DteThread Thread; public StackFrame2 Frame; }
        sealed class LocalsRef { public FrameRef Frame; }

        public Dictionary<string, object> Request(string command, Dictionary<string, object> arguments) => OnMain(() =>
        {
            var dbg = dte.Debugger;
            switch (command)
            {
                case "threads":
                    var threads = new List<object>();
                    foreach (DteThread t in dbg.CurrentProgram?.Threads ?? (IEnumerable)new object[0])
                        threads.Add(Json.Make("id", (long)t.ID, "name", string.IsNullOrEmpty(t.Name) ? $"thread {t.ID}" : t.Name));
                    return Json.Make("threads", threads);
                case "stackTrace":
                {
                    var thread = FindThread(Json.Long(arguments, "threadId"));
                    var frames = thread.StackFrames;
                    var start = (int)(Json.Long(arguments, "startFrame") ?? 0);
                    var levels = (int)(Json.Long(arguments, "levels") ?? 20);
                    var listed = new List<object>();
                    for (var i = start; i < Math.Min(frames.Count, start + levels); i++)
                    {
                        var frame = (StackFrame2)frames.Item(i + 1);
                        var id = Remember(new FrameRef { Thread = thread, Frame = frame });
                        listed.Add(Json.Make("id", id, "name", frame.FunctionName,
                            "source", string.IsNullOrEmpty(frame.FileName) ? null : Json.Make("path", frame.FileName), "line", (long)frame.LineNumber));
                    }
                    return Json.Make("stackFrames", listed, "totalFrames", (long)frames.Count);
                }
                case "scopes":
                {
                    if (!(Recall(Json.Long(arguments, "frameId")) is FrameRef frame)) throw new InvalidOperationException("that frame is no longer available");
                    var id = Remember(new LocalsRef { Frame = frame });
                    return Json.Make("scopes", new List<object> { Json.Make("name", "Locals", "variablesReference", id, "expensive", false) });
                }
                case "variables":
                {
                    var target = Recall(Json.Long(arguments, "variablesReference"));
                    Expressions values;
                    if (target is LocalsRef locals)
                    {
                        if (dbg.CurrentThread?.ID != locals.Frame.Thread.ID) dbg.CurrentThread = locals.Frame.Thread;
                        dbg.CurrentStackFrame = (StackFrame)locals.Frame.Frame;
                        values = locals.Frame.Frame.Locals;
                    }
                    else if (target is Expression parent) values = parent.DataMembers;
                    else throw new InvalidOperationException("that value is no longer available");
                    var listed = new List<object>();
                    for (var i = 1; i <= Math.Min(values.Count, MaxChildren); i++)
                    {
                        try
                        {
                            var value = values.Item(i);
                            var members = value.DataMembers;
                            listed.Add(Json.Make("name", value.Name, "type", value.Type, "value", value.Value,
                                "variablesReference", members != null && members.Count > 0 ? Remember(value) : 0L));
                        }
                        catch (COMException) { /* the debugger cannot show this value */ }
                    }
                    return Json.Make("variables", listed);
                }
                case "next":
                case "stepIn":
                case "stepOut":
                    Select(Json.Long(arguments, "threadId"));
                    Forget();
                    if (command == "next") dbg.StepOver(false);
                    else if (command == "stepIn") dbg.StepInto(false);
                    else dbg.StepOut(false);
                    return Json.Make();
                case "continue":
                    Forget();
                    dbg.Go(false);
                    return Json.Make("allThreadsContinued", true);
                case "pause":
                    dbg.Break(false);
                    return Json.Make();
                case "exceptionInfo":
                    return lastException ?? Json.Make("exceptionId", "unknown", "description", "");
                case "setExceptionBreakpoints":
                    if (Json.List(Json.Get(arguments, "filters")).Count > 0) throw new InvalidOperationException("exception filters are not supported yet");
                    return Json.Make();
                default:
                    throw new InvalidOperationException($"{command} is not supported");
            }
        });

        DteThread FindThread(long? id)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            var dbg = dte.Debugger;
            if (id != null)
                foreach (DteThread t in dbg.CurrentProgram?.Threads ?? (IEnumerable)new object[0])
                    if (t.ID == id.Value) return t;
            return dbg.CurrentThread ?? throw new InvalidOperationException($"no thread {id}");
        }

        void Select(long? id)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            var thread = FindThread(id);
            if (dte.Debugger.CurrentThread?.ID != thread.ID) dte.Debugger.CurrentThread = thread;
        }

        // -- Visual Studio's events, as debugger events ---------------------------------------------

        void Send(string name, Dictionary<string, object> body) =>
            session?.Debugger(Json.Make("type", "event", "event", name, "body", body));

        // -- the debug windows and screenshots ---------------------------------------------------------

        const string LocalsWindow = "{4A18F9D0-B838-11D0-93EB-00A0C90F2734}";   // EnvDTE.Constants.vsWindowKindLocals
        const string AutosWindow = "{F2E84780-2AF1-11D1-A7FA-00A0C9110051}";    // vsWindowKindAutoLocals
        const string CallStackWindow = "{0504FF91-9D61-11D0-A794-00A0C9110051}"; // vsWindowKindCallStack

        [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr window, out Rect rect);
        [DllImport("user32.dll")] static extern bool PrintWindow(IntPtr window, IntPtr dc, uint flags);
        const uint RenderFullContent = 2; // PW_RENDERFULLCONTENT: also WPF and DirectX content, even when covered

        [StructLayout(LayoutKind.Sequential)]
        struct Rect { public int Left, Top, Right, Bottom; }

        public string ShowDebugWindows() => OnMain(ShowDebugWindowsOnMain);

        // Visual Studio's debug layout puts the code on top, Autos/Locals bottom left and Call Stack bottom right.
        // At every stop of an AutoDebug session, bring the right tabs forward so that layout shows values:
        // Locals when the frame has locals or arguments (never an empty window), else Autos. The code document
        // stays in front. The developer's own window arrangement is not moved.
        string ShowDebugWindowsOnMain()
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            var count = 0;
            try
            {
                var frame = dte.Debugger.CurrentStackFrame;
                count = (frame?.Locals?.Count ?? 0) + (frame?.Arguments?.Count ?? 0);
            }
            catch (COMException) { /* no frame: Autos below */ }
            var variables = count > 0 ? "Locals" : "Autos";
            var document = dte.ActiveDocument;
            Show(CallStackWindow);
            Show(count > 0 ? LocalsWindow : AutosWindow);
            try { document?.Activate(); } catch (COMException) { /* the document closed */ }
            return variables;
        }

        void Show(string kind)
        {
            try
            {
                var window = dte.Windows.Item(kind);
                window.Visible = true;
                window.Activate();
            }
            catch (Exception error) when (error is COMException || error is ArgumentException)
            {
                Log($"could not show a debug window: {error.Message}");
            }
        }

        public Dictionary<string, object> Screenshot(string file) => ThreadHelper.JoinableTaskFactory.Run(async () =>
        {
            await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();
            var variables = ShowDebugWindowsOnMain();
            var main = dte.MainWindow;
            if (main.WindowState == vsWindowState.vsWindowStateMinimize) main.WindowState = vsWindowState.vsWindowStateNormal;
            await Task.Delay(500); // let the windows that were brought forward paint
            await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();
            var handle = new IntPtr(main.HWnd);
            if (!GetWindowRect(handle, out var rect)) throw new InvalidOperationException("could not read Visual Studio's window size");
            var width = rect.Right - rect.Left;
            var height = rect.Bottom - rect.Top;
            if (width <= 0 || height <= 0) throw new InvalidOperationException("Visual Studio's window has no size");
            using (var picture = new Bitmap(width, height))
            {
                using (var graphics = Graphics.FromImage(picture))
                {
                    var dc = graphics.GetHdc();
                    try
                    {
                        if (!PrintWindow(handle, dc, RenderFullContent)) throw new InvalidOperationException("Windows could not draw Visual Studio's window");
                    }
                    finally { graphics.ReleaseHdc(dc); }
                }
                Directory.CreateDirectory(Path.GetDirectoryName(file));
                picture.Save(file, ImageFormat.Png);
            }
            Log($"saved a screenshot: {file}");
            return Json.Make("file", file, "width", (long)width, "height", (long)height, "variables_window", variables);
        });

        void OnBreak(dbgEventReason reason, ref dbgExecutionAction action)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            if (session == null) return;
            ShowDebugWindowsOnMain();
            var why = reason switch
            {
                dbgEventReason.dbgEventReasonBreakpoint => "breakpoint",
                dbgEventReason.dbgEventReasonStep => "step",
                dbgEventReason.dbgEventReasonUserBreak => "pause",
                dbgEventReason.dbgEventReasonExceptionThrown => "exception",
                dbgEventReason.dbgEventReasonExceptionNotHandled => "exception",
                _ => "pause",
            };
            Send("stopped", Json.Make("reason", why, "threadId", (long)(dte.Debugger.CurrentThread?.ID ?? 0)));
            var events = session;
            Task.Run(() => events?.BindingChanged());
        }

        void OnRun(dbgEventReason reason)
        {
            Forget();
            Send("continued", Json.Make("allThreadsContinued", true));
        }

        void OnDesign(dbgEventReason reason)
        {
            Forget();
            var events = session;
            if (events == null) return;
            session = null;
            Send("exited", Json.Make("exitCode", exitCode));
            events.Debugger(Json.Make("type", "event", "event", "terminated", "body", Json.Make()));
            events.Ended(reason == dbgEventReason.dbgEventReasonDetachProgram ? "the debugger detached" : "the program exited", exitCode);
        }

        void OnException(string type, string name, int code, string description, ref dbgExceptionAction action)
        {
            lastException = Json.Make("exceptionId", string.IsNullOrEmpty(name) ? type : name, "description", description ?? "");
        }

        // Debug engine events: output, exit code and breakpoint binding.
        public int Event(IDebugEngine2 engine, IDebugProcess2 process, IDebugProgram2 program, IDebugThread2 thread,
            IDebugEvent2 debugEvent, ref Guid riidEvent, uint attributes)
        {
            try
            {
                var events = session;
                switch (debugEvent)
                {
                    case IDebugOutputStringEvent2 output when events != null:
                        if (output.GetString(out var text) == VSConstants.S_OK && !string.IsNullOrEmpty(text))
                            Send("output", Json.Make("category", "stdout", "output", text));
                        break;
                    case IDebugProgramDestroyEvent2 destroyed:
                        if (destroyed.GetExitCode(out var code) == VSConstants.S_OK) exitCode = code;
                        break;
                    case IDebugBreakpointBoundEvent2 _:
                    case IDebugBreakpointErrorEvent2 _:
                        if (events != null) Task.Run(() => events.BindingChanged());
                        break;
                }
            }
            catch (Exception error)
            {
                Log($"error handling a debugger event: {error.Message}");
            }
            return VSConstants.S_OK;
        }
    }
}
