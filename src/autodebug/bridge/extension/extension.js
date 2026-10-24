'use strict';
// AutoDebug Bridge: VS Code entry point. All logic lives in bridge-core.js.
const vscode = require('vscode');
const { Bridge } = require('./bridge-core');

let bridge;

function activate(context) {
  const log = vscode.window.createOutputChannel('AutoDebug Bridge');
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 0);
  status.text = '$(debug-alt) AutoDebug';
  status.tooltip = 'AutoDebug Bridge: nothing runs until you click Approve';
  status.command = 'autodebug.bridge.showLog';
  const folder = vscode.workspace.getConfiguration('autodebug').get('bridgesFolder') || undefined;
  bridge = new Bridge(vscode, { folder, log: (line) => log.appendLine(`${new Date().toISOString()} ${line}`) });
  context.subscriptions.push(
    log, status,
    vscode.commands.registerCommand('autodebug.bridge.showLog', () => log.show()),
    vscode.debug.registerDebugAdapterTrackerFactory('*', { createDebugAdapterTracker: (s) => bridge.tracker(s) }),
    vscode.debug.onDidStartDebugSession((s) => bridge.sessionStarted(s)),
    vscode.debug.onDidTerminateDebugSession((s) => bridge.sessionEnded(s)),
    vscode.tasks.onDidEndTaskProcess((e) => bridge.taskEnded(e)),
    vscode.workspace.onDidChangeWorkspaceFolders(() => bridge.announce()),
    { dispose: () => bridge.stop() },
  );
  bridge.start().then(() => { if (bridge.listening) status.show(); },
    (error) => log.appendLine(`could not start: ${error.message}`));
}

function deactivate() {
  return bridge ? bridge.stop() : undefined;
}

module.exports = { activate, deactivate };
