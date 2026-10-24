'use strict';
// AutoDebug extension core: one debug session per IDE window, driven by the
// AutoDebug MCP server over a token-protected 127.0.0.1 connection.
// See docs/design.md ("Extension protocol"). The `vscode` API is passed in so
// this module can be tested without an IDE.

const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');

const PROTOCOL = 2;
const VERSION = '0.2.0';
const MAX_LINE = 1024 * 1024;
const APPROVAL_SECONDS = 120;
const STEP_COMMANDS = { over: 'next', into: 'stepIn', out: 'stepOut' };
// Extensions to suggest when a launch configuration's debugger is missing.
const DEBUGGER_EXTENSIONS = {
  debugpy: 'Python Debugger', python: 'Python Debugger', cppdbg: 'C/C++', cppvsdbg: 'C/C++', lldb: 'CodeLLDB',
  coreclr: 'C#', java: 'Debugger for Java', go: 'Go', php: 'PHP Debug',
};

class BridgeError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}
const fail = (code, message) => { throw new BridgeError(code, message); };

function stateFolder(env = process.env, platform = process.platform, home = os.homedir()) {
  if (env.AUTODEBUG_HOME) return env.AUTODEBUG_HOME;
  if (platform === 'win32') return path.join(env.LOCALAPPDATA || path.join(home, 'AppData', 'Local'), 'autodebug');
  if (platform === 'darwin') return path.join(home, 'Library', 'Application Support', 'autodebug');
  return path.join(env.XDG_STATE_HOME || path.join(home, '.local', 'state'), 'autodebug');
}

function insideFolder(root, relative) {
  if (typeof relative !== 'string' || !relative.trim()) fail('BAD_REQUEST', 'a breakpoint needs a file');
  const full = path.resolve(root, relative);
  const rel = path.relative(root, full);
  if (!rel || rel.startsWith('..') || path.isAbsolute(rel)) fail('OUTSIDE_WORKSPACE', `${relative} is outside ${root}`);
  return full;
}

class Bridge {
  constructor(vscode, { folder, log, platform = process.platform } = {}) {
    this.vscode = vscode;
    this.folder = folder || path.join(stateFolder(), 'bridges');
    this.log = log || (() => {});
    this.platform = platform;
    this.ide = /cursor/i.test(vscode.env.appName || '') ? 'cursor' : 'vscode';
    const id = String(vscode.env.sessionId || crypto.randomBytes(6).toString('hex')).replace(/[^A-Za-z0-9]/g, '');
    this.window = `${this.ide}-${id.slice(0, 12)}-${process.pid}`;
    this.token = crypto.randomBytes(32).toString('hex');
    this.server = null;
    this.session = null;
    this.trackers = new Map(); // DAP session id -> breakpoint verification and process info
  }

  // ---- lifecycle -----------------------------------------------------------

  get file() { return path.join(this.folder, `${this.window}.json`); }

  folders() { return (this.vscode.workspace.workspaceFolders || []).map((f) => f.uri.fsPath); }

  async start() {
    this.server = net.createServer((socket) => this.accept(socket));
    await new Promise((resolve, reject) => {
      this.server.once('error', reject);
      this.server.listen(0, '127.0.0.1', resolve);
    });
    this.announce();
    this.log(`listening on 127.0.0.1:${this.server.address().port}`);
  }

  announce() {
    if (!this.server) return;
    fs.mkdirSync(this.folder, { recursive: true, mode: 0o700 });
    const info = {
      protocol: PROTOCOL, port: this.server.address().port, token: this.token, window: this.window,
      ide: this.ide, folders: this.folders(), version: VERSION,
    };
    const temporary = `${this.file}.tmp`;
    fs.writeFileSync(temporary, JSON.stringify(info), { mode: 0o600 });
    fs.renameSync(temporary, this.file);
  }

  async stop() {
    if (this.session) await this.end('the IDE window closed');
    try { fs.unlinkSync(this.file); } catch (_) { /* already removed */ }
    if (this.server) this.server.close();
    this.server = null;
  }

  // ---- connection ----------------------------------------------------------

