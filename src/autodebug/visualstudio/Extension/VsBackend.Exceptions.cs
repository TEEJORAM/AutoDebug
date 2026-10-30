// Part of VsBackend (VsBackend.cs): exception settings and data breakpoints, put back after the session.

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
                    // Bound, as for other breakpoints (Binding): Visual Studio lists a bound breakpoint's locations as its children.
                    var bound = added.Children != null && added.Children.Count > 0;
                    answers.Add(bound
                        ? Json.Make("id", (long)dataBreakpoints.Count, "verified", true)
                        : Json.Make("id", (long)dataBreakpoints.Count, "verified", false, "message", "Visual Studio has not bound this data breakpoint"));
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
    }
}
