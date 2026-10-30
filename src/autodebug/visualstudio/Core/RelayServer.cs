// The connection the Autodebug server uses: 127.0.0.1 only, a random token, one JSON
// object per line, and a connection file in <state>/bridges (docs/design.md). The same
// contract as the VS Code / Cursor relay.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

namespace AutoDebug
{
    public sealed class RelayServer : IDisposable
    {
        public const string Version = "0.8.0";
        const int MaxLine = 1024 * 1024;

        readonly IBackend backend;
        readonly Gate gate;
        readonly string folder;
        readonly string token;
        readonly int keepMs;
        TcpListener listener;
        Timer keeper;
        volatile bool stopped;

        public string Window { get; }
        public string FilePath => Path.Combine(folder, Window + ".json");
        public int Port => ((IPEndPoint)listener.LocalEndpoint).Port;
        public Gate Gate => gate;

        public RelayServer(IBackend backend, string bridgesFolder = null, int keepMs = 10000)
        {
            this.backend = backend;
            gate = new Gate(backend);
            folder = bridgesFolder ?? Path.Combine(StateFolder(), "bridges");
            this.keepMs = keepMs;
            token = Hex(32);
            Window = $"{backend.Ide}-{Hex(6)}-{System.Diagnostics.Process.GetCurrentProcess().Id}";
        }

        public static string StateFolder()
        {
            var home = Environment.GetEnvironmentVariable("AUTODEBUG_HOME");
            if (!string.IsNullOrEmpty(home)) return home;
            var profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            if (Path.DirectorySeparatorChar == '\\')
            {
                var local = Environment.GetEnvironmentVariable("LOCALAPPDATA");
                return Path.Combine(string.IsNullOrEmpty(local) ? Path.Combine(profile, "AppData", "Local") : local, "autodebug");
            }
            var xdg = Environment.GetEnvironmentVariable("XDG_STATE_HOME");
            return Path.Combine(string.IsNullOrEmpty(xdg) ? Path.Combine(profile, ".local", "state") : xdg, "autodebug");
        }

        static string Hex(int bytes)
        {
            var data = new byte[bytes];
            using (var random = RandomNumberGenerator.Create()) random.GetBytes(data);
            return string.Concat(data.Select(b => b.ToString("x2")));
        }

        public void Start()
        {
            listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start();
            Announce();
            backend.Log($"listening on 127.0.0.1:{Port}");
            new Thread(AcceptLoop) { IsBackground = true, Name = "Autodebug relay" }.Start();
            // If something deletes the connection file while the IDE is open, write it again,
            // or the server could never find this window.
            keeper = new Timer(_ =>
            {
                if (stopped || File.Exists(FilePath)) return;
                Announce();
                backend.Log("the connection file was deleted; wrote it again");
            }, null, keepMs, keepMs);
        }

        public void Announce()
        {
            if (listener == null || stopped) return;
            Directory.CreateDirectory(folder);
            var info = Json.Make("protocol", (long)Gate.Protocol, "port", (long)Port, "token", token, "window", Window, "ide", backend.Ide,
                "folders", backend.Folders().Cast<object>().ToList(), "version", Version);
            var temporary = FilePath + ".tmp";
            File.WriteAllText(temporary, Json.Write(info), new UTF8Encoding(false));
#if NET7_0_OR_GREATER
            if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(temporary, UnixFileMode.UserRead | UnixFileMode.UserWrite);
#endif
            if (File.Exists(FilePath)) File.Delete(FilePath);
            File.Move(temporary, FilePath);
        }

        public void Dispose()
        {
            stopped = true;
            keeper?.Dispose();
            gate.End("the IDE window closed");
            try { File.Delete(FilePath); } catch (Exception) { /* already removed */ }
            try { listener?.Stop(); } catch (Exception) { /* already stopped */ }
        }

        void AcceptLoop()
        {
            while (!stopped)
            {
                TcpClient client;
                try { client = listener.AcceptTcpClient(); }
                catch (Exception) { return; }
                new Thread(() => Serve(client)) { IsBackground = true, Name = "Autodebug connection" }.Start();
            }
        }

        void Serve(TcpClient client)
        {
            using (client)
            using (var stream = client.GetStream())
            {
                var reader = new LineReader(stream);
                var trusted = false;
                try
                {
                    while (!stopped)
                    {
                        var line = reader.Next();
                        if (line == null) return;
                        var message = Json.Obj(Json.Parse(line));
                        if (!trusted)
                        {
                            if (!SameToken(Json.Str(message, "hello"))) return;
                            trusted = true;
                            Send(stream, Json.Make("hello", "ok", "protocol", (long)Gate.Protocol, "window", Window));
                            continue;
                        }
                        Send(stream, Answer(message));
                    }
                }
                catch (Exception) { /* the server went away or sent something unreadable */ }
            }
        }

        bool SameToken(string given)
        {
            if (given == null || given.Length != token.Length) return false;
            var difference = 0;
            for (var i = 0; i < token.Length; i++) difference |= given[i] ^ token[i];
            return difference == 0;
        }

        Dictionary<string, object> Answer(Dictionary<string, object> message)
        {
            var id = Json.Get(message, "id");
            var op = Json.Str(message, "op") ?? "";
            try
            {
                return Json.Make("id", id, "ok", true, "result", gate.Handle(op, Json.Obj(Json.Get(message, "args"))));
            }
            catch (RelayException error)
            {
                return Json.Make("id", id, "ok", false, "error", Json.Make("code", error.Code, "message", error.Message));
            }
            catch (Exception error)
            {
                backend.Log($"error in {op}: {error}");
                return Json.Make("id", id, "ok", false, "error", Json.Make("code", "IDE_ERROR", "message", error.Message));
            }
        }

        static void Send(Stream stream, Dictionary<string, object> message)
        {
            var bytes = new UTF8Encoding(false).GetBytes(Json.Write(message) + "\n");
            stream.Write(bytes, 0, bytes.Length);
            stream.Flush();
        }

        sealed class LineReader
        {
            readonly Stream stream;
            readonly MemoryStream line = new MemoryStream();
            readonly byte[] buffer = new byte[65536];
            int length, at;

            public LineReader(Stream stream) { this.stream = stream; }

            public string Next()
            {
                line.SetLength(0);
                while (true)
                {
                    if (at == length)
                    {
                        length = stream.Read(buffer, 0, buffer.Length);
                        at = 0;
                        if (length <= 0) return null;
                    }
                    var end = Array.IndexOf(buffer, (byte)'\n', at, length - at);
                    if (end < 0)
                    {
                        line.Write(buffer, at, length - at);
                        at = length;
                    }
                    else
                    {
                        line.Write(buffer, at, end - at);
                        at = end + 1;
                        return Encoding.UTF8.GetString(line.ToArray());
                    }
                    if (line.Length > MaxLine) throw new IOException("line too long");
                }
            }
        }
    }
}
