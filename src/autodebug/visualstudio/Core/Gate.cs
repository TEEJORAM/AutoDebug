// The relay's operations (docs/design.md, "Extension protocol", protocol 4): the same
// contract as the VS Code / Cursor relay. Nothing runs before the developer clicks
// Approve, and only what the dialog showed. Limits, approved folders and the list of
// allowed debugger requests are enforced here, whatever the server asks.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace AutoDebug
{
    public sealed class RelayException : Exception
    {
        public string Code { get; }
        public RelayException(string code, string message) : base(message) { Code = code; }
    }

    public sealed class Gate : IBackendEvents
    {
        public const int Protocol = 4;
        public const int MaxEvents = 5000;
        public const int MaxConfig = 4000;
        public const int ApprovalSeconds = 120;
        static readonly HashSet<string> Allowed = new HashSet<string> {
            "threads", "stackTrace", "scopes", "variables", "next", "stepIn", "stepOut", "continue", "pause",
            "exceptionInfo", "setExceptionBreakpoints" };
        static readonly HashSet<string> Steps = new HashSet<string> { "next", "stepIn", "stepOut" };
        static readonly string[] Open = { "awaiting_approval", "building", "starting", "debugging" };

        readonly IBackend backend;
        readonly object sync = new object();
        readonly List<Dictionary<string, object>> queue = new List<Dictionary<string, object>>();
        long seq;
        long droppedOutput;
        long requestSeq = 1000000;
        int sessions;
        Session session;
        public int BuildMinuteMs { get; set; } = 60000;
        /// <summary>How long the Approve dialog waits for an answer (tests shorten it).</summary>
        public int ApprovalMs { get; set; } = ApprovalSeconds * 1000;

        sealed class Mark
        {
            public string Id, File, Function, Condition;
            public int Line;
            public object Handle;
            public long DapId;
        }

        sealed class Session
        {
            public int Id;
            public string Phase, Folder, Shown, Task, Label;
            public Dictionary<string, object> Launch;
            public List<string> Roots, Notes;
            public List<Mark> Marks = new List<Mark>();
            public int NextId = 1, StepsUsed, MaxSteps, Minutes, BuildMinutes;
            public bool Screenshots;
            public Timer TimeLimit;
            public bool Attach => Json.Str(Launch, "request") == "attach";
        }

        public Gate(IBackend backend) { this.backend = backend; }

        static RelayException Fail(string code, string message) => new RelayException(code, message);

        static int Clamp(object value, int low, int fallback, int high)
        {
            var number = value is long l ? (int)Math.Min(l, int.MaxValue) : value is double d ? (int)d : 0;
            return Math.Max(low, Math.Min(number == 0 ? fallback : number, high));
        }

        public object Handle(string op, Dictionary<string, object> args)
        {
            switch (op)
            {
                case "info":
                    return Json.Make("ide", backend.Ide, "ide_version", backend.IdeVersion, "version", RelayServer.Version,
                        "folders", backend.Folders().Cast<object>().ToList(), "platform", backend.Platform,
                        "debugger_types", backend.DebuggerTypes().Cast<object>().ToList());
                case "workspace": return backend.Workspace(Folder(Json.Str(args, "folder")));
                case "approve": return Approve(args);
                case "events": return Events(args);
                case "dap": return Request(args);
                case "breakpoints": return Breakpoints(args);
                case "editor_breakpoints":
                    List<object> own;
                    lock (sync) own = session == null ? new List<object>() : session.Marks.Select(m => m.Handle).Where(h => h != null).ToList();
                    return Json.Make("breakpoints", backend.EditorBreakpoints(own).Cast<object>().ToList());
                case "notify": return Notify(args);
                case "screenshot": return Screenshot(args);
                case "stop": End(Json.Str(args, "reason") ?? "stopped by the agent"); return Json.Make();
                default: throw Fail("BAD_REQUEST", $"unknown operation {op}");
            }
        }

        string Folder(string wanted)
        {
            var all = backend.Folders();
            if (string.IsNullOrEmpty(wanted))
            {
                if (all.Count == 1) return all[0];
                throw Fail(all.Count == 0 ? "NOT_FOUND" : "BAD_REQUEST",
                    all.Count == 0 ? "no solution is open in Visual Studio" : "this window has several folders; name one");
            }
            var found = all.FirstOrDefault(f => Same(f, wanted));
            if (found == null) throw Fail("NOT_FOUND", $"{wanted} is not open in this window");
            return found;
        }

        static string Norm(string path) => Path.GetFullPath(path).TrimEnd('\\', '/');

        static bool Same(string a, string b) => string.Equals(Norm(a), Norm(b), StringComparison.OrdinalIgnoreCase);

        static bool Within(string root, string full)
        {
            var r = Norm(root);
            var f = Norm(full);
            return string.Equals(r, f, StringComparison.OrdinalIgnoreCase)
                || f.StartsWith(r + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                || f.StartsWith(r + "/", StringComparison.OrdinalIgnoreCase);
        }

        // -- events ---------------------------------------------------------------------

        void Emit(Dictionary<string, object> evt)
        {
            lock (sync)
            {
                evt["seq"] = ++seq;
                queue.Add(evt);
                if (queue.Count > MaxEvents)
                {
                    // Program output goes first, so a flood of it never pushes out a stop or the end.
                    var output = queue.FindIndex(IsOutput);
                    if (output >= 0) { queue.RemoveAt(output); droppedOutput++; } else queue.RemoveAt(0);
                }
                Monitor.PulseAll(sync);
            }
        }

        static bool IsOutput(Dictionary<string, object> e) =>
            Json.Str(e, "kind") == "dap" && Json.Str(Json.Obj(Json.Get(e, "message")), "event") == "output";

        object Events(Dictionary<string, object> args)
        {
            var since = Json.Long(args, "since") ?? 0;
            var ms = Clamp(Json.Get(args, "wait_ms"), 0, 0, 60000);
            lock (sync)
            {
                var deadline = DateTime.UtcNow.AddMilliseconds(ms);
                while (seq <= since && ms > 0)
                {
                    var left = deadline - DateTime.UtcNow;
                    if (left <= TimeSpan.Zero || !Monitor.Wait(sync, left)) break;
                }
                var events = queue.Where(e => (long)e["seq"] > since).Take(500).Cast<object>().ToList();
                var next = events.Count > 0 ? (long)((Dictionary<string, object>)events[events.Count - 1])["seq"] : Math.Min(since, seq);
                var dropped = queue.Count > 0 && (long)queue[0]["seq"] > since + 1 && since < seq && !(IsOutput(queue[0]) && droppedOutput > 0);
                return Json.Make("events", events, "next", next, "latest", seq, "dropped", dropped, "dropped_output", droppedOutput);
            }
        }

        // -- approve: the only way anything runs ------------------------------------------------

        object Approve(Dictionary<string, object> args)
        {
            // The IDE is never called while the lock is held: its events need the lock too.
            var folder = Folder(Json.Str(args, "folder"));
            var tasks = Json.List(Json.Get(backend.Workspace(folder), "tasks")).Select(Json.Obj).ToList();
            Session s;
            Dictionary<string, object> ids;
            lock (sync)
            {
                if (session != null && Open.Contains(session.Phase)) throw Fail("BUSY", "a debug session is already active in this window; stop it first");
                var launch = Json.Get(args, "launch") as Dictionary<string, object>;
                if (launch == null || Json.Str(launch, "name") == null || Json.Str(launch, "type") == null) throw Fail("BAD_REQUEST", "a launch configuration is needed");
                var request = Json.Str(launch, "request");
                if (request != "launch" && request != "attach") throw Fail("BAD_REQUEST", "request must be launch or attach");
                var shown = new Dictionary<string, object>(launch);
                shown.Remove("name");
                var json = Json.Write(shown, indent: true);
                if (json.Length > MaxConfig) throw Fail("BAD_REQUEST", $"the launch configuration is longer than {MaxConfig} characters");
                var task = Json.Str(args, "task");
                if (task != null && !tasks.Any(t => Json.Str(t, "label") == task)) throw Fail("NOT_FOUND", $"no build task labelled \"{task}\"");
                var roots = new List<string> { folder };
                foreach (var extra in Json.List(Json.Get(args, "source_folders")))
                {
                    if (!(extra is string text) || !Path.IsPathRooted(text)) throw Fail("BAD_REQUEST", "source_folders must be absolute paths");
                    roots.Add(Norm(text));
                }
                s = new Session
                {
                    Id = ++sessions, Phase = "awaiting_approval", Folder = folder, Launch = launch, Shown = json, Task = task, Roots = roots,
                    MaxSteps = Clamp(Json.Get(args, "max_steps"), 1, 100, 1000), Minutes = Clamp(Json.Get(args, "max_minutes"), 1, 30, 480),
                    BuildMinutes = Clamp(Json.Get(args, "build_minutes"), 1, 30, 600),
                    Notes = Json.List(Json.Get(args, "notes")).Select(n => Cut(Convert.ToString(n), 500)).ToList(),
                    Label = Cut(Json.Str(args, "label") ?? Json.Str(launch, "name"), 200),
                    Screenshots = Json.Get(args, "screenshots") is bool pictures && pictures,
                };
                ids = Register(s, Json.List(Json.Get(args, "breakpoints")), Json.List(Json.Get(args, "functions")));
                session = s;
            }
            Ask(s, tasks);
            ids["session"] = s.Id;
            return ids;
        }

        static string Cut(string text, int length) => text == null || text.Length <= length ? text : text.Substring(0, length);

        Dictionary<string, object> Register(Session s, List<object> lines, List<object> functions)
        {
            var lineIds = new List<object>();
            var functionIds = new List<object>();
            foreach (var item in lines.Select(Json.Obj))
            {
                var line = Json.Long(item, "line") ?? 0;
                var file = Json.Str(item, "file");
                if (line < 1) throw Fail("BAD_REQUEST", "breakpoint lines are positive integers");
                if (file == null || !Path.IsPathRooted(file)) throw Fail("BAD_REQUEST", "breakpoint files are absolute paths");
                if (!s.Roots.Any(root => Within(root, file))) throw Fail("OUTSIDE_WORKSPACE", $"{file} is outside the approved folders");
                var mark = new Mark { Id = $"b{s.NextId++}", File = Norm(file), Line = (int)line, Condition = Cut(Json.Str(item, "condition"), 500) };
                s.Marks.Add(mark);
                lineIds.Add(mark.Id);
            }
            foreach (var name in functions)
            {
                var mark = new Mark { Id = $"f{s.NextId++}", Function = Cut(Convert.ToString(name), 300) };
                s.Marks.Add(mark);
                functionIds.Add(mark.Id);
            }
            return Json.Make("breakpoint_ids", lineIds, "function_ids", functionIds);
        }

        string Relative(Session s, string full) =>
            Within(s.Folder, full) && !Same(s.Folder, full) ? full.Substring(Norm(s.Folder).Length + 1).Replace('\\', '/') : full;

        string DialogText(Session s, List<Dictionary<string, object>> tasks)
        {
            var l = s.Launch;
            var program = string.Join(" ", new[] { Json.Str(l, "program") ?? Json.Str(l, "module") ?? "" }
                .Concat(Json.List(Json.Get(l, "args")).Select(a => Convert.ToString(a))).Where(p => !string.IsNullOrEmpty(p)));
            var task = s.Task == null ? null : tasks.First(t => Json.Str(t, "label") == s.Task);
            var lines = new List<string>(s.Notes)
            {
                $"Folder: {s.Folder}",
                task == null ? "Build: none" : $"Build first: \"{s.Task}\": {Json.Str(task, "command")}",
                $"Run: \"{Json.Str(l, "name")}\" ({Json.Str(l, "type")}) {program}".Trim(),
                "Breakpoints: " + (s.Marks.Any(m => m.File != null)
                    ? string.Join(", ", s.Marks.Where(m => m.File != null).Select(m => $"{Relative(s, m.File)}:{m.Line}{(m.Condition != null ? $" if {m.Condition}" : "")}"))
                    : "none"),
            };
            if (s.Marks.Any(m => m.Function != null)) lines.Add("Function breakpoints: " + string.Join(", ", s.Marks.Where(m => m.Function != null).Select(m => m.Function)));
            if (s.Roots.Count > 1) lines.Add("Breakpoints may also be set in: " + string.Join(", ", s.Roots.Skip(1)));
            lines.Add($"Limits: {s.MaxSteps} steps, {s.Minutes} minutes");
            lines.Add(s.Attach ? "When the session ends: the debugger detaches and the program keeps running"
                               : "When the session ends: the program is stopped");
            lines.Add("");
            lines.Add("The AI agent can then read the stack and variables, step and continue.");
            lines.Add("It cannot evaluate code or change variables. Secret-looking values are hidden from it.");
            if (s.Screenshots)
                lines.Add("Screenshots: at the stops the agent captures, a picture of this window is saved in " +
                          "autodebug-reports\\screenshots. It shows whatever the window shows, including values that look secret.");
            lines.Add("");
            lines.Add("Launch configuration, exactly as it will be used:");
            lines.Add(s.Shown);
            return string.Join("\n", lines);
        }

        void Ask(Session s, List<Dictionary<string, object>> tasks)
        {
            var answered = 0;
            void Answer(bool approved, string reason)
            {
                if (Interlocked.Exchange(ref answered, 1) == 1) return;
                lock (sync)
                {
                    if (session != s || s.Phase != "awaiting_approval") return;
                    if (!approved) s.Phase = "denied";
                }
                Emit(Json.Make("kind", "approval", "approved", approved, "reason", reason));
                if (!approved) return;
                backend.Log($"approved: {Json.Str(s.Launch, "name")}");
                Task.Run(() =>
                {
                    try { Run(s); }
                    catch (Exception error)
                    {
                        Emit(Json.Make("kind", "error", "message", error.Message));
                        End("could not start");
                    }
                });
            }
            // Nobody answered in time: refuse, then close the dialog so a late click cannot look like an answer.
            Action close = null;
            var timeout = new Timer(_ =>
            {
                Answer(false, "no answer within 2 minutes");
                try { close?.Invoke(); }
                catch (Exception error) { backend.Log($"could not close the Approve dialog: {error.Message}"); }
            }, null, Timeout.Infinite, Timeout.Infinite);
            var title = s.Attach ? $"AutoDebug: let the AI agent attach the debugger for \"{s.Label}\"?"
                                 : $"AutoDebug: let the AI agent debug \"{Json.Str(s.Launch, "name")}\"?";
            close = backend.Ask(title, DialogText(s, tasks), (approved, reason) =>
            {
                timeout.Dispose();
                Answer(approved, approved ? "the developer clicked Approve" : reason ?? "the developer did not approve");
            });
            timeout.Change(ApprovalMs, Timeout.Infinite);
        }

        void Run(Session s)
        {
            if (s.Task != null)
            {
                lock (sync) { if (session != s || s.Phase != "awaiting_approval") return; s.Phase = "building"; }
                Emit(Json.Make("kind", "build", "task", s.Task, "status", "running", "exit_code", null));
                var result = backend.Build(s.Task, s.BuildMinutes * BuildMinuteMs);
                lock (sync) { if (session != s || s.Phase != "building") return; }
                if (result.Status != "succeeded")
                {
                    lock (sync) s.Phase = "build_failed";
                    Emit(Json.Make("kind", "build", "task", s.Task, "status", result.Status, "exit_code", result.ExitCode, "minutes", s.BuildMinutes));
                    return;
                }
                Emit(Json.Make("kind", "build", "task", s.Task, "status", "succeeded", "exit_code", 0L));
            }
            lock (sync)
            {
                if (session != s || (s.Phase != "awaiting_approval" && s.Phase != "building")) return;
                s.Phase = "starting";
                s.TimeLimit = new Timer(_ => End("the session time limit was reached"), null, s.Minutes * 60000L, Timeout.Infinite);
            }
            foreach (var mark in s.Marks.ToList()) Place(mark);
            Emit(Json.Make("kind", "starting"));
            Debugger(Json.Make("type", "response", "command", "initialize", "request_seq", 0L, "success", true, "body", backend.Capabilities()));
            Report(s, s.Marks);
            var started = backend.Launch(new Dictionary<string, object>(s.Launch), this);
            lock (sync) { if (session != s || s.Phase != "starting") return; }
            if (!started)
            {
                Emit(Json.Make("kind", "not_started"));
                Finish(s, "the debugger did not start", null);
                return;
            }
            lock (sync) s.Phase = "debugging";
            Emit(Json.Make("kind", "started"));
            BindingChanged();
        }

        void Place(Mark mark)
        {
            mark.Handle = mark.File != null ? backend.AddBreakpoint(mark.File, mark.Line, mark.Condition) : backend.AddFunctionBreakpoint(mark.Function);
        }

        // Tell the server which breakpoints exist and whether they are bound, as the
        // setBreakpoints / setFunctionBreakpoints exchange a debug adapter would show.
        void Report(Session s, IEnumerable<Mark> marks)
        {
            foreach (var group in marks.Where(m => m.Handle != null).GroupBy(m => m.File ?? "\0functions"))
            {
                var all = s.Marks.Where(m => m.Handle != null && (m.File ?? "\0functions") == group.Key).ToList();
                var number = Interlocked.Increment(ref requestSeq);
                var functions = group.Key == "\0functions";
                var request = functions
                    ? Json.Make("type", "request", "seq", number, "command", "setFunctionBreakpoints", "arguments",
                        Json.Make("breakpoints", all.Select(m => (object)Json.Make("name", m.Function)).ToList()))
                    : Json.Make("type", "request", "seq", number, "command", "setBreakpoints", "arguments",
                        Json.Make("source", Json.Make("path", group.Key), "breakpoints", all.Select(m => (object)Json.Make("line", (long)m.Line)).ToList()));
                Emit(Json.Make("kind", "dap", "direction", "to_adapter", "message", request));
                var answers = all.Select(m =>
                {
                    m.DapId = m.DapId == 0 ? Interlocked.Increment(ref requestSeq) : m.DapId;
                    return (object)State(m);
                }).ToList();
                Debugger(Json.Make("type", "response", "command", functions ? "setFunctionBreakpoints" : "setBreakpoints",
                    "request_seq", number, "success", true, "body", Json.Make("breakpoints", answers)));
            }
        }

        Dictionary<string, object> State(Mark m)
        {
            Binding binding;
            try { binding = backend.Binding(m.Handle) ?? new Binding(); }
            catch (Exception) { binding = new Binding { Message = "the debugger did not report this breakpoint" }; }
            var state = Json.Make("id", m.DapId, "verified", binding.Verified, "line", binding.Line ?? (long)m.Line);
            if (!binding.Verified && binding.Message != null) state["message"] = binding.Message;
            return state;
        }

        // -- IBackendEvents ---------------------------------------------------------------------

        public void Debugger(Dictionary<string, object> message)
        {
            lock (sync) { if (session == null || session.Phase == "ended") return; }
            if (Json.Str(message, "event") == "output")
            {
                var body = Json.Obj(Json.Get(message, "body"));
                if (Json.Str(body, "output") is string text && text.Length > 4000) body["output"] = text.Substring(0, 4000) + "…";
            }
            Emit(Json.Make("kind", "dap", "direction", "from_adapter", "message", message));
        }

        readonly Dictionary<long, bool> lastBinding = new Dictionary<long, bool>();

        public void BindingChanged()
        {
            List<Mark> marks;
            lock (sync)
            {
                if (session == null || session.Phase == "ended") return;
                marks = session.Marks.Where(m => m.Handle != null && m.DapId != 0).ToList();
            }
            foreach (var mark in marks)
            {
                var state = State(mark);
                var verified = (bool)state["verified"];
                lock (sync)
                {
                    if (lastBinding.TryGetValue(mark.DapId, out var before) && before == verified) continue;
                    lastBinding[mark.DapId] = verified;
                }
                Debugger(Json.Make("type", "event", "event", "breakpoint", "body", Json.Make("reason", "changed", "breakpoint", state)));
            }
        }

        public void Ended(string reason, long? exitCode)
        {
            Session s;
            lock (sync) s = session;
            if (s != null) Finish(s, reason ?? "the debug session ended", exitCode);
        }

        void Finish(Session s, string reason, long? exitCode)
        {
            lock (sync)
            {
                if (s.Phase == "ended") return;
                s.TimeLimit?.Dispose();
                s.Phase = "ended";
            }
            foreach (var mark in s.Marks) Unplace(mark);
            Emit(Json.Make("kind", "ended", "reason", reason, "exit_code", exitCode));
        }

        void Unplace(Mark mark)
        {
            if (mark.Handle == null) return;
            try { backend.RemoveBreakpoint(mark.Handle); } catch (Exception) { /* already gone */ }
            mark.Handle = null;
        }

        // -- while the session runs -------------------------------------------------------------------

        Session Live()
        {
            var s = session;
            if (s == null || (s.Phase != "starting" && s.Phase != "debugging")) throw Fail("NOT_FOUND", "no debug session is running");
            return s;
        }

        object Request(Dictionary<string, object> args)
        {
            var command = Json.Str(args, "command") ?? "";
            if (!Allowed.Contains(command)) throw Fail("BAD_REQUEST", $"the debugger request {command} is not allowed");
            Session s;
            var step = Steps.Contains(command);
            lock (sync)
            {
                s = Live();
                if (step && s.StepsUsed >= s.MaxSteps) throw Fail("LIMIT", $"the approved limit of {s.MaxSteps} steps is used up");
                if (step) s.StepsUsed++;
            }
            var ms = Clamp(Json.Get(args, "timeout_ms"), 100, 10000, 60000);
            var call = Task.Run(() => backend.Request(command, Json.Obj(Json.Get(args, "arguments"))));
            try
            {
                if (!call.Wait(ms)) throw Fail("IDE_ERROR", $"the debugger did not answer {command} in time");
                return Json.Make("body", call.Result ?? Json.Make());
            }
            catch (Exception error)
            {
                if (step) lock (sync) s.StepsUsed--;
                var inner = error is AggregateException aggregate ? aggregate.InnerException ?? error : error;
                if (inner is RelayException relay) throw relay;
                throw Fail("IDE_ERROR", inner.Message);
            }
        }

        object Breakpoints(Dictionary<string, object> args)
        {
            Dictionary<string, object> ids;
            Session s;
            List<Mark> added, removed;
            lock (sync)
            {
                s = Live();
                var remove = new HashSet<string>(Json.List(Json.Get(args, "remove")).Select(Convert.ToString));
                removed = s.Marks.Where(m => remove.Contains(m.Id)).ToList();
                foreach (var gone in removed) s.Marks.Remove(gone);
                var before = s.Marks.Count;
                ids = Register(s, Json.List(Json.Get(args, "add")), Json.List(Json.Get(args, "add_functions")));
                added = s.Marks.Skip(before).ToList();
            }
            foreach (var gone in removed) Unplace(gone);
            foreach (var mark in added) Place(mark);
            Report(s, added);
            return ids;
        }

        // A picture of the IDE window at a stop, only when the developer approved screenshots, and only into the
        // approved folder's autodebug-reports\screenshots.
        object Screenshot(Dictionary<string, object> args)
        {
            Session s;
            lock (sync) s = Live();
            if (!s.Screenshots) throw Fail("NOT_APPROVED", "the developer did not approve screenshots for this session");
            var file = Json.Str(args, "file");
            if (file == null || !Path.IsPathRooted(file) || !file.EndsWith(".png", StringComparison.OrdinalIgnoreCase))
                throw Fail("BAD_REQUEST", "file must be an absolute .png path");
            var folder = Path.Combine(s.Folder, "autodebug-reports", "screenshots");
            if (!Within(folder, file) || Same(folder, file)) throw Fail("OUTSIDE_WORKSPACE", $"screenshots are saved only in {folder}");
            var call = Task.Run(() => backend.Screenshot(Norm(file)));
            try
            {
                if (!call.Wait(30000)) throw Fail("IDE_ERROR", "the screenshot took too long");
                return call.Result;
            }
            catch (AggregateException error)
            {
                var inner = error.InnerException ?? error;
                if (inner is RelayException relay) throw relay;
                throw Fail("IDE_ERROR", inner.Message);
            }
        }

        object Notify(Dictionary<string, object> args)
        {
            var text = Json.Str(args, "text") ?? "";
            if (text.Length == 0 || text.Length > 300) throw Fail("BAD_REQUEST", "the note is 1 to 300 characters");
            lock (sync) { if (session == null || !Open.Contains(session.Phase)) throw Fail("NOT_FOUND", "no debug session is running"); }
            backend.Log($"asked the developer: {text}");
            backend.Notify($"AutoDebug: the AI agent asks you to: {text}");
            return Json.Make();
        }

        public void End(string reason)
        {
            Session s;
            string phase;
            lock (sync)
            {
                s = session;
                if (s == null || s.Phase == "ended" || s.Phase == "denied" || s.Phase == "build_failed") return;
                phase = s.Phase;
            }
            if (phase == "building") { try { backend.CancelBuild(); } catch (Exception) { /* the build already finished */ } }
            var wasDebugging = phase == "starting" || phase == "debugging";
            Finish(s, reason, null);
            if (wasDebugging) { try { backend.Stop(s.Attach); } catch (Exception) { /* already stopped */ } }
        }
    }
}
