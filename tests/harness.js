'use strict';
// Runs the real extension core (src/autodebug/extension/bridge.js) against a
// stand-in VS Code API, so Python tests can drive it over the real protocol.
// Debug sessions are scripted, or, with HARNESS_DEBUGPY=<python>, real DAP
// sessions with that Python's debugpy adapter (what the Python extension uses).
//
// usage: node harness.js <bridges-folder> <workspace-folder>
// stdin: approve | deny | breakpoints | exit
// stdout: READY | DIALOG <json> | BREAKPOINTS <n> | LOG <text>

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const readline = require('readline');
const { Bridge } = require('../src/autodebug/extension/bridge');

const [bridgesFolder, workspace] = process.argv.slice(2);
const python = process.env.HARNESS_DEBUGPY;
const buildExit = Number(process.env.HARNESS_BUILD_EXIT || 0);
const say = (line) => process.stdout.write(`${line}\n`);
const readJson = (name) => { try { return JSON.parse(fs.readFileSync(path.join(workspace, '.vscode', name), 'utf8')); } catch (_) { return {}; } };

class Position { constructor(line, character) { this.line = line; this.character = character; } }
class Location { constructor(uri, position) { this.uri = uri; this.range = { start: position }; } }
class SourceBreakpoint { constructor(location, enabled, condition) { this.location = location; this.enabled = enabled; this.condition = condition; } }

let bridge;
let tracker;
let session;
const dialogs = [];
const breakpoints = [];
const taskListeners = [];
const byFile = () => {
  const files = new Map();
  for (const b of breakpoints) {
    const file = b.location.uri.fsPath;
    files.set(file, [...(files.get(file) || []), b.location.range.start.line + 1]);
  }
  return files;
};

// A scripted program: geometry.py's loop for a moved unit square.
const TRACE = [
  { line: 12, vars: { points: '[(2, 1), (3, 1), (3, 2), (2, 2)]', total: '0.0' } },
  { line: 15, vars: { i: '0', total: '0.0', password: "'hunter2'" } },
  { line: 12, vars: { i: '0', total: '-1.0' } },
  { line: 15, vars: { i: '1', total: '-1.0' } },
  { line: 12, vars: { i: '1', total: '2.0' } },
  { line: 15, vars: { i: '2', total: '2.0' } },
  { line: 16, vars: { total: '4.0' } },
];

class ScriptedSession {
  constructor(configuration) { this.id = 'dap-1'; this.name = configuration.name; this.configuration = configuration; this.pos = -1; this.seq = 1; }
  file() { return path.join(workspace, 'geometry.py'); }
  send(message) { tracker.onDidSendMessage(message); }
  event(event, body = {}) { this.send({ type: 'event', event, body }); }
  start() {
    for (const [file, lines] of byFile()) {
      const seq = this.seq++;
      tracker.onWillReceiveMessage({ type: 'request', seq, command: 'setBreakpoints', arguments: { source: { path: file }, breakpoints: lines.map((line) => ({ line })) } });
      this.send({ type: 'response', request_seq: seq, command: 'setBreakpoints', success: true, body: { breakpoints: lines.map((line) => ({ verified: true, line })) } });
    }
    this.event('process', { name: 'python', systemProcessId: 4242 });
    setTimeout(() => this.run(), 10);
  }
  lines() { return (byFile().get(this.file()) || []); }
  run() {
    for (this.pos += 1; this.pos < TRACE.length; this.pos += 1) {
      if (this.lines().includes(TRACE[this.pos].line)) { this.event('stopped', { reason: 'breakpoint', threadId: 1 }); return; }
    }
    this.event('exited', { exitCode: 1 });
    this.event('terminated');
  }
  async customRequest(command, args) {
    const here = TRACE[this.pos] || TRACE[TRACE.length - 1];
    switch (command) {
      case 'stackTrace':
        return { stackFrames: [
          { id: 1, name: 'polygon_area', source: { path: this.file() }, line: here.line },
          { id: 2, name: 'test_area_does_not_change_when_moved', source: { path: path.join(workspace, 'test_geometry.py') }, line: 18 },
        ].slice(0, args.levels) };
      case 'scopes': return { scopes: [{ name: 'Locals', variablesReference: args.frameId === 1 ? 7 : 8, expensive: false }] };
      case 'variables':
        return { variables: args.variablesReference === 7 ? Object.entries(here.vars).map(([name, value]) => ({ name, value, type: 'str' })) : [{ name: 'self', value: '<test>', type: 'Test' }] };
      case 'next': case 'stepIn': case 'stepOut':
        setTimeout(() => {
          this.pos += 1;
          if (this.pos >= TRACE.length) { this.event('exited', { exitCode: 1 }); this.event('terminated'); } else this.event('stopped', { reason: 'step', threadId: 1 });
        }, 5);
        return {};
      case 'continue': setTimeout(() => this.run(), 5); return {};
      case 'pause': setTimeout(() => this.event('stopped', { reason: 'pause', threadId: 1 }), 5); return {};
      case 'threads': return { threads: [{ id: 1, name: 'main' }] };
      default: throw new Error(`scripted session has no ${command}`);
    }
  }
  stop() { this.event('terminated'); }
}

