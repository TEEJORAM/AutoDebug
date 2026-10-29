// A console program debugged in Visual Studio prints to its own console window, which the debugger
// does not report as output. This reads that window's text for the agent, from a small Windows
// PowerShell helper process that attaches to the program's console: Visual Studio itself never
// attaches to a console, so closing the program's window can never close Visual Studio.

using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;

namespace AutoDebug.VisualStudio
{
    sealed class ConsoleReader : IDisposable
    {
        // Attach to the program's console, then print each finished line of its screen buffer once, until the
        // program exits (one last read after that). PID is replaced with the program's process ID.
        const string Script = @"
$ErrorActionPreference = 'Stop'
Add-Type -Namespace AutoDebug -Name Con -MemberDefinition @'
[DllImport(""kernel32.dll"")] public static extern bool FreeConsole();
[DllImport(""kernel32.dll"")] public static extern bool AttachConsole(uint pid);
[DllImport(""kernel32.dll"", CharSet = CharSet.Unicode)] public static extern IntPtr CreateFile(string name, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
[DllImport(""kernel32.dll"")] public static extern bool GetConsoleScreenBufferInfo(IntPtr handle, out Info info);
[DllImport(""kernel32.dll"", CharSet = CharSet.Unicode)] public static extern bool ReadConsoleOutputCharacter(IntPtr handle, System.Text.StringBuilder text, uint length, int at, out uint read);
[DllImport(""kernel32.dll"")] public static extern bool CloseHandle(IntPtr handle);
[StructLayout(LayoutKind.Sequential)] public struct Info { public short SizeX, SizeY, CursorX, CursorY, Attributes, Left, Top, Right, Bottom, MaxX, MaxY; }
'@
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$out = [Console]::Out
[AutoDebug.Con]::FreeConsole() | Out-Null
if (-not [AutoDebug.Con]::AttachConsole(PID)) { exit 2 }
$row = 0
$last = $false
while ($true) {
  $running = $null -ne (Get-Process -Id PID -ErrorAction SilentlyContinue)
  $handle = [AutoDebug.Con]::CreateFile('CONOUT$', 0xC0000000, 3, [IntPtr]::Zero, 3, 0, [IntPtr]::Zero)
  if ($handle -eq [IntPtr]-1) { exit 0 }
  $info = New-Object AutoDebug.Con+Info
  if ([AutoDebug.Con]::GetConsoleScreenBufferInfo($handle, [ref]$info)) {
    if ($info.CursorY -lt $row) { $row = 0 }
    while ($row -lt $info.CursorY) {
      $text = New-Object System.Text.StringBuilder ([int]$info.SizeX)
      $read = [uint32]0
      [AutoDebug.Con]::ReadConsoleOutputCharacter($handle, $text, [uint32]$info.SizeX, ($row -shl 16), [ref]$read) | Out-Null
      $out.WriteLine($text.ToString().TrimEnd())
      $row++
    }
    $out.Flush()
  }
  [AutoDebug.Con]::CloseHandle($handle) | Out-Null
  if ($last) { exit 0 }
  if (-not $running) { $last = $true } else { Start-Sleep -Milliseconds 400 }
}
";

        readonly Process helper;

        ConsoleReader(Process helper) { this.helper = helper; }

        /// <summary>Start reading the console of process <paramref name="processId"/>; every finished line goes to
        /// <paramref name="line"/>. Null when the helper cannot start (then there is simply no output).</summary>
        public static ConsoleReader Start(uint processId, Action<string> line, Action<string> log)
        {
            try
            {
                var script = Script.Replace("PID", processId.ToString(CultureInfo.InvariantCulture));
                var encoded = Convert.ToBase64String(Encoding.Unicode.GetBytes(script));
                var shell = Path.Combine(System.Environment.SystemDirectory, "WindowsPowerShell", "v1.0", "powershell.exe");
                var start = new ProcessStartInfo(shell, $"-NoProfile -NonInteractive -EncodedCommand {encoded}")
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
