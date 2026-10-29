// Visual Studio's side of the relay: launch targets from the startup projects (C/C++ and
// .NET), the Approve dialog, builds, breakpoints, and the debugger, shaped as Debug Adapter
// Protocol requests and events. It reads what the debugger shows (locals and their members,
// registers, machine code, memory, modules) and places breakpoints, log points (tracepoints)
// and data breakpoints; it never evaluates an expression the agent wrote or changes a value.
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
using EnvDTE90;
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
        static readonly Guid ManagedEngine = new Guid("2E36F1D4-B23C-435D-AB41-18E608940038");   // .NET (Core) and .NET 5+
        static readonly Guid FrameworkEngine = new Guid("FB0D4648-F776-4980-95F8-BB7F36EBC1EE"); // .NET Framework 4
        static readonly Guid RegistersFilter = new Guid("223AE797-BD09-4F28-8241-2763BDC5F713");  // guidFilterRegisters
        static readonly Guid LocalsFilter = new Guid("E74721BB-10C0-40F5-807F-920D37F95419");     // guidFilterLocalsPlusArgs
        // Exception filters the agent can switch on, as Visual Studio's Exception Settings groups.
        static readonly (string Id, string Group, string Label)[] ExceptionGroups =
        {
            ("cpp", "C++ Exceptions", "C++ exceptions when thrown"),
            ("win32", "Win32 Exceptions", "Win32 exceptions (access violations, ...) when thrown"),
            ("clr", "Common Language Runtime Exceptions", ".NET exceptions when thrown"),
        };
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
        // The launched program, to read its exit code when the debug engine's destroy event comes after design mode
        // (or not at all): the run then ended with "exit code None" although the program exited with 1.
        System.Diagnostics.Process program;
        Dictionary<string, object> lastException;
        readonly Dictionary<string, (string UniqueName, string Configuration)> buildTargets = new Dictionary<string, (string, string)>();
        // Frames and values the server may ask about; cleared whenever the program runs again.
        readonly Dictionary<long, object> references = new Dictionary<long, object>();
        long nextReference = 1;
        // Where the program last stopped, as the debug engine reports it: for registers, machine code, memory and
        // instruction steps, which Visual Studio's automation does not offer.
        IDebugProgram2 stopProgram;
        IDebugThread2 stopThread;
        readonly Dictionary<string, IDebugMemoryContext2> memory = new Dictionary<string, IDebugMemoryContext2>(StringComparer.OrdinalIgnoreCase);
        // Loaded modules, from the debug engine's module events.
        readonly Dictionary<string, Dictionary<string, object>> modules = new Dictionary<string, Dictionary<string, object>>(StringComparer.OrdinalIgnoreCase);
        // What this session changed and must put back: exception settings, data breakpoints, frozen threads.
        readonly List<Action> restore = new List<Action>();
        readonly List<Breakpoint> dataBreakpoints = new List<Breakpoint>();
        readonly List<DteThread> frozen = new List<DteThread>();
        // The program's console window, read for its output (a console program's own window is not an output event).
        ConsoleReader console;
        // How much of the Output window's Debug pane was read: log points (tracepoints) print there.
        int debugPaneRead;
        readonly HashSet<string> engineOutput = new HashSet<string>(StringComparer.Ordinal);

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
            launch.Add(Json.Make("name", "Attach to a process (.NET)", "type", "visualstudio", "request", "attach",
                "processId", "${command:pickProcess}", "engine", "managed"));
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
            if (IsManaged(project.FullName)) return ManagedTarget(project, configuration, targetPath, projectDir);
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

        static bool IsManaged(string file)
        {
            var extension = Path.GetExtension(file ?? "").ToLowerInvariant();
            return extension == ".csproj" || extension == ".vbproj" || extension == ".fsproj";
        }

        static string Property(Properties properties, string name)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            try { return Convert.ToString(properties?.Item(name)?.Value); }
            catch (ArgumentException) { return null; }
            catch (COMException) { return null; }
        }

        // A .NET project (C#, Visual Basic, F#): its program (the .exe, else dotnet with the .dll) and the profile in
        // Properties/launchSettings.json that Visual Studio starts ("commandName": "Project").
        Dictionary<string, object> ManagedTarget(Project project, string configuration, string targetPath, string projectDir)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            if (string.IsNullOrWhiteSpace(targetPath))
            {
                var output = Property(project.ConfigurationManager?.ActiveConfiguration?.Properties, "OutputPath");
                var file = Property(project.Properties, "OutputFileName");
                if (!string.IsNullOrEmpty(output) && !string.IsNullOrEmpty(file)) targetPath = Path.Combine(projectDir, output, file);
            }
            if (string.IsNullOrWhiteSpace(targetPath)) return null;
            var framework = (Property(project.Properties, "TargetFrameworkMoniker") ?? "").StartsWith(".NETFramework", StringComparison.OrdinalIgnoreCase);
            var profile = LaunchProfile(projectDir);
            var arguments = Json.Str(profile, "commandLineArgs") ?? "";
            var cwd = Json.Str(profile, "workingDirectory");
            var env = new Dictionary<string, object>();
            foreach (var pair in Json.Obj(Json.Get(profile, "environmentVariables"))) env[pair.Key] = Convert.ToString(pair.Value);
            var native = Json.Get(profile, "nativeDebugging") is bool mixed && mixed;
            var program = targetPath;
            if (!framework && targetPath.EndsWith(".dll", StringComparison.OrdinalIgnoreCase))
            {
                var host = Path.ChangeExtension(targetPath, ".exe");
                if (File.Exists(host)) program = host;
                else
                {
                    program = DotnetPath();
                    arguments = $"\"{targetPath}\" {arguments}".Trim();
                }
            }
            var engine = framework ? (native ? "mixed_framework" : "framework") : (native ? "mixed" : "managed");
            return Json.Make("name", $"{project.Name} ({configuration})", "type", "visualstudio", "request", "launch",
                "program", program, "args", string.IsNullOrWhiteSpace(arguments) ? new List<object>() : new List<object> { arguments },
                "cwd", string.IsNullOrWhiteSpace(cwd) ? projectDir : Path.Combine(projectDir, cwd), "env", env,
                "project", project.Name, "configuration", configuration, "engine", engine);
        }

        static Dictionary<string, object> LaunchProfile(string projectDir)
        {
            try
            {
                var file = Path.Combine(projectDir, "Properties", "launchSettings.json");
                if (!File.Exists(file)) return new Dictionary<string, object>();
                var profiles = Json.Obj(Json.Get(Json.Obj(Json.Parse(File.ReadAllText(file))), "profiles"));
                return profiles.Values.Select(Json.Obj).FirstOrDefault(p => Json.Str(p, "commandName") == "Project")
                       ?? new Dictionary<string, object>();
            }
            catch (Exception) { return new Dictionary<string, object>(); } // an unreadable profile: start without it
        }

        static string DotnetPath()
        {
            foreach (var folder in (System.Environment.GetEnvironmentVariable("PATH") ?? "").Split(';'))
            {
                try
                {
                    var candidate = Path.Combine(folder.Trim(), "dotnet.exe");
                    if (File.Exists(candidate)) return candidate;
                }
                catch (ArgumentException) { /* not a folder */ }
            }
            return Path.Combine(System.Environment.GetFolderPath(System.Environment.SpecialFolder.ProgramFiles), "dotnet", "dotnet.exe");
        }

        // The debug engines for a configuration's "engine": native (C, C++), managed (.NET), framework (.NET
        // Framework), or both kinds at once (mixed: native code and .NET in one process).
        static Guid[] Engines(string engine)
        {
            switch (engine)
            {
                case "managed": return new[] { ManagedEngine };
                case "framework": return new[] { FrameworkEngine };
                case "mixed": return new[] { NativeEngine, ManagedEngine };
                case "mixed_framework": return new[] { NativeEngine, FrameworkEngine };
                default: return new[] { NativeEngine };
            }
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

        public object AddBreakpoint(string file, int line, BreakpointOptions options) => OnMain(() =>
        {
            var (count, kind) = HitCount(options.HitCondition);
            var added = (Breakpoint)dte.Debugger.Breakpoints.Add(File: file, Line: line, Column: Math.Max(options.Column, 1),
                Condition: options.Condition ?? "", ConditionType: dbgBreakpointConditionType.dbgBreakpointConditionTypeWhenTrue,
                HitCount: count, HitCountType: kind).Item(1);
            if (options.LogMessage != null && added is Breakpoint2 tracepoint)
            {
                // A tracepoint: Visual Studio prints the message to its Output window and does not stop.
                tracepoint.Message = options.LogMessage;
                tracepoint.BreakWhenHit = false;
            }
            return (object)added;
        });

        // Visual Studio counts hits as "equal to", "at least" or "a multiple of".
        static (int Count, dbgHitCountType Kind) HitCount(string condition)
        {
            if (string.IsNullOrWhiteSpace(condition)) return (0, dbgHitCountType.dbgHitCountTypeNone);
            var text = condition.Trim();
            var digits = new string(text.Where(char.IsDigit).ToArray());
            var number = int.Parse(digits, System.Globalization.CultureInfo.InvariantCulture);
            if (text.StartsWith(">=", StringComparison.Ordinal)) return (number, dbgHitCountType.dbgHitCountTypeGreaterOrEqual);
            if (text.StartsWith(">", StringComparison.Ordinal)) return (number + 1, dbgHitCountType.dbgHitCountTypeGreaterOrEqual);
            if (text.StartsWith("%", StringComparison.Ordinal)) return (number, dbgHitCountType.dbgHitCountTypeMultiple);
            if (text.StartsWith("<", StringComparison.Ordinal))
                throw new InvalidOperationException("Visual Studio counts hits as =, >= or every Nth (%); not fewer than");
            return (number, dbgHitCountType.dbgHitCountTypeEqual);
        }

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
            "supportsExceptionInfoRequest", true, "supportsFunctionBreakpoints", true, "supportsConditionalBreakpoints", true,
            "supportsHitConditionalBreakpoints", true, "supportsLogPoints", true, "supportsDataBreakpoints", true,
            "supportsValueFormattingOptions", true, "supportsModulesRequest", true, "supportsSingleThreadExecutionRequests", true,
            "supportsSteppingGranularity", true, "supportsDisassembleRequest", true, "supportsReadMemoryRequest", true,
            "supportsExceptionOptions", true,
            "exceptionBreakpointFilters", ExceptionGroups.Select(g => (object)Json.Make("filter", g.Id, "label", g.Label, "default", false)).ToList());

        public bool Launch(Dictionary<string, object> configuration, IBackendEvents events)
        {
            exitCode = null;
            lastException = null;
            program?.Dispose();
            program = null;
            session = events;
            var attach = Json.Str(configuration, "request") == "attach";
            var chosen = Engines(Json.Str(configuration, "engine"));
            stopProgramIsManaged = chosen.Length == 1 && chosen[0] != NativeEngine;
            stopProgram = null;
            stopThread = null;
            lock (engineOutput) engineOutput.Clear();
            OnMain(() => ReadDebugPane(skip: true)); // what an earlier session printed there is not this program's
            Restore();
            lock (modules) modules.Clear();
            var info = new VsDebugTargetInfo4
            {
                guidLaunchDebugEngine = chosen[0],
                dwDebugEngineCount = (uint)chosen.Length,
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
            var size = Marshal.SizeOf(typeof(Guid));
            var engines = Marshal.AllocCoTaskMem(size * chosen.Length);
            try
            {
                for (var i = 0; i < chosen.Length; i++) Marshal.StructureToPtr(chosen[i], engines + i * size, false);
                info.pDebugEngines = engines;
                var started = new VsDebugTargetProcessInfo[1];
                OnMain(() => ((IVsDebugger4)debugger).LaunchDebugTargets4(1, new[] { info }, started));
                if (!attach) Follow(started[0].dwProcessId);
                return true;
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

        sealed class FrameRef { public DteThread Thread; public StackFrame2 Frame; public int Index; }
        sealed class LocalsRef { public FrameRef Frame; }
        sealed class RegistersRef { public FrameRef Frame; }
        sealed class ValueRef { public Expression Value; public string Path; }
        sealed class PropertyRef { public IDebugProperty2 Property; }

        // Every debugged process's programs: Visual Studio can debug a program and the processes it starts.
        List<(string Process, EnvDTE.Program Program)> Programs()
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            var found = new List<(string, EnvDTE.Program)>();
            try
            {
                foreach (EnvDTE.Process process in dte.Debugger.DebuggedProcesses)
                    foreach (EnvDTE.Program program in process.Programs)
                        found.Add((Path.GetFileName(process.Name), program));
            }
            catch (COMException) { /* the list changed while it was read */ }
            if (found.Count == 0 && dte.Debugger.CurrentProgram != null) found.Add(("", dte.Debugger.CurrentProgram));
            return found;
        }

        IEnumerable<DteThread> AllThreads()
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            foreach (var (_, program) in Programs())
                foreach (DteThread t in program.Threads) yield return t;
        }

        // -- the debug engine's view of the stop: frames with addresses, registers, machine code, memory ------------

        uint StopThreadId()
        {
            if (stopThread == null) return 0;
            return stopThread.GetThreadId(out var id) == VSConstants.S_OK ? id : 0;
        }

        List<IDebugStackFrame2> EngineFrames(long threadId)
        {
            var frames = new List<IDebugStackFrame2>();
            if (stopThread == null || StopThreadId() != threadId) return frames;
            if (stopThread.EnumFrameInfo(enum_FRAMEINFO_FLAGS.FIF_FRAME, 10, out var listed) != VSConstants.S_OK || listed == null) return frames;
            if (listed.GetCount(out var count) != VSConstants.S_OK || count == 0) return frames;
            var info = new FRAMEINFO[count];
            uint fetched = 0;
            listed.Next(count, info, ref fetched);
            for (var i = 0; i < fetched; i++) frames.Add(info[i].m_pFrame);
            return frames;
        }

        string Address(IDebugMemoryContext2 context)
        {
            if (context == null) return null;
            var info = new CONTEXT_INFO[1];
            if (context.GetInfo(enum_CONTEXT_INFO_FIELDS.CIF_ADDRESS, info) != VSConstants.S_OK || string.IsNullOrEmpty(info[0].bstrAddress)) return null;
            var address = info[0].bstrAddress.Trim();
            lock (memory) memory[address] = context;
            return address;
        }

        string InstructionAddress(IDebugStackFrame2 frame)
        {
            if (frame == null || frame.GetCodeContext(out var code) != VSConstants.S_OK) return null;
            return Address(code);
        }

        static List<DEBUG_PROPERTY_INFO> Properties(IEnumDebugPropertyInfo2 listed)
        {
            var found = new List<DEBUG_PROPERTY_INFO>();
            if (listed == null) return found;
            var one = new DEBUG_PROPERTY_INFO[1];
            while (found.Count < 500 && listed.Next(1, one, out var fetched) == VSConstants.S_OK && fetched == 1) found.Add(one[0]);
            return found;
        }

        const enum_DEBUGPROP_INFO_FLAGS PropertyFields = enum_DEBUGPROP_INFO_FLAGS.DEBUGPROP_INFO_NAME | enum_DEBUGPROP_INFO_FLAGS.DEBUGPROP_INFO_VALUE
            | enum_DEBUGPROP_INFO_FLAGS.DEBUGPROP_INFO_TYPE | enum_DEBUGPROP_INFO_FLAGS.DEBUGPROP_INFO_PROP | enum_DEBUGPROP_INFO_FLAGS.DEBUGPROP_INFO_ATTRIB;

        List<DEBUG_PROPERTY_INFO> FrameProperties(IDebugStackFrame2 frame, Guid filter, uint radix)
        {
            if (frame == null) return new List<DEBUG_PROPERTY_INFO>();
            return frame.EnumProperties(PropertyFields, radix, ref filter, 2000, out _, out var listed) == VSConstants.S_OK
                ? Properties(listed) : new List<DEBUG_PROPERTY_INFO>();
        }

        object PropertyVariable(DEBUG_PROPERTY_INFO info)
        {
            var expandable = info.pProperty != null && (info.dwAttrib & enum_DBG_ATTRIB_FLAGS.DBG_ATTRIB_OBJ_IS_EXPANDABLE) != 0;
            return Json.Make("name", info.bstrName, "type", info.bstrType ?? "", "value", info.bstrValue ?? "",
                "variablesReference", expandable ? Remember(new PropertyRef { Property = info.pProperty }) : 0L);
        }

        // The memory address of each local and argument, for readMemory and data breakpoints.
        Dictionary<string, string> LocalAddresses(FrameRef frame)
        {
            var addresses = new Dictionary<string, string>(StringComparer.Ordinal);
            var engine = EngineFrames(frame.Thread.ID);
            if (frame.Index >= engine.Count) return addresses;
            foreach (var local in FrameProperties(engine[frame.Index], LocalsFilter, 10))
            {
                try
                {
                    if (local.pProperty != null && local.pProperty.GetMemoryContext(out var context) == VSConstants.S_OK)
                    {
                        var address = Address(context);
                        if (address != null && local.bstrName != null) addresses[local.bstrName] = address;
                    }
                }
                catch (COMException) { /* no address: a register variable, or optimized away */ }
            }
            return addresses;
        }

        IDebugMemoryContext2 Memory(string reference, long offset)
        {
            IDebugMemoryContext2 context;
            lock (memory) memory.TryGetValue(reference ?? "", out context);
            if (context == null) throw new InvalidOperationException("that address is no longer available; read the stack or variables again");
            if (offset == 0) return context;
            var moved = offset > 0 ? context.Add((ulong)offset, out var forward) : context.Subtract((ulong)-offset, out forward);
            if (moved != VSConstants.S_OK) throw new InvalidOperationException("cannot move to that offset");
            return forward;
        }

        Dictionary<string, object> Disassemble(Dictionary<string, object> arguments)
        {
            if (stopProgram == null) throw new InvalidOperationException("the debugger has not stopped the program");
            if (!(Memory(Json.Str(arguments, "memoryReference"), 0) is IDebugCodeContext2 code)) throw new InvalidOperationException("that is not an address of code");
            if (stopProgram.GetDisassemblyStream(enum_DISASSEMBLY_STREAM_SCOPE.DSS_HUGE, code, out var stream) != VSConstants.S_OK || stream == null)
                throw new InvalidOperationException("Visual Studio cannot disassemble here");
            var offset = Json.Long(arguments, "instructionOffset") ?? 0;
            var count = (int)Math.Max(1, Math.Min(Json.Long(arguments, "instructionCount") ?? 16, 200));
            stream.Seek(enum_SEEK_START.SEEK_START_CODECONTEXT, code, 0, offset);
            var data = new DisassemblyData[count];
            stream.Read((uint)count, enum_DISASSEMBLY_STREAM_FIELDS.DSF_ALL, out var read, data);
            var instructions = new List<object>();
            for (var i = 0; i < read; i++)
            {
                var item = data[i];
                var row = Json.Make("address", item.bstrAddress, "instruction", $"{item.bstrOpcode} {item.bstrOperands}".Trim());
                if (!string.IsNullOrEmpty(item.bstrSymbol)) row["symbol"] = item.bstrSymbol;
                if (!string.IsNullOrEmpty(item.bstrDocumentUrl) && File.Exists(item.bstrDocumentUrl))
                {
                    row["location"] = Json.Make("path", item.bstrDocumentUrl);
                    row["line"] = (long)item.posBeg.dwLine + 1;
                }
                instructions.Add(row);
            }
            return Json.Make("instructions", instructions);
        }

        Dictionary<string, object> ReadMemory(Dictionary<string, object> arguments)
        {
            if (stopProgram == null) throw new InvalidOperationException("the debugger has not stopped the program");
            var context = Memory(Json.Str(arguments, "memoryReference"), Json.Long(arguments, "offset") ?? 0);
            var count = (int)Math.Max(1, Math.Min(Json.Long(arguments, "count") ?? 64, 4096));
            if (stopProgram.GetMemoryBytes(out var bytes) != VSConstants.S_OK || bytes == null) throw new InvalidOperationException("Visual Studio cannot read this program's memory");
            var buffer = new byte[count];
            uint unreadable = 0;
            bytes.ReadAt(context, (uint)count, buffer, out var read, ref unreadable);
            var result = Json.Make("address", Address(context), "data", Convert.ToBase64String(buffer, 0, (int)read));
            if (unreadable > 0) result["unreadableBytes"] = (long)unreadable;
            return result;
        }

        // -- exception settings and data breakpoints: changed for the session, put back after it ---------------------

        void Restore()
        {
            List<Action> undo;
            lock (restore) { undo = restore.ToList(); restore.Clear(); }
            OnMain(() =>
            {
                for (var i = undo.Count - 1; i >= 0; i--)
                {
                    try { undo[i](); } catch (Exception error) { Log($"could not put a setting back: {error.Message}"); }
                }
                foreach (var data in dataBreakpoints) { try { data.Delete(); } catch (COMException) { /* already gone */ } }
                dataBreakpoints.Clear();
                Thaw();
            });
        }

        void Thaw()
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            foreach (var thread in frozen) { try { thread.Thaw(); } catch (COMException) { /* the thread ended */ } }
            frozen.Clear();
        }

        void FreezeOthers(long? threadId)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            foreach (var thread in AllThreads())
            {
                if (thread.ID == threadId || thread.IsFrozen) continue;
                thread.Freeze();
                frozen.Add(thread);
            }
        }

        void SetExceptions(Dictionary<string, object> arguments)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            var groups = ((Debugger3)dte.Debugger).ExceptionGroups;
            void BreakWhenThrown(ExceptionSettings settings, ExceptionSetting setting)
            {
                if (setting.BreakWhenThrown) return;
                settings.SetBreakWhenThrown(true, setting);
                lock (restore) restore.Add(() => settings.SetBreakWhenThrown(false, setting));
            }
            foreach (var id in Json.List(Json.Get(arguments, "filters")).Select(Convert.ToString))
            {
                var group = ExceptionGroups.FirstOrDefault(g => g.Id == id);
                if (group.Id == null) throw new InvalidOperationException($"no exception filter {id}");
                var settings = groups.Item(group.Group);
                foreach (ExceptionSetting setting in settings) BreakWhenThrown(settings, setting);
            }
            foreach (var option in Json.List(Json.Get(arguments, "exceptionOptions")).Select(Json.Obj))
            {
                var path = Json.List(Json.Get(option, "path")).Select(Json.Obj).ToList();
                var names = path.Count == 0 ? new List<string>() : Json.List(Json.Get(path[path.Count - 1], "names")).Select(Convert.ToString).ToList();
                // Visual Studio always stops when an exception is not handled; "unhandled" therefore changes nothing.
                if (Json.Str(option, "breakMode") == "unhandled") continue;
                foreach (var name in names)
                {
                    var (settings, setting) = FindException(groups, name);
                    if (setting == null)
                    {
                        // Not listed yet: add it to the group of this program's code.
                        settings = groups.Item(stopProgramIsManaged ? "Common Language Runtime Exceptions" : "C++ Exceptions");
                        setting = settings.NewException(name, 0);
                        var added = settings;
                        lock (restore) restore.Add(() => added.Remove(name));
                    }
                    BreakWhenThrown(settings, setting);
                }
            }
        }

        (ExceptionSettings, ExceptionSetting) FindException(EnvDTE90.ExceptionGroups groups, string name)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            foreach (var (_, group, _) in ExceptionGroups)
            {
                try
                {
                    var settings = groups.Item(group);
                    foreach (ExceptionSetting setting in settings)
                        if (string.Equals(setting.Name, name, StringComparison.Ordinal)) return (settings, setting);
                }
                catch (Exception error) when (error is COMException || error is ArgumentException) { /* no such group here */ }
            }
            return (null, null);
        }

        bool stopProgramIsManaged;

        Dictionary<string, object> SetDataBreakpoints(Dictionary<string, object> arguments)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            foreach (var data in dataBreakpoints) { try { data.Delete(); } catch (COMException) { /* already gone */ } }
            dataBreakpoints.Clear();
            var answers = new List<object>();
            foreach (var item in Json.List(Json.Get(arguments, "breakpoints")).Select(Json.Obj))
            {
                var path = Json.Str(item, "dataId");
                try
                {
                    // Visual Studio watches the variable's memory: the debugger reads the variable's address, it runs nothing.
                    var added = (Breakpoint)dte.Debugger.Breakpoints.Add(Data: path, DataCount: 1).Item(1);
                    dataBreakpoints.Add(added);
                    answers.Add(Json.Make("id", (long)dataBreakpoints.Count, "verified", added.Children == null || added.Children.Count > 0 || added.Enabled));
                }
                catch (Exception error) when (error is COMException || error is ArgumentException)
                {
                    answers.Add(Json.Make("verified", false, "message", error.Message));
                }
            }
            return Json.Make("breakpoints", answers);
        }

        static readonly System.Text.RegularExpressions.Regex PlainPath = new System.Text.RegularExpressions.Regex(
            @"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*|->[A-Za-z_$][\w$]*|\[\d{1,9}\])*$");

        // -- requests -------------------------------------------------------------------------------------------

        public Dictionary<string, object> Request(string command, Dictionary<string, object> arguments) => OnMain(() =>
        {
            var dbg = dte.Debugger;
            switch (command)
            {
                case "threads":
                {
                    var threads = new List<object>();
                    var programs = Programs();
                    foreach (var (process, program) in programs)
                        foreach (DteThread t in program.Threads)
                        {
                            var name = string.IsNullOrEmpty(t.Name) ? $"thread {t.ID}" : t.Name;
                            threads.Add(Json.Make("id", (long)t.ID, "name", programs.Count > 1 && process.Length > 0 ? $"{process}: {name}" : name));
                        }
                    return Json.Make("threads", threads);
                }
                case "stackTrace":
                {
                    var thread = FindThread(Json.Long(arguments, "threadId"));
                    var frames = thread.StackFrames;
                    var start = (int)(Json.Long(arguments, "startFrame") ?? 0);
                    var levels = (int)(Json.Long(arguments, "levels") ?? 20);
                    var engine = EngineFrames(thread.ID);
                    var listed = new List<object>();
                    for (var i = start; i < Math.Min(frames.Count, start + levels); i++)
                    {
                        var frame = (StackFrame2)frames.Item(i + 1);
                        var id = Remember(new FrameRef { Thread = thread, Frame = frame, Index = i });
                        var item = Json.Make("id", id, "name", frame.FunctionName,
                            "source", string.IsNullOrEmpty(frame.FileName) ? null : Json.Make("path", frame.FileName), "line", (long)frame.LineNumber);
                        var address = i < engine.Count ? InstructionAddress(engine[i]) : null;
                        if (address != null) item["instructionPointerReference"] = address;
                        if (!string.IsNullOrEmpty(frame.Module)) item["moduleId"] = frame.Module;
                        listed.Add(item);
                    }
                    return Json.Make("stackFrames", listed, "totalFrames", (long)frames.Count);
                }
                case "scopes":
                {
                    if (!(Recall(Json.Long(arguments, "frameId")) is FrameRef frame)) throw new InvalidOperationException("that frame is no longer available");
                    var scopes = new List<object> { Json.Make("name", "Locals", "variablesReference", Remember(new LocalsRef { Frame = frame }), "expensive", false) };
                    if (frame.Index < EngineFrames(frame.Thread.ID).Count)
                        scopes.Add(Json.Make("name", "Registers", "variablesReference", Remember(new RegistersRef { Frame = frame }), "expensive", true));
                    return Json.Make("scopes", scopes);
                }
                case "variables":
                    return Variables(arguments);
                case "dataBreakpointInfo":
                {
                    var name = Json.Str(arguments, "name") ?? "";
                    var target = Recall(Json.Long(arguments, "variablesReference"));
                    var path = target is LocalsRef ? name
                        : target is ValueRef parent && parent.Path != null ? (name.StartsWith("[", StringComparison.Ordinal) ? parent.Path + name : $"{parent.Path}.{name}")
                        : null;
                    if (path == null || !PlainPath.IsMatch(path))
                        return Json.Make("dataId", null, "description", $"{name} has no plain path Visual Studio can watch");
                    return Json.Make("dataId", path, "description", path, "accessTypes", new List<object> { "write" });
                }
                case "setDataBreakpoints":
                    return SetDataBreakpoints(arguments);
                case "modules":
                    lock (modules) return Json.Make("modules", modules.Values.Cast<object>().ToList(), "totalModules", (long)modules.Count);
                case "disassemble":
                    return Disassemble(arguments);
                case "readMemory":
                    return ReadMemory(arguments);
                case "next":
                case "stepIn":
                case "stepOut":
                {
                    var threadId = Json.Long(arguments, "threadId");
                    Select(threadId);
                    if (Json.Get(arguments, "singleThread") is bool single && single) FreezeOthers(threadId);
                    Forget();
                    if (Json.Str(arguments, "granularity") == "instruction")
                    {
                        if (stopProgram == null || stopThread == null) throw new InvalidOperationException("the debugger has not stopped the program");
                        var kind = command == "next" ? enum_STEPKIND.STEP_OVER : command == "stepIn" ? enum_STEPKIND.STEP_INTO : enum_STEPKIND.STEP_OUT;
                        if (stopProgram.Step(stopThread, kind, enum_STEPUNIT.STEP_INSTRUCTION) != VSConstants.S_OK)
                            throw new InvalidOperationException("Visual Studio could not step one instruction here");
                        return Json.Make();
                    }
                    if (command == "next") dbg.StepOver(false);
                    else if (command == "stepIn") dbg.StepInto(false);
                    else dbg.StepOut(false);
                    return Json.Make();
                }
                case "continue":
                    if (Json.Get(arguments, "singleThread") is bool alone && alone) FreezeOthers(Json.Long(arguments, "threadId"));
                    Forget();
                    dbg.Go(false);
                    return Json.Make("allThreadsContinued", !(Json.Get(arguments, "singleThread") is bool one && one));
                case "pause":
                    dbg.Break(false);
                    return Json.Make();
                case "exceptionInfo":
                    return lastException ?? Json.Make("exceptionId", "unknown", "description", "");
                case "setExceptionBreakpoints":
                    SetExceptions(arguments);
                    return Json.Make();
                default:
                    throw new InvalidOperationException($"Visual Studio cannot do {command}");
            }
        });

        Dictionary<string, object> Variables(Dictionary<string, object> arguments)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            var dbg = dte.Debugger;
            var target = Recall(Json.Long(arguments, "variablesReference"));
            var hex = Json.Get(Json.Obj(Json.Get(arguments, "format")), "hex") is bool wanted && wanted;
            var first = (int)Math.Max(0, Json.Long(arguments, "start") ?? 0);
            var count = (int)Math.Max(1, Math.Min(Json.Long(arguments, "count") ?? MaxChildren, 1000));
            var listed = new List<object>();
            if (target is RegistersRef registers)
            {
                var engine = EngineFrames(registers.Frame.Thread.ID);
                var frame = registers.Frame.Index < engine.Count ? engine[registers.Frame.Index] : null;
                foreach (var register in FrameProperties(frame, RegistersFilter, hex ? 16u : 10u)) listed.Add(PropertyVariable(register));
                return Json.Make("variables", listed);
            }
            if (target is PropertyRef property)
            {
                var none = Guid.Empty;
                if (property.Property.EnumChildren(PropertyFields, hex ? 16u : 10u, ref none, enum_DBG_ATTRIB_FLAGS.DBG_ATTRIB_ALL, null, 2000, out var children) == VSConstants.S_OK)
                    foreach (var child in Properties(children).Skip(first).Take(count)) listed.Add(PropertyVariable(child));
                return Json.Make("variables", listed);
            }
            Expressions values;
            string parentPath = null;
            Dictionary<string, string> addresses = null;
            if (target is LocalsRef locals)
            {
                if (dbg.CurrentThread?.ID != locals.Frame.Thread.ID) dbg.CurrentThread = locals.Frame.Thread;
                dbg.CurrentStackFrame = (StackFrame)locals.Frame.Frame;
                values = locals.Frame.Frame.Locals;
                addresses = LocalAddresses(locals.Frame);
            }
            else if (target is ValueRef parent)
            {
                values = parent.Value.DataMembers;
                parentPath = parent.Path;
            }
            else throw new InvalidOperationException("that value is no longer available");
            var before = dbg.HexDisplayMode;
            if (hex != before) dbg.HexDisplayMode = hex;
            try
            {
                for (var i = first + 1; i <= Math.Min(values.Count, first + count); i++)
                {
                    try
                    {
                        var value = values.Item(i);
                        var members = value.DataMembers;
                        var path = parentPath == null ? value.Name
                            : value.Name.StartsWith("[", StringComparison.Ordinal) ? parentPath + value.Name : $"{parentPath}.{value.Name}";
                        var item = Json.Make("name", value.Name, "type", value.Type, "value", value.Value,
                            "variablesReference", members != null && members.Count > 0 ? Remember(new ValueRef { Value = value, Path = path }) : 0L);
                        // Arrays and containers: their elements are [0], [1], ...; the server pages through them.
                        if (members != null && members.Count > 0 && (members.Item(1).Name ?? "").StartsWith("[", StringComparison.Ordinal))
                            item["indexedVariables"] = (long)members.Count;
                        if (addresses != null && addresses.TryGetValue(value.Name, out var address)) item["memoryReference"] = address;
                        listed.Add(item);
                    }
                    catch (COMException) { /* the debugger cannot show this value */ }
                }
            }
            finally
            {
                if (hex != before) dbg.HexDisplayMode = before;
            }
            return Json.Make("variables", listed);
        }

        DteThread FindThread(long? id)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            if (id != null)
                foreach (var t in AllThreads())
                    if (t.ID == id.Value) return t;
            return dte.Debugger.CurrentThread ?? throw new InvalidOperationException($"no thread {id}");
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
            var handle = (IntPtr)main.HWnd; // int or IntPtr, depending on the EnvDTE version
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
            Thaw();
            ReadDebugPane();
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

        // Keep a handle to the launched process, so its exit code can be read after it ends.
        void Follow(uint processId)
        {
            if (processId == 0) return;
            try
            {
                var process = System.Diagnostics.Process.GetProcessById((int)processId);
                _ = process.Handle; // opened now, while the process exists
                program = process;
                console?.Dispose();
                console = ConsoleReader.Start(processId, line => Send("output", Json.Make("category", "stdout", "output", line + "\n")), Log);
            }
            catch (Exception error) when (error is ArgumentException || error is InvalidOperationException
                                          || error is System.ComponentModel.Win32Exception)
            {
                Log($"cannot follow process {processId} for its exit code: {error.Message}");
            }
        }

        long? ExitCodeOfProgram()
        {
            try
            {
                if (program != null && program.WaitForExit(3000)) return program.ExitCode;
            }
            catch (Exception error) when (error is InvalidOperationException || error is System.ComponentModel.Win32Exception)
            {
                Log($"cannot read the exit code: {error.Message}");
            }
            return null;
        }

        void OnDesign(dbgEventReason reason)
        {
            Forget();
            var events = session;
            if (events == null) return;
            session = null;
            if (exitCode == null && reason != dbgEventReason.dbgEventReasonDetachProgram) exitCode = ExitCodeOfProgram();
            var reader = console;
            console = null;
            if (reader != null)
            {
                session = events; // the console's last lines still reach this session
                reader.Finish(1500);
                reader.Dispose();
                session = null;
            }
            stopProgram = null;
            stopThread = null;
            session = events;
            ReadDebugPane();
            session = null;
            Restore();
            events.Debugger(Json.Make("type", "event", "event", "exited", "body", Json.Make("exitCode", exitCode)));
            events.Debugger(Json.Make("type", "event", "event", "terminated", "body", Json.Make()));
            events.Ended(reason == dbgEventReason.dbgEventReasonDetachProgram ? "the debugger detached" : "the program exited", exitCode);
        }

        static readonly System.Text.RegularExpressions.Regex DebugPaneNoise = new System.Text.RegularExpressions.Regex(
            @"^('.*' \(.*\): (Loaded|Unloaded)|The thread |The program |Exception thrown at |onecore\\)");

        // New lines in the Output window's Debug pane, where log points (tracepoints) print. Module loads and thread
        // exits are left out, and so is what the debug engine already reported as output.
        void ReadDebugPane(bool skip = false)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            try
            {
                OutputWindowPane pane = null;
                foreach (OutputWindowPane candidate in dte.ToolWindows.OutputWindow.OutputWindowPanes)
                    if (candidate.Name == "Debug") pane = candidate;
                if (pane == null)
                {
                    if (skip) debugPaneRead = 0;
                    return;
                }
                var document = pane.TextDocument;
                var text = document.StartPoint.CreateEditPoint().GetText(document.EndPoint);
                if (text.Length < debugPaneRead) debugPaneRead = 0; // the pane was cleared
                if (skip)
                {
                    debugPaneRead = text.Length;
                    return;
                }
                var fresh = text.Substring(debugPaneRead);
                var end = fresh.LastIndexOf('\n');
                if (end < 0) return;
                debugPaneRead += end + 1;
                foreach (var raw in fresh.Substring(0, end).Split('\n'))
                {
                    var line = raw.TrimEnd('\r');
                    bool reported;
                    lock (engineOutput) reported = engineOutput.Remove(line);
                    if (line.Trim().Length == 0 || reported || DebugPaneNoise.IsMatch(line)) continue;
                    Send("output", Json.Make("category", "console", "output", line + "\n"));
                }
            }
            catch (Exception error) when (error is COMException || error is ArgumentException)
            {
                Log($"could not read the Debug output: {error.Message}");
            }
        }

        // A module (DLL, executable) loaded or unloaded: its path, version and whether its symbols loaded.
        void Module(IDebugModuleLoadEvent2 loaded)
        {
            string message = null;
            var load = 0;
            if (loaded.GetModule(out var module, ref message, ref load) != VSConstants.S_OK || module == null) return;
            var info = new MODULE_INFO[1];
            if (module.GetInfo(enum_MODULE_INFO_FIELDS.MIF_ALLFIELDS, info) != VSConstants.S_OK) return;
            var m = info[0];
            var key = m.m_bstrUrl ?? m.m_bstrName ?? "";
            var entry = Json.Make("id", key, "name", m.m_bstrName, "path", m.m_bstrUrl, "version", m.m_bstrVersion,
                "symbolStatus", (m.m_dwModuleFlags & enum_MODULE_FLAGS.MODULE_FLAG_SYMBOLS) != 0 ? "Symbols loaded." : "Symbols not loaded.",
                "isOptimized", (m.m_dwModuleFlags & enum_MODULE_FLAGS.MODULE_FLAG_OPTIMIZED) != 0);
            lock (modules)
            {
                if (load != 0) modules[key] = entry;
                else modules.Remove(key);
            }
            Send("module", Json.Make("reason", load != 0 ? "new" : "removed", "module", entry));
        }

        void OnException(string type, string name, int code, string description, ref dbgExceptionAction action)
        {
            lastException = Json.Make("exceptionId", string.IsNullOrEmpty(name) ? type : name, "description", description ?? "");
        }

        // Debug engine events: where the program stopped, output, exit code, breakpoint binding, and the threads,
        // processes and modules that start and end.
        public int Event(IDebugEngine2 engine, IDebugProcess2 process, IDebugProgram2 program, IDebugThread2 thread,
            IDebugEvent2 debugEvent, ref Guid riidEvent, uint attributes)
        {
            try
            {
                var events = session;
                if ((attributes & (uint)enum_EVENTATTRIBUTES.EVENT_STOPPING) != 0 && program != null && thread != null)
                {
                    stopProgram = program;
                    stopThread = thread;
                }
                switch (debugEvent)
                {
                    case IDebugModuleLoadEvent2 loaded when events != null:
                        Module(loaded);
                        break;
                    case IDebugThreadCreateEvent2 _ when events != null && thread != null:
                        if (thread.GetThreadId(out var started) == VSConstants.S_OK) Send("thread", Json.Make("reason", "started", "threadId", (long)started));
                        break;
                    case IDebugThreadDestroyEvent2 _ when events != null && thread != null:
                        if (thread.GetThreadId(out var ended) == VSConstants.S_OK) Send("thread", Json.Make("reason", "exited", "threadId", (long)ended));
                        break;
                    case IDebugProcessCreateEvent2 _ when events != null && process != null:
                    {
                        process.GetName(enum_GETNAME_TYPE.GN_BASENAME, out var name);
                        var id = new AD_PROCESS_ID[1];
                        var body = Json.Make("name", name ?? "");
                        if (process.GetPhysicalProcessId(id) == VSConstants.S_OK) body["systemProcessId"] = (long)id[0].dwProcessId;
                        Send("process", body);
                        break;
                    }
                    case IDebugOutputStringEvent2 output when events != null:
                        if (output.GetString(out var text) == VSConstants.S_OK && !string.IsNullOrEmpty(text))
                        {
                            Send("output", Json.Make("category", "stdout", "output", text));
                            lock (engineOutput) foreach (var line in text.Split('\n')) engineOutput.Add(line.TrimEnd('\r'));
                        }
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
