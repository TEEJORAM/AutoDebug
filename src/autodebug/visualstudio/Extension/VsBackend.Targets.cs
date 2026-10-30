// Part of VsBackend (VsBackend.cs): launch targets: the startup project's debug settings.

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
        // -- launch targets: the startup project's debug settings --------------------------------

        public Dictionary<string, object> Workspace(string folder) => OnMain(() =>
        {
            var launch = new List<object>();
            var tasks = new List<object>();
            var solution = dte.Solution;
            var solutionConfig = solution?.SolutionBuild?.ActiveConfiguration as SolutionConfiguration2;
            var solutionName = solutionConfig == null ? "" : $"{solutionConfig.Name}|{solutionConfig.PlatformName}";
            foreach (var uniqueName in ((solution?.SolutionBuild?.StartupProjects as object[]) ?? new object[0]).OfType<string>())
            {
                var target = Target(uniqueName);
                if (target == null) continue;
                launch.Add(target);
                var label = $"Build {target["project"]} ({target["configuration"]})";
                lock (buildTargets) buildTargets[label] = (uniqueName, (string)target["configuration"]);
                tasks.Add(Json.Make("label", label, "command", $"build project {target["project"]} ({target["configuration"]})"));
            }
            if (solutionConfig != null)
            {
                var label = $"Build solution ({solutionName})";
                lock (buildTargets) buildTargets[label] = (null, solutionName);
                tasks.Add(Json.Make("label", label, "command", $"build the solution ({solutionName})"));
            }
            launch.Add(Json.Make("name", "Attach to a process (native)", "type", "visualstudio", "request", "attach",
                "processId", "${command:pickProcess}", "engine", "native"));
            launch.Add(Json.Make("name", "Attach to a process (.NET)", "type", "visualstudio", "request", "attach",
                "processId", "${command:pickProcess}", "engine", "managed"));
            return Json.Make("folder", solutionFolder ?? folder, "launch", launch, "tasks", tasks);
        });

        Dictionary<string, object> Target(string uniqueName)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            var solution = (IVsSolution)Package.GetGlobalService(typeof(SVsSolution));
            if (solution == null || solution.GetProjectOfUniqueName(uniqueName, out var hierarchy) != VSConstants.S_OK) return null;
            hierarchy.GetProperty((uint)VSConstants.VSITEMID.Root, (int)__VSHPROPID.VSHPROPID_ExtObject, out var extObject);
            var project = extObject as Project;
            var active = project?.ConfigurationManager?.ActiveConfiguration;
            if (project == null || active == null) return null;
            var configuration = $"{active.ConfigurationName}|{active.PlatformName}";
            var storage = hierarchy as IVsBuildPropertyStorage;
            string Read(string name, _PersistStorageType where)
            {
                if (storage == null) return null;
                return storage.GetPropertyValue(name, configuration, (uint)where, out var value) == VSConstants.S_OK ? value : null;
            }
            var targetPath = Read("TargetPath", _PersistStorageType.PST_PROJECT_FILE);
            var projectDir = Path.GetDirectoryName(project.FullName) ?? "";
            if (IsManaged(project.FullName)) return ManagedTarget(project, configuration, targetPath, projectDir);
            string Expand(string value) => (value ?? "")
                .Replace("$(TargetPath)", targetPath ?? "")
                .Replace("$(ProjectDir)", projectDir.EndsWith("\\") ? projectDir : projectDir + "\\")
                .Replace("$(SolutionDir)", (solutionFolder ?? "") + "\\");
            var program = Expand(Read("LocalDebuggerCommand", _PersistStorageType.PST_USER_FILE));
            if (string.IsNullOrWhiteSpace(program)) program = targetPath;
            if (string.IsNullOrWhiteSpace(program)) return null;
            var arguments = Expand(Read("LocalDebuggerCommandArguments", _PersistStorageType.PST_USER_FILE));
            var cwd = Expand(Read("LocalDebuggerWorkingDirectory", _PersistStorageType.PST_USER_FILE));
            var env = new Dictionary<string, object>();
            foreach (var line in Expand(Read("LocalDebuggerEnvironment", _PersistStorageType.PST_USER_FILE)).Split('\n'))
            {
                var equals = line.IndexOf('=');
                if (equals > 0) env[line.Substring(0, equals).Trim()] = line.Substring(equals + 1).TrimEnd('\r');
            }
            return Json.Make("name", $"{project.Name} ({configuration})", "type", "visualstudio", "request", "launch",
                "program", program, "args", string.IsNullOrWhiteSpace(arguments) ? new List<object>() : new List<object> { arguments },
                "cwd", string.IsNullOrWhiteSpace(cwd) ? projectDir : cwd, "env", env, "project", project.Name,
                "configuration", configuration, "engine", "native");
        }

        static bool IsManaged(string file)
        {
            var extension = Path.GetExtension(file ?? "").ToLowerInvariant();
            return extension == ".csproj" || extension == ".vbproj" || extension == ".fsproj";
        }

        static string Property(Properties properties, string name)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            try { return Convert.ToString(properties?.Item(name)?.Value); }
            catch (ArgumentException) { return null; }
            catch (COMException) { return null; }
        }

        // A .NET project (C#, Visual Basic, F#): its program (the .exe, else dotnet with the .dll) and the profile in
        // Properties/launchSettings.json that Visual Studio starts ("commandName": "Project").
        Dictionary<string, object> ManagedTarget(Project project, string configuration, string targetPath, string projectDir)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            if (string.IsNullOrWhiteSpace(targetPath))
            {
                var output = Property(project.ConfigurationManager?.ActiveConfiguration?.Properties, "OutputPath");
                var file = Property(project.Properties, "OutputFileName");
                if (!string.IsNullOrEmpty(output) && !string.IsNullOrEmpty(file)) targetPath = Path.Combine(projectDir, output, file);
            }
            if (string.IsNullOrWhiteSpace(targetPath)) return null;
            var framework = (Property(project.Properties, "TargetFrameworkMoniker") ?? "").StartsWith(".NETFramework", StringComparison.OrdinalIgnoreCase);
            var profile = LaunchProfile(projectDir);
            var arguments = Json.Str(profile, "commandLineArgs") ?? "";
            var cwd = Json.Str(profile, "workingDirectory");
            var env = new Dictionary<string, object>();
            foreach (var pair in Json.Obj(Json.Get(profile, "environmentVariables"))) env[pair.Key] = Convert.ToString(pair.Value);
            var native = Json.Get(profile, "nativeDebugging") is bool mixed && mixed;
            var program = targetPath;
            if (!framework && targetPath.EndsWith(".dll", StringComparison.OrdinalIgnoreCase))
            {
                var host = Path.ChangeExtension(targetPath, ".exe");
                if (File.Exists(host)) program = host;
                else
                {
                    program = DotnetPath();
                    arguments = $"\"{targetPath}\" {arguments}".Trim();
                }
            }
            var engine = framework ? (native ? "mixed_framework" : "framework") : (native ? "mixed" : "managed");
            return Json.Make("name", $"{project.Name} ({configuration})", "type", "visualstudio", "request", "launch",
                "program", program, "args", string.IsNullOrWhiteSpace(arguments) ? new List<object>() : new List<object> { arguments },
                "cwd", string.IsNullOrWhiteSpace(cwd) ? projectDir : Path.Combine(projectDir, cwd), "env", env,
                "project", project.Name, "configuration", configuration, "engine", engine);
        }

        static Dictionary<string, object> LaunchProfile(string projectDir)
        {
            try
            {
                var file = Path.Combine(projectDir, "Properties", "launchSettings.json");
                if (!File.Exists(file)) return new Dictionary<string, object>();
                var profiles = Json.Obj(Json.Get(Json.Obj(Json.Parse(File.ReadAllText(file))), "profiles"));
                return profiles.Values.Select(Json.Obj).FirstOrDefault(p => Json.Str(p, "commandName") == "Project")
                       ?? new Dictionary<string, object>();
            }
            catch (Exception) { return new Dictionary<string, object>(); } // an unreadable profile: start without it
        }

        static string DotnetPath()
        {
            foreach (var folder in (System.Environment.GetEnvironmentVariable("PATH") ?? "").Split(';'))
            {
                try
                {
                    var candidate = Path.Combine(folder.Trim(), "dotnet.exe");
                    if (File.Exists(candidate)) return candidate;
                }
                catch (ArgumentException) { /* not a folder */ }
            }
            return Path.Combine(System.Environment.GetFolderPath(System.Environment.SpecialFolder.ProgramFiles), "dotnet", "dotnet.exe");
        }

        // The debug engines for a configuration's "engine": native (C, C++), managed (.NET), framework (.NET
        // Framework), or both kinds at once (mixed: native code and .NET in one process).
        static Guid[] Engines(string engine)
        {
            switch (engine)
            {
                case "managed": return new[] { ManagedEngine };
                case "framework": return new[] { FrameworkEngine };
                case "mixed": return new[] { NativeEngine, ManagedEngine };
                case "mixed_framework": return new[] { NativeEngine, FrameworkEngine };
                default: return new[] { NativeEngine };
            }
        }
    }
}