class DebugpySession {
  constructor(configuration) {
    this.id = 'dap-1'; this.name = configuration.name; this.configuration = configuration; this.seq = 1;
    this.pending = new Map(); this.buffer = Buffer.alloc(0);
    this.initialized = new Promise((resolve) => { this.onInitialized = resolve; });
    this.adapter = childProcess.spawn(python, ['-m', 'debugpy.adapter'], { stdio: ['pipe', 'pipe', 'inherit'] });
    this.adapter.stdout.on('data', (chunk) => this.receive(chunk));
  }
  write(message) { const body = Buffer.from(JSON.stringify(message)); this.adapter.stdin.write(`Content-Length: ${body.length}\r\n\r\n`); this.adapter.stdin.write(body); }
  request(command, args) {
    const message = { seq: this.seq++, type: 'request', command, arguments: args };
    tracker.onWillReceiveMessage(message);
    return new Promise((resolve, reject) => { this.pending.set(message.seq, { resolve, reject }); this.write(message); });
  }
  receive(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    for (;;) {
      const end = this.buffer.indexOf('\r\n\r\n');
      if (end < 0) return;
      const length = Number(/Content-Length: (\d+)/i.exec(this.buffer.subarray(0, end).toString())[1]);
      if (this.buffer.length < end + 4 + length) return;
      const message = JSON.parse(this.buffer.subarray(end + 4, end + 4 + length).toString());
      this.buffer = this.buffer.subarray(end + 4 + length);
      this.handle(message);
    }
  }
  handle(message) {
    if (message.type === 'request' && message.command === 'runInTerminal') {
      const [program, ...args] = message.arguments.args;
      const env = { ...process.env, ...(message.arguments.env || {}) };
      Object.keys(env).forEach((key) => env[key] === null && delete env[key]);
      const child = childProcess.spawn(program, args, { cwd: message.arguments.cwd, env, stdio: 'ignore' });
      this.write({ seq: this.seq++, type: 'response', request_seq: message.seq, success: true, command: 'runInTerminal', body: { processId: child.pid } });
      return;
    }
    tracker.onDidSendMessage(message);
    if (message.type === 'event' && message.event === 'initialized') this.onInitialized();
    if (message.type === 'response' && this.pending.has(message.request_seq)) {
      const { resolve, reject } = this.pending.get(message.request_seq);
      this.pending.delete(message.request_seq);
      if (message.success) resolve(message.body || {}); else reject(new Error(message.message || 'failed'));
    }
  }
  async start() {
    await this.request('initialize', { clientID: 'vscode', adapterID: 'debugpy', pathFormat: 'path', linesStartAt1: true, columnsStartAt1: true, supportsRunInTerminalRequest: true, supportsVariableType: true });
    const launched = this.request('launch', { ...this.configuration, python });
    await this.initialized;
    for (const [file, lines] of byFile()) await this.request('setBreakpoints', { source: { path: file }, breakpoints: lines.map((line) => ({ line })) });
    await this.request('configurationDone', {});
    await launched;
  }
  customRequest(command, args) { return this.request(command, args); }
  stop() { return this.request('disconnect', { terminateDebuggee: true }).catch(() => {}).then(() => this.adapter.kill()); }
}

