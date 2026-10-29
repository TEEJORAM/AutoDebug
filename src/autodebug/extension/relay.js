'use strict';
// AutoDebug extension: a thin relay between the AutoDebug server (Python) and
// this IDE window. The server decides what to debug. This file shows the Approve
// dialog, runs only what the dialog showed, and passes Debug Adapter Protocol
// requests and events through. See docs/design.md ("Extension protocol").
// The `vscode` API is passed in so this module can be tested without an IDE.

const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');

const PROTOCOL = 4;
const VERSION = '0.6.0';
const MAX_LINE = 1024 * 1024;
const APPROVAL_SECONDS = 120;
const MAX_EVENTS = 5000;
const MAX_CONFIG = 4000;
// The only debugger requests the server may send. They read state or move the program; none evaluates an
// expression or changes a value (no evaluate, setVariable, setExpression, writeMemory, goto or restartFrame).
const DAP_COMMANDS = new Set(['threads', 'stackTrace', 'scopes', 'variables', 'next', 'stepIn', 'stepOut', 'continue',
  'pause', 'exceptionInfo', 'setExceptionBreakpoints', 'dataBreakpointInfo', 'setDataBreakpoints', 'modules',
  'loadedSources', 'source', 'stepInTargets', 'disassemble', 'readMemory', 'breakpointLocations', 'stepBack',
  'reverseContinue']);
const STEPS = new Set(['next', 'stepIn', 'stepOut', 'stepBack']);
// What this relay can do beyond protocol 4's first version; the server checks it.
const FEATURES = ['breakpoint_options', 'child_sessions', 'inspection'];
const HIT = /^\s*(>=|<=|==|>|<|%)?\s*\d{1,9}\s*$/;
const VARIABLE_PATH = /^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*|->[A-Za-z_$][\w$]*|\[\d{1,9}\])*$/;
// IDE-to-debugger requests and debugger responses the server needs to see.
const TO_ADAPTER = new Set(['setBreakpoints', 'setFunctionBreakpoints']);
const RESPONSES = new Set(['initialize', 'setBreakpoints', 'setFunctionBreakpoints']);
const PLATFORM_KEY = { win32: 'windows', darwin: 'osx', linux: 'linux' };
const OPEN = ['awaiting_approval', 'building', 'starting', 'debugging'];

class RelayError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}
const fail = (code, message) => { throw new RelayError(code, message); };
const clamp = (value, low, fallback, high) => Math.max(low, Math.min(Number(value) || fallback, high));

function stateFolder(env = process.env, platform = process.platform, home = os.homedir()) {
  if (env.AUTODEBUG_HOME) return env.AUTODEBUG_HOME;
  if (platform === 'win32') return path.join(env.LOCALAPPDATA || path.join(home, 'AppData', 'Local'), 'autodebug');
  if (platform === 'darwin') return path.join(home, 'Library', 'Application Support', 'autodebug');
  return path.join(env.XDG_STATE_HOME || path.join(home, '.local', 'state'), 'autodebug');
}

