# Reads a console program's window for AutoDebug in Visual Studio (see ConsoleReader.cs): attaches to the
# program's console and prints each finished line once, until the program exits, then one last read.
# A separate process does this so that Visual Studio itself never attaches to a console.
param([Parameter(Mandatory = $true)][int]$ProcessId)
$ErrorActionPreference = 'Stop'
Add-Type -Namespace AutoDebug -Name Con -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern bool FreeConsole();
[DllImport("kernel32.dll")] public static extern bool AttachConsole(uint pid);
[DllImport("kernel32.dll", CharSet = CharSet.Unicode)] public static extern IntPtr CreateFile(string name, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
[DllImport("kernel32.dll")] public static extern bool GetConsoleScreenBufferInfo(IntPtr handle, out Info info);
[DllImport("kernel32.dll", CharSet = CharSet.Unicode)] public static extern bool ReadConsoleOutputCharacter(IntPtr handle, System.Text.StringBuilder text, uint length, int at, out uint read);
[DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr handle);
[StructLayout(LayoutKind.Sequential)] public struct Info { public short SizeX, SizeY, CursorX, CursorY, Attributes, Left, Top, Right, Bottom, MaxX, MaxY; }
'@
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$out = [Console]::Out
[AutoDebug.Con]::FreeConsole() | Out-Null
if (-not [AutoDebug.Con]::AttachConsole($ProcessId)) { exit 2 }
$row = 0
$last = $false
while ($true) {
  $running = $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
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