  accept(socket) {
    let buffer = '';
    let trusted = false;
    let queue = Promise.resolve();
    socket.setEncoding('utf8');
    socket.on('error', () => socket.destroy());
    socket.on('data', (chunk) => {
      buffer += chunk;
      if (buffer.length > MAX_LINE) { socket.destroy(); return; }
      let end;
      while ((end = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, end);
        buffer = buffer.slice(end + 1);
        let message;
        try { message = JSON.parse(line); } catch (_) { socket.destroy(); return; }
        if (!trusted) {
          const given = Buffer.from(String(message && message.hello));
          const expected = Buffer.from(this.token);
          if (given.length !== expected.length || !crypto.timingSafeEqual(given, expected)) { socket.destroy(); return; }
          trusted = true;
          socket.write(`${JSON.stringify({ hello: 'ok', protocol: PROTOCOL, window: this.window })}\n`);
          continue;
        }
        queue = queue.then(() => this.answer(socket, message));
      }
    });
  }

  async answer(socket, message) {
    let reply;
    try {
      reply = { id: message.id, ok: true, result: await this.handle(String(message.op), message.args || {}) };
    } catch (error) {
      if (!(error instanceof BridgeError)) this.log(`error in ${message.op}: ${error && error.stack}`);
      const code = error instanceof BridgeError ? error.code : 'IDE_ERROR';
      reply = { id: message.id, ok: false, error: { code, message: String(error && error.message) } };
    }
    if (!socket.destroyed) socket.write(`${JSON.stringify(reply)}\n`);
  }

  handle(op, args) {
    switch (op) {
      case 'info': return { window: this.window, ide: this.ide, ide_version: this.vscode.version, version: VERSION, folders: this.folders() };
      case 'targets': return this.targets(args);
      case 'start': return this.begin(args);
      case 'state': return this.waitState(args);
      case 'stack': return this.stack(args);
      case 'variables': return this.variables(args);
      case 'step': return this.step(args);
      case 'continue': return this.resume();
      case 'pause': return this.pause();
      case 'breakpoints': return this.editBreakpoints(args);
      case 'stop': return this.end('stopped by the agent').then(() => ({ state: this.snapshot() }));
      default: return fail('BAD_REQUEST', `unknown operation ${op}`);
    }
  }

  // ---- targets ---------------------------------------------------------------

  workspaceFolder(fsPath) {
    const all = this.vscode.workspace.workspaceFolders || [];
    if (!fsPath) {
      if (all.length === 1) return all[0];
      fail('BAD_REQUEST', 'this window has several folders; name one');
    }
    const norm = (p) => { const r = path.resolve(p); return this.platform === 'win32' ? r.toLowerCase() : r; };
    const folder = all.find((f) => norm(f.uri.fsPath) === norm(fsPath));
    if (!folder) fail('NOT_FOUND', `${fsPath} is not open in this window`);
    return folder;
  }

  launchConfigs(folder) {
    return (this.vscode.workspace.getConfiguration('launch', folder.uri).get('configurations') || []).filter((c) => c && c.name);
  }

  taskDefinitions(folder) {
    return (this.vscode.workspace.getConfiguration('tasks', folder.uri).get('tasks') || []).filter((t) => t && t.label);
  }

  targets(args) {
    const folder = this.workspaceFolder(args.folder);
    return {
      folder: folder.uri.fsPath,
      launch: this.launchConfigs(folder).map((c) => ({
        name: c.name, type: c.type, request: c.request, program: c.program || c.module || null, args: c.args || [],
      })),
      tasks: this.taskDefinitions(folder).map((t) => ({ label: t.label, command: [t.command, ...(t.args || [])].filter(Boolean).join(' ') })),
    };
  }

  // ---- session state -------------------------------------------------------------

  snapshot() {
    const s = this.session;
    if (!s) return { version: 0, status: 'none' };
    return {
      version: s.version, status: s.status, reason: s.reason, location: s.location, exit_code: s.exitCode,
      message: s.message, steps_used: s.stepsUsed, max_steps: s.maxSteps, build: s.build,
      breakpoints: s.breakpoints.map((b) => ({ file: b.file, line: b.line, verified: this.verified(b), message: this.verifyMessage(b) })),
    };
  }

  update(changes) {
    const s = this.session;
    Object.assign(s, changes);
    s.version += 1;
    const waiters = s.waiters.splice(0);
    waiters.forEach((resolve) => resolve());
  }

