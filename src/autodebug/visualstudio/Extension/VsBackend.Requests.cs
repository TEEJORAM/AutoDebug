// Part of VsBackend (VsBackend.cs): Debug Adapter Protocol requests, answered from Visual Studio.

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
    }
}
