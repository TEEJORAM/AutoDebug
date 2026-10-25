// Loads AutoDebug in the background when Visual Studio starts, and runs the relay
// for as long as Visual Studio is open.

using System;
using System.Runtime.InteropServices;
using System.Threading;
using Microsoft.VisualStudio;
using Microsoft.VisualStudio.Shell;
using Task = System.Threading.Tasks.Task;

namespace AutoDebug.VisualStudio
{
    [PackageRegistration(UseManagedResourcesOnly = true, AllowsBackgroundLoading = true)]
    [ProvideAutoLoad(VSConstants.UICONTEXT.SolutionExists_string, PackageAutoLoadFlags.BackgroundLoad)]
    [ProvideAutoLoad(VSConstants.UICONTEXT.NoSolution_string, PackageAutoLoadFlags.BackgroundLoad)]
    [Guid("6b0f6a8e-1f7d-4c3a-9a51-2d3c8e7b4f10")]
    public sealed class AutoDebugPackage : AsyncPackage
    {
        VsBackend backend;
        RelayServer relay;

        protected override async Task InitializeAsync(CancellationToken cancellationToken, IProgress<ServiceProgressData> progress)
        {
            await JoinableTaskFactory.SwitchToMainThreadAsync(cancellationToken);
            backend = await VsBackend.CreateAsync(this);
            relay = new RelayServer(backend);
            backend.FoldersChanged = () => relay.Announce();
            try
            {
                relay.Start();
            }
            catch (Exception error)
            {
                backend.Log($"could not start: {error.Message}");
            }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                relay?.Dispose();
                backend?.Dispose();
            }
            base.Dispose(disposing);
        }
    }
}