  async waitState(args) {
    const since = Number(args.since) || 0;
    const ms = Math.max(0, Math.min(Number(args.wait_ms) || 0, 60000));
    const s = this.session;
    if (s && s.version <= since && ms > 0) {
      await new Promise((resolve) => {
        const timer = setTimeout(resolve, ms);
        s.waiters.push(() => { clearTimeout(timer); resolve(); });
      });
    }
    return { state: this.snapshot() };
  }

  current(...statuses) {
    const s = this.session;
    if (!s) fail('NOT_FOUND', 'no debug session; call start_session first');
    if (statuses.length && !statuses.includes(s.status)) {
      fail(s.status === 'running' ? 'NOT_PAUSED' : 'BAD_REQUEST', `the session is ${s.status}`);
    }
    return s;
  }

  // ---- start: approval, build, launch ------------------------------------------------

  begin(args) {
    if (this.session && !['ended', 'denied', 'build_failed'].includes(this.session.status)) {
      fail('BUSY', 'a debug session is already active in this window; stop it first');
    }
    const folder = this.workspaceFolder(args.folder);
    const launch = this.launchConfigs(folder).find((c) => c.name === args.launch);
    if (!launch) fail('NOT_FOUND', `no launch configuration named "${args.launch}" in .vscode/launch.json`);
    if (launch.request !== 'launch') fail('BAD_REQUEST', 'only "launch" configurations are supported');
    const types = this.debuggerTypes();
    if (types && !types.has(launch.type)) {
      const extension = DEBUGGER_EXTENSIONS[launch.type];
      fail('NOT_FOUND', `${this.ide === 'cursor' ? 'Cursor' : 'VS Code'} has no debugger for type "${launch.type}". `
        + `Ask the developer to install ${extension ? `the ${extension} extension` : 'the extension for it'} and reload the window.`);
    }
    let task = null;
    if (args.task) {
      task = this.taskDefinitions(folder).find((t) => t.label === args.task);
      if (!task) fail('NOT_FOUND', `no task labelled "${args.task}" in .vscode/tasks.json`);
    }
    const breakpoints = (args.breakpoints || []).map((b) => this.breakpoint(folder, b));
    const maxSteps = Math.max(1, Math.min(Number(args.max_steps) || 50, 500));
    const minutes = Math.max(1, Math.min(Number(args.max_minutes) || 30, 120));
    this.session = {
      version: 0, status: 'awaiting_approval', reason: null, location: null, exitCode: null, message: null,
      folder, launch: JSON.parse(JSON.stringify(launch)), task, breakpoints, stepsUsed: 0, maxSteps, minutes,
      goal: String(args.goal || '').slice(0, 500), threadId: null, dap: null, waiters: [], timer: null, build: null,
    };
    this.update({});
    this.ask(this.session);
    return { state: this.snapshot() };
  }

  // Debug types that installed extensions provide; null if the IDE does not say.
  debuggerTypes() {
    const all = this.vscode.extensions && this.vscode.extensions.all;
    if (!Array.isArray(all)) return null;
    const types = new Set();
    for (const extension of all) {
      const debuggers = (extension.packageJSON && extension.packageJSON.contributes && extension.packageJSON.contributes.debuggers) || [];
      debuggers.forEach((d) => d && d.type && types.add(d.type));
    }
    return types;
  }

  breakpoint(folder, b) {
    const line = Number(b && b.line);
    if (!Number.isInteger(line) || line < 1) fail('BAD_REQUEST', 'breakpoint lines are positive integers');
    const full = insideFolder(folder.uri.fsPath, b.file);
    if (!fs.existsSync(full)) fail('NOT_FOUND', `no file ${b.file}`);
    const condition = b.condition ? String(b.condition).slice(0, 500) : undefined;
    return { file: path.relative(folder.uri.fsPath, full).split(path.sep).join('/'), full, line, condition, handle: null };
  }

