# Autodebug

Lets an AI agent debug your program with this window's own debugger: build,
set breakpoints, run, step, read variables, and write a root-cause report into
your project.

- Nothing runs until you click **Approve** in the dialog, which shows the build
  command, preLaunchTask, postDebugTask, the launch configuration as JSON, the
  breakpoints and the limits. Remote hosts and `${input}` / `${command}`
  substitutions are refused. Attach sessions detach and leave the program running.
- The agent cannot run code or change variables: conditions and log points only read values. Secret-looking values are
  hidden from it.
- The connection is 127.0.0.1 only, protected by a random token.

Set up with `autodebug setup vscode` or `autodebug setup cursor`.
Log: Command Palette → **Autodebug: Show Log**.
