// Part of VsBackend (VsBackend.cs): the debug engine's view of a stop: registers, machine code, memory.

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
    }
}
