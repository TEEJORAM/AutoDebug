'use strict';
// Runs the real extension relay (src/autodebug/extension/relay.js) against a
// stand-in VS Code API, so Python tests can drive it over the real protocol.
// The debug session talks the Debug Adapter Protocol to a real adapter process:
// tests/fake_adapter.py (a scripted program), debugpy (HARNESS_DEBUGPY=<python>)
// or gdb (HARNESS_GDB=1).
//
// usage: node harness.js <bridges-folder> <workspace-folder>
// stdin: approve | deny | breakpoints | exit
// stdout: READY | DIALOG <json> | INFO <text> | DISCONNECT <json> | BREAKPOINTS <n> | LOG <text>

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const readline = require('readline');
const { Relay } = require('../src/autodebug/extension/relay');

const [bridgesFolder, workspace] = process.argv.slice(2);
const buildExit = Number(process.env.HARNESS_BUILD_EXIT || 0);
const say = (line) => process.stdout.write(`${line}\n`);
const readJson = (name) => { try { return JSON.parse(fs.readFileSync(path.join(workspace, '.vscode', name), 'utf8')); } catch (_) { return {}; } };

class Position { constructor(line, character) { this.line = line; this.character = character; } }
class Location { constructor(uri, position) { this.uri = uri; this.range = { start: position }; } }
class SourceBreakpoint {
  constructor(location, enabled, condition, hitCondition, logMessage) {
    this.location = location; this.enabled = enabled; this.condition = condition; this.hitCondition = hitCondition; this.logMessage = logMessage;
  }
}
class FunctionBreakpoint { constructor(functionName) { this.functionName = functionName; this.enabled = true; } }

let relay;
let session; // the approved session; with HARNESS_CHILD=1 the program runs in a child session it starts
const sessions = [];
const dialogs = [];
const breakpoints = [];
// HARNESS_EDITOR_BP=geometry.py:16 sets a breakpoint "in the editor" before AutoDebug starts.
for (const spec of (process.env.HARNESS_EDITOR_BP || '').split(',').filter(Boolean)) {
  const [file, line] = spec.split(':');
  breakpoints.push(new SourceBreakpoint(new Location({ fsPath: path.join(workspace, file) }, new Position(Number(line) - 1, 0)), true));
}
const taskListeners = [];
// Like VS Code: each source breakpoint as the Debug Adapter Protocol sends it.
const byFile = () => {
  const files = new Map();
  for (const b of breakpoints) {
    if (!b.location || !b.location.uri) continue;
    const file = b.location.uri.fsPath;
    const start = b.location.range.start;
    const sent = { line: start.line + 1 };
    if (start.character) sent.column = start.character + 1;
    if (b.condition) sent.condition = b.condition;
    if (b.hitCondition) sent.hitCondition = b.hitCondition;
    if (b.logMessage) sent.logMessage = b.logMessage;
    files.set(file, [...(files.get(file) || []), sent]);
  }
  return files;
};
const functionNames = () => breakpoints.filter((b) => b.functionName).map((b) => ({ name: b.functionName }));