  dialogText(s) {
    const l = s.launch;
    const program = [l.program || l.module || '', ...[].concat(l.args || [])].filter(Boolean).join(' ');
    return [
      s.goal ? `Goal: ${s.goal}` : null,
      `Folder: ${s.folder.uri.fsPath}`,
      s.task ? `Build first: ${[s.task.command, ...(s.task.args || [])].filter(Boolean).join(' ')}` : 'Build: none',
      `Run: "${l.name}" (${l.type}) ${program}`.trim(),
      `Breakpoints: ${s.breakpoints.map((b) => `${b.file}:${b.line}${b.condition ? ` if ${b.condition}` : ''}`).join(', ') || 'none'}`,
      `Limits: ${s.maxSteps} steps, ${s.minutes} minutes`,
      '',
      'The AI agent can then read the stack and variables, step and continue.',
      'It cannot evaluate code or change variables. Secret-looking values are hidden from it.',
    ].filter((line) => line !== null).join('\n');
  }

  ask(s) {
    const timeout = setTimeout(() => { if (s.status === 'awaiting_approval') this.update({ status: 'denied', reason: 'no answer within 2 minutes' }); }, APPROVAL_SECONDS * 1000);
    if (timeout.unref) timeout.unref();
    Promise.resolve(this.vscode.window.showWarningMessage(
      `AutoDebug: let the AI agent debug "${s.launch.name}"?`, { modal: true, detail: this.dialogText(s) }, 'Approve',
    )).then((choice) => {
      clearTimeout(timeout);
      if (this.session !== s || s.status !== 'awaiting_approval') return;
      if (choice !== 'Approve') { this.update({ status: 'denied', reason: 'the developer did not approve' }); return; }
      this.log(`approved: ${s.launch.name}`);
      s.timer = setTimeout(() => this.end('the session time limit was reached'), s.minutes * 60000);
      if (s.timer.unref) s.timer.unref();
      this.run(s).catch((error) => this.update({ status: 'ended', reason: 'could not start', message: String(error.message || error) }));
    }, () => this.update({ status: 'denied', reason: 'the dialog was dismissed' }));
  }

  async run(s) {
    const vs = this.vscode;
    if (s.task) {
      this.update({ status: 'building', build: { task: s.task.label, status: 'running', exit_code: null } });
      const all = await vs.tasks.fetchTasks();
      const task = all.find((t) => t.name === s.task.label && t.scope && t.scope.uri && t.scope.uri.fsPath === s.folder.uri.fsPath);
      if (!task) { this.update({ status: 'build_failed', message: `task "${s.task.label}" is not available` }); return; }
      const code = await new Promise((resolve) => {
        let execution = null;
        const listener = vs.tasks.onDidEndTaskProcess((e) => {
          if (execution && e.execution === execution) { listener.dispose(); resolve(e.exitCode); }
        });
        Promise.resolve(vs.tasks.executeTask(task)).then((e) => { execution = e; }, () => { listener.dispose(); resolve(null); });
      });
      if (this.session !== s) return;
      const exitCode = code === undefined ? null : code;
      if (code !== 0) {
        this.update({ status: 'build_failed', exitCode, message: 'see the task output in the terminal',
          build: { task: s.task.label, status: 'failed', exit_code: exitCode } });
        return;
      }
      s.build = { task: s.task.label, status: 'succeeded', exit_code: 0 };
    }
    for (const b of s.breakpoints) b.handle = this.sourceBreakpoint(b);
    vs.debug.addBreakpoints(s.breakpoints.map((b) => b.handle));
    this.update({ status: 'starting' });
    s.expecting = s.launch.name;
    const started = await vs.debug.startDebugging(s.folder, s.launch);
    s.expecting = null;
    if (this.session !== s) return;
    if (!started || !s.dap) this.update({ status: 'ended', reason: 'the debugger did not start', message: 'check the Debug Console' });
    else if (s.status === 'starting') this.update({ status: 'running' });
  }

  sourceBreakpoint(b) {
    const vs = this.vscode;
    return new vs.SourceBreakpoint(new vs.Location(vs.Uri.file(b.full), new vs.Position(b.line - 1, 0)), true, b.condition);
  }

  // ---- debug adapter events ---------------------------------------------------------

  key(file) { const p = path.resolve(String(file)); return this.platform === 'win32' ? p.toLowerCase() : p; }

