// A console program debugged in Visual Studio prints to its own console window, which the debugger
// does not report as output. This reads that window's text for the agent, from a small Windows
// PowerShell helper process (ConsoleReader.ps1) that attaches to the program's console: Visual Studio
// itself never attaches to a console, so closing the program's window can never close Visual Studio.

using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;

namespace AutoDebug.VisualStudio
{
    sealed class ConsoleReader : IDisposable
    {
        // The helper script ships beside this assembly in the extension (ConsoleReader.ps1): a readable file, not an
        // encoded command, so security tools and developers can see what it does.
        static string ScriptFile => Path.Combine(Path.GetDirectoryName(typeof(ConsoleReader).Assembly.Location) ?? "", "ConsoleReader.ps1");

        readonly Process helper;

        ConsoleReader(Process helper) { this.helper = helper; }

        /// <summary>Start reading the console of process <paramref name="processId"/>; every finished line goes to
        /// <paramref name="line"/>. Null when the helper cannot start (then there is simply no output).</summary>
        public static ConsoleReader Start(uint processId, Action<string> line, Action<string> log)
        {
            try
            {
                if (!File.Exists(ScriptFile))
                {
                    log($"cannot read the program's console: {ScriptFile} is missing");
                    return null;
                }
                var shell = Path.Combine(System.Environment.SystemDirectory, "WindowsPowerShell", "v1.0", "powershell.exe");
                var arguments = $"-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{ScriptFile}\" -ProcessId {processId.ToString(CultureInfo.InvariantCulture)}";
                var start = new ProcessStartInfo(shell, arguments)
                {
                    UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true,
                    RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8,
                };
                var helper = Process.Start(start);
                if (helper == null) return null;
                helper.OutputDataReceived += (_, e) => { if (e.Data != null) line(e.Data); };
                helper.ErrorDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) log($"console reader: {e.Data}"); };
                helper.BeginOutputReadLine();
                helper.BeginErrorReadLine();
                return new ConsoleReader(helper);
            }
            catch (Exception error) when (error is System.ComponentModel.Win32Exception || error is InvalidOperationException
                                          || error is IOException)
            {
                log($"cannot read the program's console: {error.Message}");
                return null;
            }
        }

        /// <summary>Wait briefly for the last lines after the program exited, then stop.</summary>
        public void Finish(int waitMs)
        {
            try
            {
                if (!helper.WaitForExit(waitMs)) helper.Kill();
                else helper.WaitForExit(); // the last lines are delivered
            }
            catch (InvalidOperationException) { /* already gone */ }
            catch (System.ComponentModel.Win32Exception) { /* already gone */ }
        }

        public void Dispose()
        {
            Finish(0);
            helper.Dispose();
        }
    }
}