// One debug session: VS Code's side of the Debug Adapter Protocol, in brief.
class DapSession {
  constructor(configuration, { parent = null, launcher = false } = {}) {
    this.id = `dap-${sessions.length + 1}`; this.name = configuration.name; this.configuration = configuration; this.seq = 1;
    this.parentSession = parent;
    sessions.push(this);
    this.pending = new Map(); this.buffer = Buffer.alloc(0); this.capabilities = {};
    this.initialized = new Promise((resolve) => { this.onInitialized = resolve; });
    this.kind = process.env.HARNESS_GDB ? 'gdb' : process.env.HARNESS_DEBUGPY ? 'debugpy' : 'fake';
    const [program, args] = {
      gdb: ['gdb', ['-i', 'dap']],
      debugpy: [process.env.HARNESS_DEBUGPY, ['-m', 'debugpy.adapter']],
      fake: [process.env.HARNESS_PYTHON || 'python3', [path.join(__dirname, 'fake_adapter.py'), workspace]],
    }[this.kind];
    const env = launcher ? { ...process.env, HARNESS_LAUNCHER: '1' } : process.env;
    this.adapter = childProcess.spawn(program, args, { stdio: ['pipe', 'pipe', 'inherit'], env });
    this.adapter.stdout.on('data', (chunk) => this.receive(chunk));
    this.adapter.on('exit', (code) => {
      for (const { reject } of this.pending.values()) reject(new Error('the debug adapter exited'));
      this.pending.clear();
      if (this.tracker && !this.exited) { this.exited = true; this.tracker.onExit(code); }
      relay.sessionEnded(this);
      // Like the JavaScript debugger: when the program's session ends, its launcher session ends too.
      if (this.parentSession && this.parentSession.adapter.exitCode === null) this.parentSession.adapter.kill();
    });
  }
  write(message) {
    if (this.adapter.exitCode !== null) return;
    const body = Buffer.from(JSON.stringify(message));
    this.adapter.stdin.write(`Content-Length: ${body.length}\r\n\r\n`);
    this.adapter.stdin.write(body);
  }
  request(command, args) {
    const message = { seq: this.seq++, type: 'request', command, arguments: args };
    if (command === 'disconnect') say(`DISCONNECT ${JSON.stringify(args)}`);
    this.tracker.onWillReceiveMessage(message);
    return new Promise((resolve, reject) => {
      if (this.adapter.exitCode !== null) { reject(new Error('the debug adapter exited')); return; }
      this.pending.set(message.seq, { resolve, reject });
      this.write(message);
    });
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
    this.tracker.onDidSendMessage(message);
    // Like VS Code: a child session whose program ended is disconnected (and its launcher then ends too).
    if (message.type === 'event' && message.event === 'terminated' && this.parentSession) this.stop();
    if (message.type === 'event' && message.event === 'initialized') this.onInitialized();
    if (message.type === 'response' && this.pending.has(message.request_seq)) {
      const { resolve, reject } = this.pending.get(message.request_seq);
      this.pending.delete(message.request_seq);
      if (message.success) resolve(message.body || {}); else reject(new Error(message.message || 'failed'));
    }
  }
  async sendBreakpoints() {
    for (const [file, sent] of byFile()) await this.request('setBreakpoints', { source: { path: file }, breakpoints: sent });
    if (this.capabilities.supportsFunctionBreakpoints) await this.request('setFunctionBreakpoints', { breakpoints: functionNames() });
  }
  async start() {
    this.capabilities = await this.request('initialize', {
      clientID: 'vscode', adapterID: this.kind, pathFormat: 'path', linesStartAt1: true, columnsStartAt1: true,
      supportsRunInTerminalRequest: true, supportsVariableType: true, supportsVariablePaging: true,
      supportsMemoryReferences: true, supportsProgressReporting: true, supportsStartDebuggingRequest: true,
    });
    if (this.kind === 'gdb') {
      await this.initialized;
      await this.sendBreakpoints();
      await this.request('launch', { request: 'launch', program: this.configuration.program, cwd: this.configuration.cwd, args: this.configuration.args || [] });
      await this.request('configurationDone', {});
    } else {
      const args = this.kind === 'debugpy' ? { ...this.configuration, python: process.env.HARNESS_DEBUGPY } : this.configuration;
      const launched = this.request(this.configuration.request === 'attach' ? 'attach' : 'launch', args);
      await this.initialized;
      await this.sendBreakpoints();
      await this.request('configurationDone', {});
      await launched;
    }
    this.started = true;
  }
  customRequest(command, args) { return this.request(command, args); }
  async stop() {
    const done = new Promise((resolve) => setTimeout(resolve, 2000));
    await Promise.race([this.request('disconnect', { terminateDebuggee: true }).catch(() => {}), done]);
    this.adapter.kill();
  }
}