const resolveVariables = (value) => {
  if (typeof value === 'string') return value.replace(/\$\{workspaceFolder\}/g, workspace);
  if (Array.isArray(value)) return value.map(resolveVariables);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, resolveVariables(v)]));
  return value;
};

const installedDebuggers = (process.env.HARNESS_DEBUGGERS ?? 'debugpy').split(',').filter(Boolean);
const vscode = {
  version: '1.99.0-harness',
  extensions: { all: [{ id: 'ms-python.debugpy', packageJSON: { contributes: { debuggers: installedDebuggers.map((type) => ({ type })) } } }] },
  env: { appName: process.env.HARNESS_APP || 'Cursor', sessionId: 'harnesssession1' },
  Uri: { file: (fsPath) => ({ fsPath }) },
  Position, Location, SourceBreakpoint,
  workspace: {
    workspaceFolders: [{ uri: { fsPath: workspace }, name: path.basename(workspace) }],
    getConfiguration: (section) => ({ get: (key) => readJson(section === 'launch' ? 'launch.json' : 'tasks.json')[key] }),
  },
  window: {
    showWarningMessage: (message, options, ...items) => new Promise((resolve) => {
      say(`DIALOG ${JSON.stringify({ message, detail: options.detail, modal: options.modal, items })}`);
      dialogs.push(resolve);
    }),
  },
  tasks: {
    fetchTasks: async () => (readJson('tasks.json').tasks || []).map((t) => ({ name: t.label, scope: { uri: { fsPath: workspace } } })),
    executeTask: async (task) => {
      const execution = { task };
      setTimeout(() => taskListeners.forEach((listener) => listener({ execution, exitCode: buildExit })), 20);
      return execution;
    },
    onDidEndTaskProcess: (listener) => { taskListeners.push(listener); return { dispose: () => taskListeners.splice(taskListeners.indexOf(listener), 1) }; },
  },
  debug: {
    addBreakpoints: (list) => breakpoints.push(...list),
    removeBreakpoints: (list) => list.forEach((b) => { const i = breakpoints.indexOf(b); if (i >= 0) breakpoints.splice(i, 1); }),
    startDebugging: async (folder, configuration) => {
      const config = resolveVariables(configuration);
      session = python ? new DebugpySession(config) : new ScriptedSession(config);
      tracker = bridge.tracker(session);
      bridge.sessionStarted(session);
      await session.start();
      return true;
    },
    stopDebugging: async (target) => {
      if (target !== session) return;
      await session.stop();
      bridge.sessionEnded(session);
      say('LOG stopped');
    },
  },
};

bridge = new Bridge(vscode, { folder: bridgesFolder, log: (line) => say(`LOG ${line}`) });
bridge.start().then(() => say('READY'), (error) => { say(`ERROR ${error.message}`); process.exit(1); });

readline.createInterface({ input: process.stdin }).on('line', (line) => {
  const command = line.trim();
  if (command === 'approve' || command === 'deny') { const answer = dialogs.shift(); if (answer) answer(command === 'approve' ? 'Approve' : undefined); }
  else if (command === 'breakpoints') say(`BREAKPOINTS ${breakpoints.length}`);
  else if (command === 'exit') bridge.stop().then(() => process.exit(0));
});
