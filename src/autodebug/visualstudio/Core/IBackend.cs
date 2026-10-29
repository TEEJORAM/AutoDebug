// What the relay needs from the IDE. Visual Studio implements it in
// Extension/VsBackend.cs; the test harness implements it with a scripted program.
// Everything about approval, limits and the protocol is in Gate and RelayServer.

using System;
using System.Collections.Generic;

namespace AutoDebug
{
    /// <summary>Reports from the IDE while a session runs. Messages are shaped like the
    /// Debug Adapter Protocol, because that is what the AutoDebug server understands.</summary>
    public interface IBackendEvents
    {
        /// <summary>An event from the debugger, e.g. {"type":"event","event":"stopped","body":{...}}.</summary>
        void Debugger(Dictionary<string, object> message);

        /// <summary>Breakpoint binding may have changed; the gate asks <see cref="IBackend.Binding"/> again.</summary>
        void BindingChanged();

        /// <summary>The debug session is over (the program exited, or the developer stopped it).</summary>
        void Ended(string reason, long? exitCode);
    }

    public sealed class BuildResult
    {
        public string Status;   // succeeded, failed, timeout, unavailable
        public long? ExitCode;
    }

    /// <summary>What a source breakpoint does besides stopping: where on the line, when, and whether it only logs.</summary>
    public sealed class BreakpointOptions
    {
        public int Column;          // 0: the start of the line
        public string Condition;    // null: always
        public string HitCondition; // a count: "5", ">=5", "%10"; null: every hit
        public string LogMessage;   // a log point (tracepoint): print this instead of stopping; null: stop
    }

    public sealed class Binding
    {
        public bool Verified;
        public long? Line;
        public string Message;
    }

    public interface IBackend
    {
        string Ide { get; }
        string IdeVersion { get; }
        string Platform { get; }
        IList<string> Folders();
        IList<string> DebuggerTypes();
        void Log(string line);

        /// <summary>{folder, launch: [configurations], tasks: [{label, command}]} for one open folder.</summary>
        Dictionary<string, object> Workspace(string folder);

        /// <summary>Show the modal Approve dialog in front of other windows; call <paramref name="answer"/> once
        /// with the developer's choice. Returns an action that closes the dialog unanswered (no answer in time).</summary>
        Action Ask(string title, string detail, Action<bool, string> answer);

        /// <summary>Run a build task; blocks until it ends or <paramref name="timeoutMs"/> passes (then cancels it).</summary>
        BuildResult Build(string label, int timeoutMs);

        void CancelBuild();

        object AddBreakpoint(string file, int line, BreakpointOptions options);
        object AddFunctionBreakpoint(string name);
        void RemoveBreakpoint(object handle);
        Binding Binding(object handle);

        /// <summary>The developer's own enabled breakpoints, excluding <paramref name="own"/>: {file, line} or {function}.</summary>
        IList<Dictionary<string, object>> EditorBreakpoints(ICollection<object> own);

        /// <summary>Debugger capabilities, as a Debug Adapter Protocol initialize response body.</summary>
        Dictionary<string, object> Capabilities();

        /// <summary>Start (or attach to) exactly <paramref name="configuration"/>; false if the debugger did not start.</summary>
        bool Launch(Dictionary<string, object> configuration, IBackendEvents events);

        /// <summary>One allowed debugger request (threads, stackTrace, scopes, variables, next, ...): its response body.</summary>
        Dictionary<string, object> Request(string command, Dictionary<string, object> arguments);

        /// <summary>End the session: detach (attach sessions) or stop the program.</summary>
        void Stop(bool detach);

        /// <summary>A non-modal note to the developer. Never an approval.</summary>
        void Notify(string text);

        /// <summary>At a stop: bring the variables window that has values (Locals, or Autos when the frame has no
        /// locals) and the Call Stack forward, with the code in front. Returns the variables window's name.</summary>
        string ShowDebugWindows();

        /// <summary>Save a PNG picture of the IDE window (after <see cref="ShowDebugWindows"/>) to
        /// <paramref name="file"/>: {file, width, height, variables_window}.</summary>
        Dictionary<string, object> Screenshot(string file);
    }
}