function within(root, full) {
  const rel = path.relative(root, full);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

function applyPlatform(item, platform) {
  const copy = JSON.parse(JSON.stringify(item));
  const block = copy[PLATFORM_KEY[platform] || 'linux'];
  delete copy.windows; delete copy.osx; delete copy.linux;
  if (block && typeof block === 'object') Object.assign(copy, block);
  return copy;
}

// A breakpoint as the dialog shows it: where, and what it does there.
function describeBreakpoint(where, b) {
  const parts = [`${where}:${b.line}${b.column ? `:${b.column}` : ''}`];
  if (b.condition) parts.push(`if ${b.condition}`);
  if (b.hit) parts.push(`at hit ${b.hit}`);
  if (b.log) parts.push(`logs "${b.log}" without stopping`);
  return parts.join(' ');
}

function taskCommand(task) {
  const args = (task.args || []).map((arg) => (arg && typeof arg === 'object' && 'value' in arg ? arg.value : arg));
  return [task.command, ...args].filter((part) => part != null && part !== '').join(' ');
}

// A task as the dialog shows it, with everything it depends on.
function describeTask(label, tasks, seen = new Set()) {
  const task = tasks.find((item) => item.label === label);
  if (!task) return `"${label}" (provided by an extension, command not in tasks.json)`;
  const self = `"${label}": ${taskCommand(task)}`;
  if (seen.has(label)) return self;
  seen.add(label);
  const deps = [].concat(task.dependsOn || []).map((dep) => (typeof dep === 'string' ? dep : dep && dep.task)).filter(Boolean);
  return deps.length ? `${self} (first: ${deps.map((dep) => describeTask(dep, tasks, seen)).join('; ')})` : self;
}

const sessionId = (dap) => String((dap && dap.id) || '');

class Relay {
  constructor(vscode, { folder, log, platform = process.platform, buildMinuteMs = 60000, keepMs = 10000 } = {}) {
    this.vscode = vscode;
    this.folder = folder || path.join(stateFolder(), 'bridges');
    this.log = log || (() => {});
    this.platform = platform;
    this.buildMinuteMs = buildMinuteMs;
    this.keepMs = keepMs;
    this.ide = /cursor/i.test(vscode.env.appName || '') ? 'cursor' : 'vscode';
    const id = String(vscode.env.sessionId || crypto.randomBytes(6).toString('hex')).replace(/[^A-Za-z0-9]/g, '');
    this.window = `${this.ide}-${id.slice(0, 12)}-${process.pid}`;
    this.token = crypto.randomBytes(32).toString('hex');
    this.server = null;
    this.session = null;
    this.sessions = 0;
    this.queue = [];
    this.seq = 0;
    this.droppedOutput = 0;
    this.waiters = [];
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
    // If something deletes the connection file while the window is open, write it again,
    // or the server could never find this window.
    this.keeper = setInterval(() => {
      if (this.server && !fs.existsSync(this.file)) {
        this.announce();
        this.log('the connection file was deleted; wrote it again');
      }
    }, this.keepMs);
    if (this.keeper.unref) this.keeper.unref();
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
    clearInterval(this.keeper);
    await this.end('the IDE window closed');
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
      if (!(error instanceof RelayError)) this.log(`error in ${message.op}: ${error && error.stack}`);
      const code = error instanceof RelayError ? error.code : 'IDE_ERROR';
      reply = { id: message.id, ok: false, error: { code, message: String(error && error.message) } };
    }
    if (!socket.destroyed) socket.write(`${JSON.stringify(reply)}\n`);
  }

  handle(op, args) {
    switch (op) {
      case 'info': return {
        window: this.window, ide: this.ide, ide_version: this.vscode.version, version: VERSION, folders: this.folders(),
        platform: this.platform, debugger_types: this.debuggerTypes(), features: FEATURES,
      };
      case 'workspace': return this.workspace(args);
      case 'approve': return this.approve(args);
      case 'events': return this.events(args);
      case 'dap': return this.dap(args);
      case 'breakpoints': return this.breakpoints(args);
      case 'editor_breakpoints': return { breakpoints: this.editorBreakpoints() };
      case 'notify': return this.notify(args);
      case 'stop': return this.end(String(args.reason || 'stopped by the agent')).then(() => ({}));
      default: return fail('BAD_REQUEST', `unknown operation ${op}`);
    }
  }

  // ---- workspace -------------------------------------------------------------

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

  workspace(args) {
    const folder = this.workspaceFolder(args.folder);
    return { folder: folder.uri.fsPath, launch: this.launchConfigs(folder), tasks: this.taskDefinitions(folder) };
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
    return [...types];
  }

  // ---- events: everything the server needs to follow the session ------------------

  emit(event) {
    this.seq += 1;
    this.queue.push({ seq: this.seq, ...event });
    if (this.queue.length > MAX_EVENTS) {
      // Program output goes first, so a flood of it never pushes out a stop or the end.
      const output = this.queue.findIndex((e) => e.kind === 'dap' && e.message && e.message.event === 'output');
      if (output >= 0) { this.queue.splice(output, 1); this.droppedOutput += 1; } else this.queue.shift();
    }
    this.waiters.splice(0).forEach((wake) => wake());
  }

  async events(args) {
    const since = Number(args.since) || 0;
    const ms = clamp(args.wait_ms, 0, 0, 60000);
    if (this.seq <= since && ms > 0) {
      await new Promise((resolve) => {
        const timer = setTimeout(resolve, ms);
        this.waiters.push(() => { clearTimeout(timer); resolve(); });
      });
    }
    const events = this.queue.filter((e) => e.seq > since).slice(0, 500);
    return {
      events, next: events.length ? events[events.length - 1].seq : Math.min(since, this.seq), latest: this.seq,
      dropped: this.queue.length > 0 && this.queue[0].seq > since + 1 && since < this.seq
        && !(this.queue[0].kind === 'dap' && this.droppedOutput > 0),
      dropped_output: this.droppedOutput,
    };
  }

  // ---- approve: the only way anything runs ------------------------------------------

  approve(args) {
    if (this.session && OPEN.includes(this.session.phase)) {
      fail('BUSY', 'a debug session is already active in this window; stop it first');
    }
    const folder = this.workspaceFolder(args.folder);
    const launch = args.launch;
    if (!launch || typeof launch !== 'object' || !launch.name || !launch.type) fail('BAD_REQUEST', 'a launch configuration is needed');
    if (!['launch', 'attach'].includes(launch.request)) fail('BAD_REQUEST', 'request must be launch or attach');
    const shown = { ...launch };
    delete shown.name;
    const json = JSON.stringify(shown, null, 2);
    if (json.length > MAX_CONFIG) fail('BAD_REQUEST', `the launch configuration is longer than ${MAX_CONFIG} characters`);
    const tasks = this.taskDefinitions(folder).map((task) => applyPlatform(task, this.platform));
    const task = args.task ? tasks.find((t) => t.label === args.task) : null;
    if (args.task && !task) fail('NOT_FOUND', `no task labelled "${args.task}" in .vscode/tasks.json`);
    const roots = [folder.uri.fsPath, ...[].concat(args.source_folders || []).map((f) => {
      if (typeof f !== 'string' || !path.isAbsolute(f)) fail('BAD_REQUEST', 'source_folders must be absolute paths');
      return path.resolve(f);
    })];
    const s = {
      id: ++this.sessions, phase: 'awaiting_approval', folder, launch: JSON.parse(JSON.stringify(launch)), json, task, tasks,
      roots, breakpoints: [], functions: [], nextId: 1, stepsUsed: 0,
      // No limits unless asked for: the session runs until the program ends or someone stops it.
      maxSteps: args.max_steps ? clamp(args.max_steps, 1, 1, 100000) : null,
      minutes: args.max_minutes ? clamp(args.max_minutes, 1, 1, 1440) : null,
      buildMinutes: clamp(args.build_minutes, 1, 30, 600),
      notes: [].concat(args.notes || []).map((note) => String(note).slice(0, 500)),
      label: String(args.label || launch.name).slice(0, 200), dap: null, timer: null, buildTimer: null, execution: null,
      children: new Set(), active: null,
    };
    const ids = this.addBreakpoints(s, args.breakpoints || [], args.functions || []);
    this.session = s;
    this.ask(s);
    return { session: s.id, ...ids };
  }

  // Record breakpoints for a session; they reach the IDE when the session runs.
  addBreakpoints(s, lines, functions) {
    const added = { breakpoint_ids: [], function_ids: [] };
    for (const b of lines) {
      const line = Number(b && b.line);
      if (!Number.isInteger(line) || line < 1) fail('BAD_REQUEST', 'breakpoint lines are positive integers');
      if (typeof b.file !== 'string' || !path.isAbsolute(b.file)) fail('BAD_REQUEST', 'breakpoint files are absolute paths');
      const full = path.resolve(b.file);
      if (!s.roots.some((root) => within(root, full))) fail('OUTSIDE_WORKSPACE', `${b.file} is outside the approved folders`);
      const column = b.column == null ? undefined : Number(b.column);
      if (column !== undefined && (!Number.isInteger(column) || column < 1)) fail('BAD_REQUEST', 'breakpoint columns are positive integers');
      const hit = b.hit_condition ? String(b.hit_condition) : undefined;
      if (hit !== undefined && !HIT.test(hit)) fail('BAD_REQUEST', 'hit_condition is a count such as 5, >=5 or %10');
      const log = b.log_message ? String(b.log_message).slice(0, 300) : undefined;
      // A log message shows variables by name only; anything else in braces would be evaluated.
      for (const placeholder of (log || '').matchAll(/\{([^{}]*)\}/g)) {
        if (!VARIABLE_PATH.test(placeholder[1].trim())) fail('BAD_REQUEST', 'log_message may show variables by name only, like {total}');
      }
      const item = {
        id: `b${s.nextId++}`, full, line, column, condition: b.condition ? String(b.condition).slice(0, 500) : undefined,
        hit, log, handle: null,
      };
      s.breakpoints.push(item);
      added.breakpoint_ids.push(item.id);
    }
    for (const name of functions) {
      const item = { id: `f${s.nextId++}`, name: String(name).slice(0, 300), handle: null };
      s.functions.push(item);
      added.function_ids.push(item.id);
    }
    return added;
  }

  relative(s, full) {
    const root = s.folder.uri.fsPath;
    return within(root, full) ? path.relative(root, full).split(path.sep).join('/') : full;
  }

  dialogText(s) {
    const l = s.launch;
    const program = [l.program || l.module || '', ...[].concat(l.args || [])].filter(Boolean).join(' ');
    return [
      ...s.notes,
      `Folder: ${s.folder.uri.fsPath}`,
      s.task ? `Build first: ${describeTask(s.task.label, s.tasks)}` : 'Build: none',
      l.preLaunchTask ? `Before the debugger starts (preLaunchTask): ${describeTask(l.preLaunchTask, s.tasks)}` : null,
      l.postDebugTask ? `After the session (postDebugTask): ${describeTask(l.postDebugTask, s.tasks)}` : null,
      `Run: "${l.name}" (${l.type}) ${program}`.trim(),
      `Breakpoints: ${s.breakpoints.map((b) => describeBreakpoint(this.relative(s, b.full), b)).join(', ') || 'none'}`,
      s.functions.length ? `Function breakpoints: ${s.functions.map((b) => b.name).join(', ')}` : null,
      s.roots.length > 1 ? `Breakpoints may also be set in: ${s.roots.slice(1).join(', ')}` : null,
      s.maxSteps || s.minutes
        ? `Limits: ${s.maxSteps ? `${s.maxSteps} steps` : 'no step limit'}, ${s.minutes ? `${s.minutes} minutes` : 'no time limit'}`
        : 'Limits: none; stop the session any time with the debug toolbar\'s Stop button',
      l.request === 'attach'
        ? 'When the session ends: the debugger detaches and the program keeps running'
        : 'When the session ends: the program is stopped',
      '',
      'The AI agent can then read the stack, variables, modules, machine code and memory, add breakpoints and',
      'watchpoints, step and continue.',
      'It cannot evaluate code or change variables. Secret-looking values are hidden from it.',
      '',
      'Launch configuration, exactly as it will be used:',
      s.json,
    ].filter((line) => line !== null).join('\n');
  }

  ask(s) {
    const answered = (approved, reason) => {
      if (this.session !== s || s.phase !== 'awaiting_approval') return false;
      if (!approved) s.phase = 'denied';
      this.emit({ kind: 'approval', approved, reason });
      return true;
    };
    const timeout = setTimeout(() => answered(false, 'no answer within 2 minutes'), APPROVAL_SECONDS * 1000);
    if (timeout.unref) timeout.unref();
    const title = s.launch.request === 'attach'
      ? `AutoDebug: let the AI agent attach the debugger for "${s.label}"?`
      : `AutoDebug: let the AI agent debug "${s.launch.name}"?`;
    Promise.resolve(this.vscode.window.showWarningMessage(title, { modal: true, detail: this.dialogText(s) }, 'Approve'))
      .then((choice) => {
        clearTimeout(timeout);
        if (choice !== 'Approve') { answered(false, 'the developer did not approve'); return; }
        if (!answered(true, 'the developer clicked Approve')) return;
        this.log(`approved: ${s.launch.name}`);
        this.run(s).catch((error) => {
          this.emit({ kind: 'error', message: String((error && error.message) || error) });
          this.end('could not start');
        });
      }, () => { clearTimeout(timeout); answered(false, 'the dialog was dismissed'); });
  }

  async run(s) {
    const vs = this.vscode;
    if (s.task) {
      s.phase = 'building';
      this.emit({ kind: 'build', task: s.task.label, status: 'running', exit_code: null });
      const all = await vs.tasks.fetchTasks();
      const task = all.find((t) => t.name === s.task.label && t.scope && t.scope.uri && t.scope.uri.fsPath === s.folder.uri.fsPath);
      if (!task) { s.phase = 'build_failed'; this.emit({ kind: 'build', task: s.task.label, status: 'unavailable', exit_code: null }); return; }
      const code = await new Promise((resolve) => {
        const timer = setTimeout(() => {
          try { if (s.execution) s.execution.terminate(); } catch (_) { /* already finished */ }
          resolve('timeout');
        }, s.buildMinutes * this.buildMinuteMs);
        if (timer.unref) timer.unref();
        s.buildTimer = timer;
        const listener = vs.tasks.onDidEndTaskProcess((e) => {
          if (s.execution && e.execution === s.execution) { listener.dispose(); clearTimeout(timer); resolve(e.exitCode); }
        });
        Promise.resolve(vs.tasks.executeTask(task)).then((execution) => { s.execution = execution; }, () => {
          listener.dispose(); clearTimeout(timer); resolve(null);
        });
      });
      if (this.session !== s || s.phase !== 'building') return;
      if (code !== 0) {
        s.phase = 'build_failed';
        this.emit({ kind: 'build', task: s.task.label, status: code === 'timeout' ? 'timeout' : 'failed',
          exit_code: code === 'timeout' || code === undefined ? null : code, minutes: s.buildMinutes });
        return;
      }
      this.emit({ kind: 'build', task: s.task.label, status: 'succeeded', exit_code: 0 });
    }
    this.place(s, s.breakpoints, s.functions);
    if (s.minutes) {
      s.timer = setTimeout(() => this.end('the session time limit was reached'), s.minutes * 60000);
      if (s.timer.unref) s.timer.unref();
    }
    s.phase = 'starting';
    this.emit({ kind: 'starting' });
    s.expecting = s.launch.name;
    const started = await vs.debug.startDebugging(s.folder, JSON.parse(JSON.stringify(s.launch)));
    s.expecting = null;
    if (this.session !== s || s.phase !== 'starting') return;
    if (!started || !s.dap) {
      this.emit({ kind: 'not_started' });
      this.finish(s, 'the debugger did not start', null);
      return;
    }
    s.phase = 'debugging';
    this.emit({ kind: 'started' });
  }

  place(s, lines, functions) {
    const vs = this.vscode;
    for (const b of lines) {
      const at = new vs.Position(b.line - 1, b.column ? b.column - 1 : 0);
      b.handle = new vs.SourceBreakpoint(new vs.Location(vs.Uri.file(b.full), at), true, b.condition, b.hit, b.log);
    }
    for (const f of functions) f.handle = new vs.FunctionBreakpoint(f.name);
    const handles = [...lines, ...functions].map((b) => b.handle);
    if (handles.length) vs.debug.addBreakpoints(handles);
  }

  // ---- the debug session ---------------------------------------------------------

  // A program can run in child debug sessions that its session starts: Node.js and browsers (the JavaScript
  // debugger), Python subprocesses. They belong to the approved session, so their messages are followed too.
  tracker(dap) {
    this.sessionStarted(dap); // claim it before its first message
    const mine = () => this.session && this.session.phase !== 'ended' && this.owns(this.session, dap);
    const id = () => sessionId(dap);
    return {
      onWillReceiveMessage: (m) => {
        if (mine() && m && m.type === 'request' && TO_ADAPTER.has(m.command)) {
          this.emit({ kind: 'dap', direction: 'to_adapter', message: m, session: id() });
        }
      },
      onDidSendMessage: (m) => {
        if (!mine() || !m) return;
        if (m.type === 'event' || (m.type === 'response' && RESPONSES.has(m.command))) {
          if (m.type === 'event' && m.event === 'output' && m.body && typeof m.body.output === 'string' && m.body.output.length > 4000) {
            m = { ...m, body: { ...m.body, output: `${m.body.output.slice(0, 4000)}…` } };
          }
          if (m.type === 'event' && m.event === 'stopped') this.session.active = dap;
          this.emit({ kind: 'dap', direction: 'from_adapter', message: m, session: id() });
        }
      },
      onExit: (code) => {
        if (mine() && this.session.dap === dap) this.finish(this.session, 'the program exited', code == null ? null : code);
      },
    };
  }

  // The approved session itself, or a session it started (directly or through another child).
  owns(s, dap) {
    if (!s.dap || !dap) return false;
    for (let at = dap, depth = 0; at && depth < 20; at = at.parentSession, depth += 1) if (at === s.dap) return true;
    return false;
  }

  sessionStarted(dap) {
    const s = this.session;
    if (!s) return;
    if (s.expecting && !s.dap && dap.configuration && dap.configuration.name === s.expecting && !dap.parentSession) {
      s.dap = dap;
    } else if (s.dap && dap !== s.dap && this.owns(s, dap) && !s.children.has(dap)) {
      s.children.add(dap);
      this.emit({ kind: 'child_started', session: sessionId(dap), name: dap.name || (dap.configuration && dap.configuration.name) });
    }
  }

  sessionEnded(dap) {
    const s = this.session;
    if (!s) return;
    if (s.dap === dap) { this.finish(s, 'the debug session ended', null); return; }
    if (s.children.delete(dap)) {
      if (s.active === dap) s.active = null;
      this.emit({ kind: 'child_ended', session: sessionId(dap), name: dap.name || (dap.configuration && dap.configuration.name) });
    }
  }

  finish(s, reason, exitCode) {
    if (s.phase === 'ended') return;
    clearTimeout(s.timer);
    clearTimeout(s.buildTimer);
    this.removeAll(s);
    s.phase = 'ended';
    this.emit({ kind: 'ended', reason, exit_code: exitCode });
  }

  removeAll(s) {
    const handles = [...s.breakpoints, ...s.functions].map((b) => b.handle).filter(Boolean);
    if (handles.length) this.vscode.debug.removeBreakpoints(handles);
    [...s.breakpoints, ...s.functions].forEach((b) => { b.handle = null; });
  }

  current() {
    const s = this.session;
    if (!s || !['starting', 'debugging'].includes(s.phase) || !s.dap) fail('NOT_FOUND', 'no debug session is running');
    return s;
  }

  async dap(args) {
    const s = this.current();
    const command = String(args.command);
    if (!DAP_COMMANDS.has(command)) fail('BAD_REQUEST', `the debugger request ${command} is not allowed`);
    const step = STEPS.has(command);
    // The session the program last stopped in answers, unless the server names one of the approved sessions.
    let target = s.active || s.dap;
    if (args.session != null) {
      target = [s.dap, ...s.children].find((d) => sessionId(d) === String(args.session));
      if (!target) fail('NOT_FOUND', 'that debug session has ended');
    }
    if (step && s.maxSteps && s.stepsUsed >= s.maxSteps) fail('LIMIT', `the approved limit of ${s.maxSteps} steps is used up`);
    if (step) s.stepsUsed += 1;
    const ms = clamp(args.timeout_ms, 100, 10000, 60000);
    let timer;
    try {
      const answer = await Promise.race([
        target.customRequest(command, args.arguments || {}),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new RelayError('IDE_ERROR', `the debugger did not answer ${command} in time`)), ms); }),
      ]);
      return { body: answer || {} };
    } catch (error) {
      if (step) s.stepsUsed -= 1;
      throw error instanceof RelayError ? error : new RelayError('IDE_ERROR', String((error && error.message) || error));
    } finally {
      clearTimeout(timer);
    }
  }

  breakpoints(args) {
    const s = this.session;
    if (!s || !['starting', 'debugging'].includes(s.phase)) fail('NOT_FOUND', 'no debug session is running');
    const remove = new Set([].concat(args.remove || []).map(String));
    const gone = [...s.breakpoints, ...s.functions].filter((b) => remove.has(b.id));
    const handles = gone.map((b) => b.handle).filter(Boolean);
    if (handles.length) this.vscode.debug.removeBreakpoints(handles);
    s.breakpoints = s.breakpoints.filter((b) => !remove.has(b.id));
    s.functions = s.functions.filter((b) => !remove.has(b.id));
    const before = { lines: s.breakpoints.length, functions: s.functions.length };
    const ids = this.addBreakpoints(s, args.add || [], args.add_functions || []);
    this.place(s, s.breakpoints.slice(before.lines), s.functions.slice(before.functions));
    return ids;
  }

  // Breakpoints the developer set in the editor; they stop the program too.
  editorBreakpoints() {
    const s = this.session;
    const mine = new Set(s ? [...s.breakpoints, ...s.functions].map((b) => b.handle).filter(Boolean) : []);
    return (this.vscode.debug.breakpoints || []).filter((b) => !mine.has(b) && b.enabled !== false).map((b) => {
      if (b.location && b.location.uri) return { file: b.location.uri.fsPath, line: b.location.range.start.line + 1 };
      if (b.functionName) return { function: b.functionName };
      return null;
    }).filter(Boolean);
  }

  notify(args) {
    const text = String(args.text || '');
    if (!text || text.length > 300) fail('BAD_REQUEST', 'the note is 1 to 300 characters');
    if (!this.session || !OPEN.includes(this.session.phase)) fail('NOT_FOUND', 'no debug session is running');
    this.log(`asked the developer: ${text}`);
    const shown = this.vscode.window.showInformationMessage(`AutoDebug: the AI agent asks you to: ${text}`);
    if (shown && typeof shown.then === 'function') shown.then(() => {}, () => {});
    return {};
  }

  async end(reason) {
    const s = this.session;
    if (!s || ['ended', 'denied', 'build_failed'].includes(s.phase)) return;
    const dap = s.dap;
    if (s.execution && s.phase === 'building') {
      try { s.execution.terminate(); } catch (_) { /* the build already finished */ }
    }
    this.finish(s, reason, null);
    if (dap) {
      if (s.launch.request === 'attach') {
        try { await dap.customRequest('disconnect', { restart: false, terminateDebuggee: false }); } catch (_) { /* already gone */ }
      }
      try { await this.vscode.debug.stopDebugging(dap); } catch (_) { /* already stopped */ }
    }
  }
}

module.exports = { Relay, RelayError, stateFolder, PROTOCOL, VERSION };
