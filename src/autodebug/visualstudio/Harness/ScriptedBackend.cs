// A stand-in for Visual Studio, for tests: a scripted run of cpp/geometry.cpp's loop
// for a moved unit square. Environment flags (set by the tests) change its behaviour,
// as in tests/fake_adapter.py.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace AutoDebug.Harness
{
    sealed class ScriptedBackend : IBackend
    {
        static readonly (int Line, string[] Vars)[] Trace =
        {
            (13, new[] { "points", "{ size=4 }", "total", "0" }),
            (16, new[] { "i", "0", "total", "0", "password", "\"hunter2\"" }),
            (13, new[] { "i", "0", "total", "-1" }),
            (16, new[] { "i", "1", "total", "-1" }),
            (13, new[] { "i", "1", "total", "2" }),
            (16, new[] { "i", "2", "total", "2" }),
            (18, new[] { "i", "2", "total", "4" }),
        };

        static readonly Dictionary<long, object[]> Children = new Dictionary<long, object[]>
        {
            [20] = new object[] { Var("[0]", "(2, 1)", "Point"), Var("[2]", "(3, 2)", "Point") },
            [21] = new object[] { Var("api_token", "\"secret-token-value\"", "std::string") },
            [23] = new object[] { Var("note", "\"visible-child\"", "std::string") },
            [30] = new object[] { Var("verts", "{ size=3 }", "std::vector<Vert>", 31) },
            [31] = new object[] { Var("[2]", "{co=...}", "Vert", 32), Var("[0]", "{co=...}", "Vert") },
            [32] = new object[] { Var("co", "(1, 2, 3)", "Vector") },
        };

        sealed class Mark { public string File, Function, Condition, Hit, Log; public int Line, Column, Hits; }

        readonly string workspace;
        readonly object sync = new object();
        readonly List<Mark> marks = new List<Mark>();
        readonly List<Mark> editor = new List<Mark>();
        readonly Queue<Action<bool, string>> dialogs = new Queue<Action<bool, string>>();
        IBackendEvents events;
        int pos = -1;
        bool done, exceptionSent, late;
        readonly List<string> watched = new List<string>();
        volatile bool buildCancelled;

        public ScriptedBackend(string workspace)
        {
            this.workspace = workspace;
            late = Flag("HARNESS_LATE_BP") == "1";
            foreach (var spec in (Flag("HARNESS_EDITOR_BP") ?? "").Split(',').Where(s => s.Contains(':')))
            {
                var parts = spec.Split(':');
                editor.Add(new Mark { File = Path.GetFullPath(Path.Combine(workspace, parts[0])), Line = int.Parse(parts[1]) });
            }
        }

        static string Flag(string name) => Environment.GetEnvironmentVariable(name);

        static Dictionary<string, object> Var(string name, string value, string type, long reference = 0) =>
            Json.Make("name", name, "value", value, "type", type, "variablesReference", reference);

        public static void Say(string line)
        {
            lock (Console.Out) { Console.Out.WriteLine(line); Console.Out.Flush(); }
        }

        string Source => Path.GetFullPath(Path.Combine(workspace, "cpp", "geometry.cpp"));

        // -- IBackend: the IDE --------------------------------------------------------------

        public string Ide => "visualstudio";
        public string IdeVersion => "17.14-harness";
        public string Platform => "win32";
        public IList<string> Folders() => new List<string> { workspace };
        public IList<string> DebuggerTypes() => new List<string> { "visualstudio" };
        public void Log(string line) => Say("LOG " + line);
        public void Notify(string text) => Say("INFO " + text);

        public string ShowDebugWindows() => "Locals";

        // A 1x1 PNG stands in for the picture of Visual Studio's window.
        static readonly byte[] Pixel = Convert.FromBase64String(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==");

        public Dictionary<string, object> Screenshot(string file)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(file));
            File.WriteAllBytes(file, Pixel);
            Say("SCREENSHOT " + file);
            return Json.Make("file", file, "width", 1L, "height", 1L, "variables_window", ShowDebugWindows());
        }

        public Dictionary<string, object> Workspace(string folder) => Json.Make(
            "folder", workspace,
            "launch", new List<object>
            {
                Json.Make("name", "geometry (Debug|x64)", "type", "visualstudio", "request", "launch",
                    "program", Path.Combine(workspace, "build", "Debug", "geometry.exe"), "args", new List<object>(), "cwd", workspace,
                    "env", Json.Make(), "project", "geometry", "configuration", "Debug|x64", "engine", "native"),
                Json.Make("name", "Attach to a process (native)", "type", "visualstudio", "request", "attach",
                    "processId", "${command:pickProcess}", "engine", "native"),
            },
            "tasks", new List<object>
            {
                Json.Make("label", "Build geometry (Debug|x64)", "command", "build project geometry (Debug|x64)"),
                Json.Make("label", "Build solution (Debug|x64)", "command", "build the solution (Debug|x64)"),
            });

        public Action Ask(string title, string detail, Action<bool, string> answer)
        {
            lock (dialogs) dialogs.Enqueue(answer);
            Say("DIALOG " + Json.Write(Json.Make("message", title, "detail", detail, "modal", true, "items", new List<object> { "Approve" })));
            return () =>
            {
                lock (dialogs) if (dialogs.Count > 0 && dialogs.Peek() == answer) dialogs.Dequeue();
                Say("DIALOG_CLOSED");
            };
        }

        public void Answer(bool approved)
        {
            Action<bool, string> answer = null;
            lock (dialogs) if (dialogs.Count > 0) answer = dialogs.Dequeue();
            answer?.Invoke(approved, approved ? null : "the developer did not approve");
        }

        public BuildResult Build(string label, int timeoutMs)
        {
            buildCancelled = false;
            if (Flag("HARNESS_BUILD_HANG") == "1")
            {
                var deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
                while (DateTime.UtcNow < deadline && !buildCancelled) Thread.Sleep(10);
                CancelBuild();
                return new BuildResult { Status = buildCancelled ? "timeout" : "failed" };
            }
            Thread.Sleep(20);
            var code = int.TryParse(Flag("HARNESS_BUILD_EXIT"), out var exit) ? exit : 0;
            return new BuildResult { Status = code == 0 ? "succeeded" : "failed", ExitCode = code };
        }

        public void CancelBuild()
        {
            buildCancelled = true;
            Say("LOG build terminated");
        }

        public object AddBreakpoint(string file, int line, BreakpointOptions options)
        {
            var mark = new Mark { File = file, Line = line, Column = options.Column, Condition = options.Condition, Hit = options.HitCondition, Log = options.LogMessage };
            lock (sync) marks.Add(mark);
            if (options.Column > 0 || options.HitCondition != null || options.LogMessage != null)
                Say($"PLACED {Path.GetFileName(file)}:{line} column={options.Column} hit={options.HitCondition} log={options.LogMessage}");
            return mark;
        }

        public object AddFunctionBreakpoint(string name)
        {
            var mark = new Mark { Function = name };
            lock (sync) marks.Add(mark);
            return mark;
        }

        public void RemoveBreakpoint(object handle)
        {
            lock (sync) marks.Remove((Mark)handle);
        }

        public int Count
        {
            get { lock (sync) return marks.Count + editor.Count; }
        }

        public Binding Binding(object handle)
        {
            var mark = (Mark)handle;
            if (mark.Function != null) return new Binding { Verified = false, Message = "not supported by the scripted program" };
            var message = Flag("HARNESS_BP_MESSAGE");
            if (!string.IsNullOrEmpty(message)) return new Binding { Verified = false, Message = message };
            return new Binding { Verified = events != null && !late, Line = mark.Line };
        }

        public IList<Dictionary<string, object>> EditorBreakpoints(ICollection<object> own) =>
            editor.Select(m => Json.Make("file", m.File, "line", (long)m.Line)).ToList();

        public Dictionary<string, object> Capabilities() => Json.Make(
            "supportsExceptionInfoRequest", true, "supportsHitConditionalBreakpoints", true, "supportsLogPoints", true,
            "supportsDataBreakpoints", true, "supportsValueFormattingOptions", true, "supportsModulesRequest", true,
            "supportsSingleThreadExecutionRequests", true, "supportsSteppingGranularity", true, "supportsDisassembleRequest", true,
            "supportsReadMemoryRequest", true, "supportsExceptionOptions", true,
            "exceptionBreakpointFilters", new List<object>
            {
                Json.Make("filter", "cpp", "label", "C++ exceptions when thrown", "default", false),
                Json.Make("filter", "win32", "label", "Win32 exceptions when thrown", "default", false),
            });

        public bool Launch(Dictionary<string, object> configuration, IBackendEvents sink)
        {
            events = sink;
            Later(() =>
            {
                if (late)
                {
                    late = false;
                    events.BindingChanged();
                }
                Event("process", Json.Make("name", "geometry.exe", "systemProcessId", 5150L));
                Event("module", Json.Make("reason", "new", "module", Json.Make("id", "geometry.exe", "name", "geometry.exe",
                    "path", Path.Combine(workspace, "build", "Debug", "geometry.exe"), "symbolStatus", "Symbols loaded.")));
                Event("thread", Json.Make("reason", "started", "threadId", 2L));
                for (var n = 0; n < (int.TryParse(Flag("HARNESS_FLOOD"), out var flood) ? flood : 0); n++)
                    Event("output", Json.Make("category", "stdout", "output", $"loading part {n}\n"));
                Run();
            }, late ? 20 : 5);
            return true;
        }

        // -- the scripted program ----------------------------------------------------------------

        void Later(Action action, int ms = 5) => Task.Run(async () => { await Task.Delay(ms); action(); });

        void Event(string name, Dictionary<string, object> body) =>
            events.Debugger(Json.Make("type", "event", "event", name, "body", body));

        // Whether a breakpoint stops the program here, as Visual Studio counts hits; a tracepoint only prints.
        bool Stops(int line)
        {
            List<Mark> here;
            lock (sync)
                here = marks.Concat(editor).Where(m => m.File != null && m.Line == line
                    && string.Equals(m.File, Source, StringComparison.OrdinalIgnoreCase)).ToList();
            var stop = false;
            foreach (var mark in here)
            {
                mark.Hits++;
                if (mark.Hit != null)
                {
                    var count = int.Parse(new string(mark.Hit.Where(char.IsDigit).ToArray()));
                    var at = mark.Hit.TrimStart().StartsWith(">=") ? mark.Hits >= count : mark.Hit.TrimStart().StartsWith("%") ? mark.Hits % count == 0 : mark.Hits == count;
                    if (!at) continue;
                }
                if (mark.Log != null)
                {
                    var values = Vars();
                    var text = System.Text.RegularExpressions.Regex.Replace(mark.Log, @"\{([^{}]*)\}", m => values.TryGetValue(m.Groups[1].Value.Trim(), out var v) ? v : m.Value);
                    Event("output", Json.Make("category", "console", "output", text + "\n"));
                    continue;
                }
                stop = true;
            }
            return stop;
        }

        Dictionary<string, string> Vars()
        {
            var values = new Dictionary<string, string>();
            for (var i = 0; i + 1 < Here.Vars.Length; i += 2) values[Here.Vars[i]] = Here.Vars[i + 1];
            return values;
        }

        string ChangedWatch()
        {
            if (pos <= 0 || watched.Count == 0) return null;
            string Value(int at, string name)
            {
                var vars = Trace[at].Vars;
                for (var i = 0; i + 1 < vars.Length; i += 2) if (vars[i] == name) return vars[i + 1];
                return null;
            }
            return watched.FirstOrDefault(n => Value(pos, n) != null && Value(pos, n) != Value(pos - 1, n));
        }

        void Run()
        {
            for (pos++; pos < Trace.Length; pos++)
            {
                var changed = ChangedWatch();
                if (changed != null)
                {
                    Event("stopped", Json.Make("reason", "data breakpoint", "description", $"{changed} changed", "threadId", 1L));
                    return;
                }
                if (!Stops(Trace[pos].Line)) continue;
                var exception = Flag("HARNESS_EXCEPTION") == "1" && !exceptionSent;
                exceptionSent = true;
                Event("stopped", Json.Make("reason", exception ? "exception" : "breakpoint", "threadId", 1L));
                return;
            }
            Finish();
        }

        void Finish()
        {
            if (done) return;
            done = true;
            Event("output", Json.Make("category", "stderr", "output", "geometry: 1 of 3 shapes change area when moved\n"));
            Event("exited", Json.Make("exitCode", 1L));
            Event("terminated", Json.Make());
            events.Ended("the program exited", 1);
        }

        (int Line, string[] Vars) Here => pos >= 0 && pos < Trace.Length ? Trace[pos] : Trace[Trace.Length - 1];

        public Dictionary<string, object> Request(string command, Dictionary<string, object> arguments)
        {
            switch (command)
            {
                case "threads":
                    return Json.Make("threads", new List<object> { Json.Make("id", 1L, "name", "main"), Json.Make("id", 2L, "name", "worker") });
                case "stackTrace":
                    if (Flag("HARNESS_STACK_THROW") == "1") throw new InvalidOperationException("stack trace failed");
                    var frames = new List<object>
                    {
                        Json.Make("id", 1L, "name", "polygon_area", "source", Json.Make("path", Source), "line", (long)Here.Line,
                            "instructionPointerReference", "0x00007FF6A1B21010"),
                        Json.Make("id", 2L, "name", "main", "source", Json.Make("path", Source), "line", 37L),
                    };
                    var levels = (int)(Json.Long(arguments, "levels") ?? 20);
                    return Json.Make("stackFrames", frames.Take(levels).ToList(), "totalFrames", 2L);
                case "scopes":
                    return Json.Make("scopes", new List<object> {
                        Json.Make("name", "Locals", "variablesReference", Json.Long(arguments, "frameId") == 1 ? 7L : 8L, "expensive", false),
                        Json.Make("name", "Registers", "variablesReference", 50L, "expensive", true) });
                case "variables":
                    var reference = Json.Long(arguments, "variablesReference") ?? 0;
                    var hex = Json.Get(Json.Obj(Json.Get(arguments, "format")), "hex") is bool h && h;
                    if (reference == 50)
                        return Json.Make("variables", new List<object> { Var("RIP", "00007FF6A1B21010", "register"), Var("RSP", "000000E3B42FF8A0", "register") });
                    if (reference == 40)
                    {
                        var first = (int)(Json.Long(arguments, "start") ?? 0);
                        var take = (int)(Json.Long(arguments, "count") ?? 200);
                        return Json.Make("variables", Enumerable.Range(first, Math.Max(0, Math.Min(take, 1000 - first)))
                            .Select(i => (object)Var($"[{i}]", hex ? $"0x{i * 3:x8}" : (i * 3).ToString(), "int")).ToList());
                    }
                    if (Children.TryGetValue(reference, out var children)) return Json.Make("variables", children.ToList());
                    if (reference != 7) return Json.Make("variables", new List<object> { Var("shapes", "{ size=3 }", "std::pair[3]") });
                    var locals = new List<object>();
                    for (var i = 0; i + 1 < Here.Vars.Length; i += 2)
                    {
                        var shown = hex && int.TryParse(Here.Vars[i + 1], out var number) ? $"0x{number:x8}" : Here.Vars[i + 1];
                        var local = Var(Here.Vars[i], shown, "double");
                        if (Here.Vars[i] == "total") local["memoryReference"] = "0x000000E3B42FF900";
                        locals.Add(local);
                    }
                    var big = Var("big", "{ size=1000 }", "std::vector<int>", 40);
                    big["indexedVariables"] = 1000L;
                    locals.Add(big);
                    locals.Add(Var("points", "{ size=4 }", "const std::vector<Point>&", 20));
                    locals.Add(Var("settings", "{...}", "Settings", 21));
                    locals.Add(Var("credentials", "{...}", "Credentials", 23));
                    locals.Add(Var("mesh", "{...}", "Mesh", 30));
                    return Json.Make("variables", locals);
                case "next": case "stepIn": case "stepOut":
                    if (Flag("HARNESS_STEP_FAIL") == "1") throw new InvalidOperationException("the debugger rejected the step");
                    if (arguments.Count > 1) Say("STEP " + Json.Write(arguments));
                    Later(() =>
                    {
                        pos++;
                        if (pos >= Trace.Length) Finish(); else Event("stopped", Json.Make("reason", "step", "threadId", 1L));
                    });
                    return Json.Make();
                case "continue":
                    if (arguments.Count > 1) Say("CONTINUE " + Json.Write(arguments));
                    Later(Run);
                    return Json.Make("allThreadsContinued", true);
                case "pause":
                    Later(() => Event("stopped", Json.Make("reason", "pause", "threadId", 1L)));
                    return Json.Make();
                case "exceptionInfo":
                    return Json.Make("exceptionId", "std::out_of_range", "description", "vector subscript out of range");
                case "setExceptionBreakpoints":
                    if (Json.Get(arguments, "exceptionOptions") != null || Json.List(Json.Get(arguments, "filters")).Count > 0)
                        Say("EXCEPTIONS " + Json.Write(arguments));
                    return Json.Make();
                case "dataBreakpointInfo":
                    var name = Json.Str(arguments, "name");
                    return Json.Long(arguments, "variablesReference") == 7 && name == "total"
                        ? Json.Make("dataId", "total", "description", "total", "accessTypes", new List<object> { "write" })
                        : Json.Make("dataId", null, "description", $"{name} has no plain path Visual Studio can watch");
                case "setDataBreakpoints":
                    lock (sync)
                    {
                        watched.Clear();
                        watched.AddRange(Json.List(Json.Get(arguments, "breakpoints")).Select(b => Json.Str(Json.Obj(b), "dataId")));
                        return Json.Make("breakpoints", watched.Select((w, i) => (object)Json.Make("id", (long)i + 1, "verified", true)).ToList());
                    }
                case "modules":
                    return Json.Make("modules", new List<object> {
                        Json.Make("id", "geometry.exe", "name", "geometry.exe", "path", Path.Combine(workspace, "build", "Debug", "geometry.exe"), "symbolStatus", "Symbols loaded."),
                        Json.Make("id", "ucrtbased.dll", "name", "ucrtbased.dll", "path", @"C:\Windows\System32\ucrtbased.dll", "version", "10.0.26100", "symbolStatus", "Symbols not loaded.") });
                case "disassemble":
                    var at = Convert.ToInt64(Json.Str(arguments, "memoryReference"), 16) + 4 * (Json.Long(arguments, "instructionOffset") ?? 0);
                    return Json.Make("instructions", Enumerable.Range(0, (int)(Json.Long(arguments, "instructionCount") ?? 1))
                        .Select(i => (object)Json.Make("address", $"0x{at + 4 * i:X16}", "instruction", "movsd xmm0,mmword ptr [rbp+8]")).ToList());
                case "readMemory":
                    var bytes = Enumerable.Range(0, (int)(Json.Long(arguments, "count") ?? 8)).Select(i => (byte)(0xA0 + i)).ToArray();
                    return Json.Make("address", Json.Str(arguments, "memoryReference"), "data", Convert.ToBase64String(bytes));
                default:
                    throw new InvalidOperationException($"the scripted program has no {command}");
            }
        }

        public void Stop(bool detach)
        {
            Say("DISCONNECT " + Json.Write(Json.Make("detach", detach)));
            if (events == null || done) return;
            done = true;
            Event("terminated", Json.Make());
            events.Ended(detach ? "the debugger detached" : "the debug session ended", null);
            Say("LOG stopped");
        }
    }
}
