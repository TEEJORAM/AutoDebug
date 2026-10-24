'use strict';
// Runs the real AutoDebug Bridge core (src/autodebug/bridge/extension/bridge-core.js)
// against a stand-in `vscode` API and a scripted debug session, so Python tests
// can drive it over the real protocol. Not VS Code: the first real run is the
// developer's.
//
// usage: node vscode_harness.js <bridges-folder> <workspace-folder>
// stdin: "approve" | "deny" | "exit"; stdout: "READY", "DIALOG <json>", "LOG <text>"

const fs = require('fs');
const path = require('path');
const readline = require('readline');
const { Bridge } = require('../../src/autodebug/bridge/extension/bridge-core');

const [bridgesFolder, workspace] = process.argv.slice(2);
const buildExit = Number(process.env.HARNESS_BUILD_EXIT || 0);
const say = (line) => process.stdout.write(`${line}\n`);

// The scripted program: geometry.py executing polygon_area for a unit square.
const TRACE = [
  { line: 12, vars: { points: '[(0, 0), (1, 0), (1, 1), (0, 1)]', total: '0.0' } },
  { line: 15, vars: { i: '0', total: '0.0', password: "'hunter2'" } },
  { line: 12, vars: { i: '0', total: '0.0' } },
  { line: 15, vars: { i: '1', total: '0.0' } },
  { line: 15, vars: { i: '2', total: '1.0' } },
  { line: 16, vars: { total: '2.0' } },
];

const pendingDialogs = [];
const readJson = (file) => { try { return JSON.parse(fs.readFileSync(path.join(workspace, '.vscode', file), 'utf8')); } catch (_) { return {}; } };

class Position { constructor(line, character) { this.line = line; this.character = character; } }
class Location { constructor(uri, position) { this.uri = uri; this.range = { start: position }; } }
class SourceBreakpoint { constructor(location, enabled) { this.location = location; this.enabled = enabled; } }

let bridge;
let session = null;
let tracker = null;
const breakpoints = [];

class FakeSession {
  constructor(name) {
    this.id = 'dap-session-1';
    this.name = name;
    this.configuration = { name };
    this.position = -1;
    this.seq = 1;
  }
  send(message) { tracker.onDidSendMessage(message); }
  event(event, body) { this.send({ type: 'event', event, body }); }
  file() { return path.join(workspace, 'geometry.py'); }
  planned() { return breakpoints.filter((b) => b.location.uri.fsPath === this.file()).map((b) => b.location.range.start.line + 1); }
  runToBreakpoint(reason) {
    const lines = this.planned();
    for (this.position += 1; this.position < TRACE.length; this.position += 1) {
      if (lines.includes(TRACE[this.position].line)) { this.event('stopped', { reason, threadId: 1 }); return; }
    }
    this.event('terminated', {});
  }
  async customRequest(command, args) {
    const here = TRACE[this.position];
    switch (command) {
      case 'stackTrace':
        return { stackFrames: [
          { id: 1, name: 'polygon_area', source: { path: this.file() }, line: here.line },
          { id: 2, name: 'test_area_does_not_change_when_moved', source: { path: path.join(workspace, 'test_geometry.py') }, line: 18 },
        ].slice(0, args.levels) };
      case 'scopes':
        return { scopes: args.frameId === 1 ? [{ name: 'Locals', variablesReference: 7, expensive: false }] : [] };
      case 'variables':
        return { variables: Object.entries(here.vars).map(([name, value]) => ({ name, value, type: 'str' })) };
      case 'next': case 'stepIn': case 'stepOut':
        setTimeout(() => {
          this.position += 1;
          if (this.position >= TRACE.length) this.event('terminated', {});
          else this.event('stopped', { reason: 'step', threadId: 1 });
        }, 10);
        return {};
      case 'continue':
        setTimeout(() => this.runToBreakpoint('breakpoint'), 10);
        return {};
      default:
        throw new Error(`harness does not implement ${command}`);
    }
  }
}

const vscode = {
  version: '1.99.0-harness',
  env: { appName: 'Visual Studio Code', sessionId: 'harness0session1' },
  Uri: { file: (fsPath) => ({ fsPath }) },
  Position, Location, SourceBreakpoint,
  workspace: {
    workspaceFolders: [{ uri: { fsPath: workspace }, name: path.basename(workspace) }],
    getConfiguration: (section) => ({
      get: (key) => (section === 'launch' ? readJson('launch.json')[key] : readJson('tasks.json')[key]),
    }),
  },
  window: {
    showWarningMessage: (message, options, ...items) => new Promise((resolve) => {
      say(`DIALOG ${JSON.stringify({ message, detail: options.detail, items, modal: options.modal })}`);
      pendingDialogs.push(resolve);
    }),
  },
  tasks: {
    fetchTasks: async () => (readJson('tasks.json').tasks || []).map((t) => ({ name: t.label, scope: { uri: { fsPath: workspace } } })),
    executeTask: async (task) => {
      const execution = { task };
      setTimeout(() => bridge.taskEnded({ execution, exitCode: buildExit }), 20);
      return execution;
    },
  },
  debug: {
    addBreakpoints: (list) => breakpoints.push(...list),
    removeBreakpoints: (list) => list.forEach((b) => breakpoints.splice(breakpoints.indexOf(b), 1)),
    startDebugging: async (folder, name) => {
      session = new FakeSession(name);
      tracker = bridge.tracker(session);
      bridge.sessionStarted(session);
      const file = session.file();
      tracker.onWillReceiveMessage({ type: 'request', seq: 3, command: 'setBreakpoints',
        arguments: { source: { path: file }, breakpoints: session.planned().map((line) => ({ line })) } });
      session.send({ type: 'response', request_seq: 3, command: 'setBreakpoints', success: true,
        body: { breakpoints: session.planned().map((line) => ({ verified: true, line })) } });
      session.event('process', { name: '/usr/bin/python3', systemProcessId: 4242 });
      setTimeout(() => session.runToBreakpoint('breakpoint'), 10);
      return true;
    },
    stopDebugging: async (target) => {
      if (target === session) { session.event('terminated', {}); bridge.sessionEnded(session); say('LOG debug session stopped'); }
    },
  },
};

bridge = new Bridge(vscode, { folder: bridgesFolder, log: (line) => say(`LOG ${line}`) });
bridge.start().then(() => say(`READY ${bridge.windowId}`), (error) => { say(`ERROR ${error.message}`); process.exit(1); });

readline.createInterface({ input: process.stdin }).on('line', (line) => {
  const command = line.trim();
  if (command === 'approve' || command === 'deny') {
    const resolve = pendingDialogs.shift();
    if (resolve) resolve(command === 'approve' ? 'Approve' : 'Deny');
  } else if (command === 'breakpoints') {
    say(`BREAKPOINTS ${breakpoints.length}`);
  } else if (command === 'exit') {
    bridge.stop().then(() => process.exit(0));
  }
});