// Like VS Code: breakpoint changes during a live session are sent to the debug adapter.
function sync(changed) {
  for (const target of sessions.filter((d) => d.started && d.adapter.exitCode === null)) {
    const files = new Set(changed.filter((b) => b.location && b.location.uri).map((b) => b.location.uri.fsPath));
    const current = byFile();
    for (const file of files) {
      target.request('setBreakpoints', { source: { path: file }, breakpoints: current.get(file) || [] }).catch(() => {});
    }
    if (changed.some((b) => b.functionName) && target.capabilities.supportsFunctionBreakpoints) {
      target.request('setFunctionBreakpoints', { breakpoints: functionNames() }).catch(() => {});
    }
  }
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
  Position, Location, SourceBreakpoint, FunctionBreakpoint,
  workspace: {
    workspaceFolders: [{ uri: { fsPath: workspace }, name: path.basename(workspace) }],
    getConfiguration: (section) => ({ get: (key) => readJson(section === 'launch' ? 'launch.json' : 'tasks.json')[key] }),
  },
  window: {
    showWarningMessage: (message, options, ...items) => new Promise((resolve) => {
      say(`DIALOG ${JSON.stringify({ message, detail: options.detail, modal: options.modal, items })}`);
      dialogs.push(resolve);
    }),
    showInformationMessage: (message) => { say(`INFO ${message}`); return new Promise(() => {}); },
  },
  tasks: {
    fetchTasks: async () => (readJson('tasks.json').tasks || []).map((t) => ({ name: t.label, scope: { uri: { fsPath: workspace } } })),
    executeTask: async (task) => {
      const execution = { task, terminate: () => say('LOG build terminated') };
      if (process.env.HARNESS_BUILD_HANG !== '1') {
        setTimeout(() => taskListeners.forEach((listener) => listener({ execution, exitCode: buildExit })), 20);
      }
      return execution;
    },
    onDidEndTaskProcess: (listener) => { taskListeners.push(listener); return { dispose: () => taskListeners.splice(taskListeners.indexOf(listener), 1) }; },
  },
  debug: {
    get breakpoints() { return [...breakpoints]; },
    addBreakpoints: (list) => { breakpoints.push(...list); sync(list); },
    removeBreakpoints: (list) => { list.forEach((b) => { const i = breakpoints.indexOf(b); if (i >= 0) breakpoints.splice(i, 1); }); sync(list); },
    startDebugging: async (folder, configuration) => {
      const child = process.env.HARNESS_CHILD === '1';
      session = new DapSession(resolveVariables(configuration), { launcher: child });
      session.tracker = relay.tracker(session);
      relay.sessionStarted(session);
      await session.start();
      if (child) {
        // The launcher starts the program in a child session, as the JavaScript debugger does.
        const program = new DapSession({ ...resolveVariables(configuration), name: `${configuration.name}: geometry.py` }, { parent: session });
        program.tracker = relay.tracker(program);
        relay.sessionStarted(program);
        await program.start();
      }
      return true;
    },
    stopDebugging: async (target) => {
      if (target !== session) return;
      for (const child of sessions.filter((d) => d.parentSession === session)) await child.stop();
      await session.stop();
      relay.sessionEnded(session);
      say('LOG stopped');
    },
  },
};

relay = new Relay(vscode, {
  folder: bridgesFolder,
  log: (line) => say(`LOG ${line}`),
  buildMinuteMs: Number(process.env.HARNESS_BUILD_MINUTE_MS) || 60000,
  keepMs: Number(process.env.HARNESS_KEEP_MS) || 10000,
});
relay.start().then(() => say('READY'), (error) => { say(`ERROR ${error.message}`); process.exit(1); });

readline.createInterface({ input: process.stdin }).on('line', (line) => {
  const command = line.trim();
  if (command === 'approve' || command === 'deny') { const answer = dialogs.shift(); if (answer) answer(command === 'approve' ? 'Approve' : undefined); }
  else if (command === 'breakpoints') say(`BREAKPOINTS ${breakpoints.length}`);
  else if (command === 'exit') relay.stop().then(() => { sessions.forEach((d) => d.adapter.kill()); process.exit(0); });
});