  tracker(dap) {
    const info = { verified: new Map(), pending: new Map() };
    this.trackers.set(dap.id, info);
    this.sessionStarted(dap); // claim it before its first event arrives
    const mine = () => this.session && this.session.dap === dap;
    return {
      onWillReceiveMessage: (m) => {
        if (m && m.type === 'request' && m.command === 'setBreakpoints' && m.arguments && m.arguments.source) {
          info.pending.set(m.seq, { file: m.arguments.source.path, lines: (m.arguments.breakpoints || []).map((b) => b.line) });
        }
      },
      onDidSendMessage: (m) => {
        if (!m) return;
        if (m.type === 'response' && m.command === 'setBreakpoints' && info.pending.has(m.request_seq)) {
          const sent = info.pending.get(m.request_seq);
          info.pending.delete(m.request_seq);
          ((m.body && m.body.breakpoints) || []).forEach((bp, i) => info.verified.set(`${this.key(sent.file)}:${sent.lines[i]}`, bp));
          if (mine()) this.update({});
        } else if (m.type === 'event' && mine()) {
          this.event(m);
        }
      },
      onExit: (code) => { if (mine() && this.session.status !== 'ended') this.finish('the program exited', code); },
    };
  }

  event(m) {
    const s = this.session;
    if (m.event === 'stopped') {
      s.threadId = m.body.threadId;
      this.locate(s, m.body.reason, m.body.threadId);
    } else if (m.event === 'continued') {
      this.update({ status: 'running', location: null, reason: null });
    } else if (m.event === 'exited') {
      if (s.status !== 'ended') s.exitCode = m.body.exitCode;
    } else if (m.event === 'terminated') {
      if (s.status !== 'ended') this.finish('the program exited', s.exitCode);
    }
  }

  async locate(s, reason, threadId) {
    let location = null;
    try {
      const trace = await s.dap.customRequest('stackTrace', { threadId, startFrame: 0, levels: 1 });
      const frame = trace.stackFrames && trace.stackFrames[0];
      if (frame) location = { file: this.relative(frame.source && frame.source.path), line: frame.line };
    } catch (_) { /* location stays unknown */ }
    if (this.session === s) this.update({ status: 'paused', reason, location });
  }

  verified(b) {
    const s = this.session;
    const info = s && s.dap && this.trackers.get(s.dap.id);
    const bp = info && info.verified.get(`${this.key(b.full)}:${b.line}`);
    return Boolean(bp && bp.verified);
  }

  verifyMessage(b) {
    const s = this.session;
    const info = s && s.dap && this.trackers.get(s.dap.id);
    const bp = info && info.verified.get(`${this.key(b.full)}:${b.line}`);
    if (!bp) return s && s.dap ? 'not confirmed by the debugger yet' : 'set when the program starts';
    return bp.verified ? (bp.line && bp.line !== b.line ? `moved to line ${bp.line}` : '') : (bp.message || 'not bound');
  }

  sessionStarted(dap) {
    const s = this.session;
    if (s && s.expecting && !s.dap && dap.configuration && dap.configuration.name === s.expecting) s.dap = dap;
  }

  sessionEnded(dap) {
    if (this.session && this.session.dap === dap && this.session.status !== 'ended') this.finish('the debug session ended', this.session.exitCode);
    this.trackers.delete(dap.id);
  }

  finish(reason, exitCode) {
    const s = this.session;
    clearTimeout(s.timer);
    this.removeBreakpoints(s);
    this.update({ status: 'ended', reason, location: null, exitCode: exitCode === undefined ? null : exitCode });
  }

  removeBreakpoints(s) {
    const handles = s.breakpoints.map((b) => b.handle).filter(Boolean);
    if (handles.length) this.vscode.debug.removeBreakpoints(handles);
    s.breakpoints.forEach((b) => { b.handle = null; });
  }

  relative(file) {
    if (!file) return null;
    const root = this.session.folder.uri.fsPath;
    const rel = path.relative(root, file);
    return !rel.startsWith('..') && !path.isAbsolute(rel) ? rel.split(path.sep).join('/') : file;
  }

  // ---- inspection and control ---------------------------------------------------------

