// The Visual Studio relay's shared core with a scripted backend, so Python tests can
// drive it over the real protocol without Visual Studio.
//
// usage: dotnet AutoDebug.Harness.dll <bridges-folder> <workspace-folder>
// stdin: approve | deny | breakpoints | condition <text> | exit
// stdout: READY | DIALOG <json> | DIALOG_CLOSED | INFO <text> | DISCONNECT <json> | BREAKPOINTS <n> | LOG <text>

using System;

namespace AutoDebug.Harness
{
    static class Program
    {
        static int Main(string[] args)
        {
            if (args.Length != 2)
            {
                Console.Error.WriteLine("usage: AutoDebug.Harness <bridges-folder> <workspace-folder>");
                return 2;
            }
            var backend = new ScriptedBackend(System.IO.Path.GetFullPath(args[1]));
            var keep = int.TryParse(Environment.GetEnvironmentVariable("HARNESS_KEEP_MS"), out var ms) ? ms : 10000;
            var relay = new RelayServer(backend, args[0], keep);
            if (int.TryParse(Environment.GetEnvironmentVariable("HARNESS_BUILD_MINUTE_MS"), out var minute)) relay.Gate.BuildMinuteMs = minute;
            if (int.TryParse(Environment.GetEnvironmentVariable("HARNESS_APPROVAL_MS"), out var wait)) relay.Gate.ApprovalMs = wait;
            relay.Start();
            ScriptedBackend.Say("READY");
            string line;
            while ((line = Console.In.ReadLine()) != null)
            {
                if (line.StartsWith("condition ", StringComparison.Ordinal))
                {
                    ScriptedBackend.Say($"CONDITION {(Gate.ConditionAllowed(line.Substring(10)) ? "allowed" : "refused")}");
                    continue;
                }
                switch (line.Trim())
                {
                    case "approve": backend.Answer(true); break;
                    case "deny": backend.Answer(false); break;
                    case "breakpoints": ScriptedBackend.Say($"BREAKPOINTS {backend.Count}"); break;
                    case "exit": relay.Dispose(); return 0;
                }
            }
            relay.Dispose();
            return 0;
        }
    }
}
