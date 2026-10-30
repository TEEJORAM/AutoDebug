// Part of VsBackend (VsBackend.cs): Visual Studio's events as debugger events, the debug windows and screenshots.

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
    sealed partial class VsBackend
    {
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
            _ = Task.Run(() => events?.BindingChanged());
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
                        if (events != null) _ = Task.Run(() => events.BindingChanged());
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
