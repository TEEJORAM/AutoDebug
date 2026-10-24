'use strict';
// AutoDebug extension entry point. The logic is in bridge.js.
const vscode = require('vscode');
const { Bridge } = require('./bridge');

let bridge;

function activate(context) {
  const output = vscode.window.createOutputChannel('AutoDebug');
  const log = (line) => output.appendLine(`${new Date().toISOString()} ${line}`);
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 0);
  status.text = '$(debug-alt) AutoDebug';
  status.tooltip = 'AutoDebug is ready. An AI agent can debug here only after you click Approve.';
  status.command = 'autodebug.showLog';
  const folder = vscode.workspace.getConfiguration('autodebug').get('bridgesFolder') || undefined;
  bridge = new Bridge(vscode, { folder, log });
  context.subscriptions.push(
    output, status,
    vscode.commands.registerCommand('autodebug.showLog', () => output.show()),
    vscode.debug.registerDebugAdapterTrackerFactory('*', { createDebugAdapterTracker: (s) => bridge.tracker(s) }),
    vscode.debug.onDidStartDebugSession((s) => bridge.sessionStarted(s)),
    vscode.debug.onDidTerminateDebugSession((s) => bridge.sessionEnded(s)),
    vscode.workspace.onDidChangeWorkspaceFolders(() => bridge.announce()),
    { dispose: () => bridge.stop() },
  );
  bridge.start().then(() => status.show(), (error) => log(`could not start: ${error.message}`));
}

function deactivate() {
  return bridge && bridge.stop();
}

module.exports = { activate, deactivate };