  async stack(args) {
    const s = this.current('paused');
    const levels = Math.max(1, Math.min(Number(args.levels) || 20, 50));
    const trace = await s.dap.customRequest('stackTrace', { threadId: s.threadId, startFrame: 0, levels });
    return {
      frames: (trace.stackFrames || []).slice(0, levels).map((f) => ({
        id: f.id, name: f.name, file: this.relative(f.source && f.source.path), line: f.line,
      })),
    };
  }

  async variables(args) {
    const s = this.current('paused');
    let frame = Number(args.frame);
    if (!Number.isInteger(frame)) {
      const top = await s.dap.customRequest('stackTrace', { threadId: s.threadId, startFrame: 0, levels: 1 });
      frame = top.stackFrames[0].id;
    }
    const scopes = await s.dap.customRequest('scopes', { frameId: frame });
    const found = new Map();
    for (const scope of scopes.scopes || []) {
      if (scope.expensive || !scope.variablesReference) continue;
      const result = await s.dap.customRequest('variables', { variablesReference: scope.variablesReference });
      for (const v of (result.variables || []).slice(0, 200)) {
        if (!found.has(v.name) && !/^(special|function) variables$/.test(v.name)) found.set(v.name, v);
      }
    }
    const wanted = Array.isArray(args.names) ? args.names.map(String) : null;
    const list = wanted ? wanted.filter((n) => found.has(n)).map((n) => found.get(n)) : [...found.values()];
    return { frame, variables: list.map((v) => ({ name: v.name, type: v.type || '', value: String(v.value) })) };
  }

  async step(args) {
    const s = this.current('paused');
    const command = STEP_COMMANDS[args.kind];
    if (!command) fail('BAD_REQUEST', 'kind is over, into or out');
    if (s.stepsUsed >= s.maxSteps) fail('LIMIT', `the approved limit of ${s.maxSteps} steps is used up`);
    const before = s.version;
    s.stepsUsed += 1;
    await s.dap.customRequest(command, { threadId: s.threadId });
    await this.waitFor(s, () => s.version > before && s.status !== 'running', 5000);
    return { state: this.snapshot() };
  }

  waitFor(s, condition, ms) {
    return new Promise((resolve) => {
      const check = () => {
        if (condition()) { clearTimeout(timer); resolve(); } else s.waiters.push(check);
      };
      const timer = setTimeout(resolve, ms);
      check();
    });
  }

  async resume() {
    const s = this.current('paused');
    this.update({ status: 'running', location: null, reason: null });
    await s.dap.customRequest('continue', { threadId: s.threadId });
    return { state: this.snapshot() };
  }

  async pause() {
    const s = this.current('running');
    let threadId = s.threadId;
    if (!threadId) {
      const threads = await s.dap.customRequest('threads', {});
      threadId = threads.threads && threads.threads[0] && threads.threads[0].id;
    }
    await s.dap.customRequest('pause', { threadId });
    return { state: this.snapshot() };
  }

  editBreakpoints(args) {
    const s = this.current('starting', 'running', 'paused');
    const remove = (args.remove || []).map((b) => `${b.file}:${b.line}`);
    const gone = s.breakpoints.filter((b) => remove.includes(`${b.file}:${b.line}`));
    if (gone.length) this.vscode.debug.removeBreakpoints(gone.map((b) => b.handle).filter(Boolean));
    s.breakpoints = s.breakpoints.filter((b) => !gone.includes(b));
    const added = (args.add || []).map((b) => this.breakpoint(s.folder, b))
      .filter((b) => !s.breakpoints.some((x) => x.file === b.file && x.line === b.line));
    added.forEach((b) => { b.handle = this.sourceBreakpoint(b); });
    if (added.length) this.vscode.debug.addBreakpoints(added.map((b) => b.handle));
    s.breakpoints.push(...added);
    this.update({});
    return { state: this.snapshot() };
  }

  async end(reason) {
    const s = this.session;
    if (!s || s.status === 'ended') return;
    clearTimeout(s.timer);
    const dap = s.dap;
    this.removeBreakpoints(s);
    this.update({ status: 'ended', reason, location: null });
    if (dap) {
      try { await this.vscode.debug.stopDebugging(dap); } catch (_) { /* already stopped */ }
    }
  }
}

module.exports = { Bridge, BridgeError, stateFolder, PROTOCOL, VERSION };
