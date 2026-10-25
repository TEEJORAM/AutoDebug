'use strict';
// AutoDebug extension entry point. The relay is in relay.js; the logic is in the Python server.
const path = require('path');
const vscode = require('vscode');
const { Relay } = require('./relay');
const mcp = require('./mcp');

let relay;

function activate(context) {
  const output = vscode.window.createOutputChannel('AutoDebug');
  const log = (line) => output.appendLine(`${new Date().toISOString()} ${line}`);
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 0);
  status.text = '$(debug-alt) AutoDebug';
  status.tooltip = 'AutoDebug is ready. An AI agent can debug here only after you click Approve.';
  status.command = 'autodebug.showLog';
  const folder = vscode.workspace.getConfiguration('autodebug').get('bridgesFolder') || undefined;
  relay = new Relay(vscode, { folder, log });
  context.subscriptions.push(
    output, status,
    vscode.commands.registerCommand('autodebug.showLog', () => output.show()),
    vscode.debug.registerDebugAdapterTrackerFactory('*', { createDebugAdapterTracker: (s) => relay.tracker(s) }),
    vscode.debug.onDidStartDebugSession((s) => relay.sessionStarted(s)),
    vscode.debug.onDidTerminateDebugSession((s) => relay.sessionEnded(s)),
    vscode.workspace.onDidChangeWorkspaceFolders(() => relay.announce()),
    { dispose: () => relay.stop() },
  );
  relay.start().then(() => status.show(), (error) => log(`could not start: ${error.message}`));
  try {
    mcp.register(vscode, context, { stateFolder: path.dirname(relay.folder), log });
  } catch (error) {
    log(`MCP: could not register the autodebug server: ${error.message}`);
  }
}

function deactivate() {
  return relay && relay.stop();
}

module.exports = { activate, deactivate };
