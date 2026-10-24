# Requirements delta

### UG-01 Guide command
`autodebug guide` prints the GitHub Pages URL, states what AutoDebug can drive
(VS Code and Cursor through the AutoDebug Bridge, only after Approve; updated
by ide-debug-bridge B9), and prints pasteable install, `doctor`, `bridge` and `config`
commands for VS Code and Cursor using the same invocation style as other
hints. It creates no files and exits 0.

### UG-02 Static site
`site/index.html` is self-contained. It includes Windows, macOS and Linux
install and evidence paths, `config` commands for VS Code, Cursor, Claude
Desktop and Claude Code, the synthetic `AUTODEBUG-DEMO` prompt, and a section
for VS Code, Cursor, CLion, Visual Studio and Xcode. It states that nothing runs
until Approve is clicked, which IDEs AutoDebug drives, and that `config` does
not write CLion, Visual Studio or Xcode files.

### UG-03 Pages workflow
`.github/workflows/pages.yml` publishes the `site` directory with the GitHub
Pages deployment actions. It does not install packages or contact a debugger.
