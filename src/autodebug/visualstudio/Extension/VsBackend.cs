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
    sealed partial class VsBackend : IBackend, IDebugEventCallback2, IDisposable
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
    }
}
