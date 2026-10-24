'use strict';
// AutoDebug extension core: one debug session per IDE window, driven by the
// AutoDebug MCP server over a token-protected 127.0.0.1 connection.
// See docs/design.md ("Extension protocol"). The `vscode` API is passed in so
// this module can be tested without an IDE.

const childProcess = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');

const PROTOCOL = 3;
const VERSION = '0.3.0';
const MAX_LINE = 1024 * 1024;
const APPROVAL_SECONDS = 120;
const STEP_COMMANDS = { over: 'next', into: 'stepIn', out: 'stepOut' };
// Extensions to suggest when a launch configuration's debugger is missing.
const DEBUGGER_EXTENSIONS = {
  debugpy: 'Python Debugger', python: 'Python Debugger', cppdbg: 'C/C++', cppvsdbg: 'C/C++', lldb: 'CodeLLDB',
  'lldb-dap': 'LLDB DAP', gdb: 'Native Debug',
  coreclr: 'C#', java: 'Debugger for Java', go: 'Go', php: 'PHP Debug',
};
const PLATFORM_KEY = { win32: 'windows', darwin: 'osx', linux: 'linux' };

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
  if (!rel || rel.startsWith('..') || path.isAbsolute(rel)) {
    fail('OUTSIDE_WORKSPACE', `${relative} is outside ${root}; pass source_folders for folders outside the workspace`);
  }
  return full;
}

function applyPlatform(config, platform) {
  const copy = JSON.parse(JSON.stringify(config));
  const block = copy[PLATFORM_KEY[platform] || 'linux'];
  delete copy.windows;
  delete copy.osx;
  delete copy.linux;
  if (block && typeof block === 'object') Object.assign(copy, block);
  return copy;
}

function walkValues(value, visit, leaf = '') {
  if (typeof value === 'string') visit(value, leaf);
  else if (Array.isArray(value)) value.forEach((item, i) => walkValues(item, visit, String(i)));
  else if (value && typeof value === 'object') {
    Object.entries(value).forEach(([key, item]) => walkValues(item, visit, key));
  }
}

function substitutionTokens(config, allowAttachPid) {
  const found = [];
  walkValues(config, (text, leaf) => {
    const pattern = /\$\{(input|command):([^}]+)\}/g;
    let match;
    while ((match = pattern.exec(text))) {
      if (allowAttachPid && match[1] === 'command' && (leaf === 'processId' || leaf === 'pid')) continue;
      found.push(`\${${match[1]}:${match[2]}}`);
    }
  });
  return found;
}

function hostOf(value) {
  let host = String(value).trim();
  const bracket = /^\[([^\]]+)\](?::\d+)?$/.exec(host);
  if (bracket) host = bracket[1];
  else {
    const withPort = /^(.*):(\d+)$/.exec(host);
    if (withPort) host = withPort[1];
  }
  return host.toLowerCase();
}

function isLocalHost(value) {
  const host = hostOf(value);
  return host === 'localhost' || host === '127.0.0.1' || host === '::1';
}

function remoteProblem(config) {
  if (config.pipeTransport) return 'pipeTransport';
  const checks = [
    ['host', config.host],
    ['address', config.address],
    ['connect.host', config.connect && config.connect.host],
    ['miDebuggerServerAddress', config.miDebuggerServerAddress],
  ];
  for (const [name, value] of checks) {
    if (value != null && value !== '' && !isLocalHost(value)) return name;
  }
  return null;
}

function taskArgs(task) {
  return (task.args || []).map((arg) => (arg && typeof arg === 'object' && 'value' in arg ? arg.value : arg));
}

function taskCommand(task) {
  return [task.command, ...taskArgs(task)].filter((part) => part != null && part !== '').join(' ');
}

function describeTask(label, tasks, seen = new Set()) {
  const task = (tasks || []).find((item) => item.label === label);
  if (!task) return `"${label}" (provided by an extension, command not in tasks.json)`;
  if (seen.has(label)) return `"${label}": ${taskCommand(task)}`;
  seen.add(label);
  const deps = [].concat(task.dependsOn || []).map((dep) => (typeof dep === 'string' ? dep : dep && dep.task)).filter(Boolean);
  const self = `"${label}": ${taskCommand(task)}`;
  if (!deps.length) return self;
  return `${self} (first: ${deps.map((dep) => describeTask(dep, tasks, seen)).join('; ')})`;
}

function tasksInChain(label, tasks, seen = new Set()) {
  if (!label || seen.has(label)) return [];
  seen.add(label);
  const task = (tasks || []).find((item) => item.label === label);
  const found = task ? [task] : [];
  const deps = task
    ? [].concat(task.dependsOn || []).map((dep) => (typeof dep === 'string' ? dep : dep && dep.task)).filter(Boolean)
    : [];
  return found.concat(deps.flatMap((dep) => tasksInChain(dep, tasks, seen)));
}

function splitPath(name) {
  const parts = [];
  String(name).replace(/->/g, '.').split('.').forEach((piece) => {
    const pattern = /([^[\].]+)|\[(\d+)\]/g;
    let match;
    while ((match = pattern.exec(piece))) parts.push(match[1] != null ? match[1] : match[2]);
  });
  return parts.filter(Boolean);
}

function childMatches(child, part) {
  return child.name === part || child.name === `[${part}]`;
}

function processName(pid, platform) {
  try {
    if (platform === 'linux') return fs.readFileSync(`/proc/${pid}/comm`, 'utf8').trim();
    if (platform === 'darwin') {
      return childProcess.execFileSync('ps', ['-p', String(pid), '-o', 'comm='], { timeout: 3000, encoding: 'utf8' }).trim();
    }
    const out = childProcess.execFileSync('tasklist', ['/FI', `PID eq ${pid}`, '/FO', 'CSV', '/NH'], { timeout: 3000, encoding: 'utf8' });
    const match = /^"([^"]+)"/.exec(out.trim());
    return match ? match[1] : '';
  } catch (error) {
    if (platform === 'linux' && error && error.code === 'ENOENT') fail('NOT_FOUND', `no process ${pid}`);
    return '';
  }
}

class Bridge {
  constructor(vscode, { folder, log, platform = process.platform, buildMinuteMs = 60000 } = {}) {
    this.vscode = vscode;
    this.folder = folder || path.join(stateFolder(), 'bridges');
    this.log = log || (() => {});
    this.platform = platform;
    this.buildMinuteMs = buildMinuteMs;
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
      case 'threads': return this.threads(args);
      case 'exceptions': return this.exceptions(args);
      case 'step': return this.step(args);
      case 'continue': return this.resume();
      case 'pause': return this.pause();
      case 'breakpoints': return this.editBreakpoints(args);
      case 'stop': return this.end(this.session && this.session.launch && this.session.launch.request === 'attach'
        ? 'the debugger detached and the program keeps running' : 'stopped by the agent').then(() => ({ state: this.snapshot() }));
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
      launch: this.launchConfigs(folder).map((c) => {
        const prepared = applyPlatform(c, this.platform);
        const types = this.debuggerTypes();
        return {
          name: c.name, type: c.type, request: c.request, program: prepared.program || null, module: prepared.module || null,
          args: prepared.args || [], console: prepared.console || null,
          available: types ? types.has(c.type) : null,
          preLaunchTask: c.preLaunchTask || null, postDebugTask: c.postDebugTask || null,
          attach: c.request === 'attach' ? this.attachTarget(prepared, '') : null,
        };
      }),
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
      thread: s.threadId == null ? null : { id: s.threadId, name: s.threadName || null },
      exception: s.exception || null,
      breakpoints: [
        ...s.breakpoints.map((b) => ({ file: b.file, line: b.line, source: 'session', verified: this.verified(b), message: this.verifyMessage(b) })),
        ...s.functions.map((b) => ({ function: b.name, source: 'session', verified: this.functionVerified(b.name), message: '' })),
        ...this.editorBreakpoints(s),
      ].map(({ full, ...rest }) => rest),
      output: s.status === 'ended' || s.status === 'paused' ? s.output.slice(-20) : [],
      output_note: s.status === 'ended' && !s.output.length && /Terminal$/.test(s.launch.console || '')
        ? 'program output went to the IDE terminal; set "console": "internalConsole" in the launch configuration to capture it' : null,
    };
  }

  // Breakpoints the developer set in the editor: they stop the program too.
  editorBreakpoints(s) {
    const mine = new Set([...s.breakpoints, ...(s.functions || [])].map((b) => b.handle).filter(Boolean));
    return (this.vscode.debug.breakpoints || [])
      .filter((b) => !mine.has(b) && b.enabled !== false && b.location && b.location.uri)
      .map((b) => {
        const full = b.location.uri.fsPath;
        const rel = path.relative(s.folder.uri.fsPath, full);
        const file = !rel.startsWith('..') && !path.isAbsolute(rel) ? rel.split(path.sep).join('/') : full;
        return { file, line: b.location.range.start.line + 1, full, source: 'editor', verified: this.verified({ full, line: b.location.range.start.line + 1 }), message: this.verifyMessage({ full, line: b.location.range.start.line + 1 }) };
      }).concat((this.vscode.debug.breakpoints || []).filter((b) => b.functionName && b.enabled !== false && !mine.has(b)).map((b) => ({
        function: b.functionName, source: 'editor', verified: this.functionVerified(b.functionName), message: '',
      })));
  }

  update(changes) {
    const s = this.session;
    Object.assign(s, changes);
    s.version += 1;
    const waiters = s.waiters.splice(0);
    waiters.forEach((resolve) => resolve());
  }

  async waitState(args) {
    if (args.ask_developer != null) {
      const text = String(args.ask_developer);
      if (text.length > 300) fail('BAD_REQUEST', 'ask_developer is at most 300 characters');
      const active = this.current();
      if (active.asked !== text) {
        active.asked = text;
        this.log(`asked the developer: ${text}`);
        const shown = this.vscode.window.showInformationMessage(`AutoDebug: the AI agent asks you to: ${text}`);
        if (shown && typeof shown.then === 'function') shown.then(() => {}, () => {});
      }
    }
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

  sourceFolders(args) {
    const folders = args.source_folders || [];
    if (!Array.isArray(folders) || folders.length > 10) fail('BAD_REQUEST', 'source_folders accepts at most 10 folders');
    return folders.map((folder) => {
      if (typeof folder !== 'string' || !path.isAbsolute(folder)) fail('BAD_REQUEST', 'source_folders must be absolute paths');
      if (!fs.existsSync(folder)) fail('NOT_FOUND', `source folder not found: ${folder}`);
      return path.resolve(folder);
    });
  }

  prepareLaunch(raw, args) {
    const launch = applyPlatform(raw, this.platform);
    if (!['launch', 'attach'].includes(launch.request)) fail('BAD_REQUEST', 'request must be launch or attach');
    if (args.process_id != null) {
      if (launch.request !== 'attach') fail('BAD_REQUEST', 'process_id is only for attach configurations');
      const pid = Number(args.process_id);
      if (!Number.isInteger(pid) || pid < 1) fail('BAD_REQUEST', 'process_id must be a positive integer');
      const field = launch.type === 'lldb' ? 'pid' : 'processId';
      const current = launch[field];
      const numeric = typeof current === 'number' || (typeof current === 'string' && /^\d+$/.test(current));
      if (numeric && Number(current) !== pid) fail('BAD_REQUEST', 'process_id contradicts the fixed PID');
      if (!numeric && !(typeof current === 'string' && /\$\{command:[^}]+\}/.test(current)) && current != null) {
        fail('BAD_REQUEST', 'process_id contradicts the fixed PID');
      }
      launch[field] = pid;
    }
    if (launch.request === 'attach' && args.process_id == null) {
      const placeholders = [];
      walkValues(launch, (text, leaf) => {
        if ((leaf === 'processId' || leaf === 'pid') && /\$\{command:[^}]+\}/.test(text)) placeholders.push(text);
      });
      if (placeholders.length) fail('BAD_REQUEST', 'pass process_id');
    }
    const tokens = substitutionTokens(launch, launch.request === 'attach');
    if (tokens.length) fail('BAD_REQUEST', `refuses ${tokens.join(', ')}`);
    const remote = remoteProblem(launch);
    if (remote) fail('BAD_REQUEST', `AutoDebug debugs only programs on this computer (${remote})`);
    const shown = JSON.parse(JSON.stringify(launch));
    delete shown.name;
    const json = JSON.stringify(shown, null, 2);
    if (json.length > 4000) fail('BAD_REQUEST', 'the launch configuration is longer than 4000 characters');
    launch._json = json;
    return launch;
  }

  attachTarget(launch, name) {
    const pid = launch.processId || launch.pid;
    if (pid != null && !String(pid).includes('${')) {
      return `Attach to: process ${pid} (${name || 'name unknown'})`;
    }
    const connect = launch.connect || {};
    const host = connect.host || launch.host || 'localhost';
    const port = connect.port || launch.port;
    if (port) return `Attach to: the debugger listening on ${host}:${port}`;
    return 'Attach to: the running program';
  }

  begin(args) {
    if (this.session && !['ended', 'denied', 'build_failed'].includes(this.session.status)) {
      fail('BUSY', 'a debug session is already active in this window; stop it first');
    }
    const folder = this.workspaceFolder(args.folder);
    const found = this.launchConfigs(folder).find((c) => c.name === args.launch);
    if (!found) fail('NOT_FOUND', `no launch configuration named "${args.launch}" in .vscode/launch.json`);
    const launch = this.prepareLaunch(found, args);
    const types = this.debuggerTypes();
    if (types && !types.has(launch.type)) {
      if (this.ide === 'cursor' && (launch.type === 'cppdbg' || launch.type === 'cppvsdbg')) {
        fail('NOT_FOUND', 'Cursor cannot run the Microsoft C/C++ debugger. Use a CodeLLDB configuration ("type": "lldb") instead.');
      }
      const extension = DEBUGGER_EXTENSIONS[launch.type];
      fail('NOT_FOUND', `${this.ide === 'cursor' ? 'Cursor' : 'VS Code'} has no debugger for type "${launch.type}". `
        + `Ask the developer to install ${extension ? `the ${extension} extension` : 'the extension for it'} and reload the window.`);
    }
    const tasks = this.taskDefinitions(folder).map((task) => applyPlatform(task, this.platform));
    let task = null;
    if (args.task) {
      task = tasks.find((t) => t.label === args.task);
      if (!task) fail('NOT_FOUND', `no task labelled "${args.task}" in .vscode/tasks.json`);
    }
    const used = [
      ...tasksInChain(args.task, tasks),
      ...tasksInChain(launch.preLaunchTask, tasks),
      ...tasksInChain(launch.postDebugTask, tasks),
    ];
    const tokens = used.flatMap((item) => substitutionTokens(item, false));
    if (tokens.length) fail('BAD_REQUEST', `refuses ${[...new Set(tokens)].join(', ')}`);
    const extras = this.sourceFolders(args);
    const breakpoints = (args.breakpoints || []).map((b) => this.breakpoint(folder, b, extras));
    const functions = (args.function_breakpoints || []).map((name) => ({ name: String(name), handle: null }));
    const maxSteps = Math.max(1, Math.min(Number(args.max_steps) || 100, 1000));
    const minutes = Math.max(1, Math.min(Number(args.max_minutes) || 30, 480));
    const buildMinutes = Math.max(1, Math.min(Number(args.build_minutes) || 30, 600));
    let processLabel = '';
    const pid = launch.processId || launch.pid;
    if (launch.request === 'attach' && pid != null && /^\d+$/.test(String(pid))) {
      processLabel = processName(Number(pid), this.platform);
    }
    this.session = {
      version: 0, status: 'awaiting_approval', reason: null, location: null, exitCode: null, message: null,
      folder, launch, task, tasks, breakpoints, functions, stepsUsed: 0, maxSteps, minutes, buildMinutes,
      goal: String(args.goal || '').slice(0, 500), threadId: null, threadName: null, exception: null,
      dap: null, waiters: [], timer: null, buildTimer: null, taskExecution: null, build: null,
      output: [], partial: '', sourceFolders: extras, processLabel,
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

  breakpoint(folder, b, extras = []) {
    const line = Number(b && b.line);
    if (!Number.isInteger(line) || line < 1) fail('BAD_REQUEST', 'breakpoint lines are positive integers');
    const root = folder.uri.fsPath;
    let full;
    if (typeof b.file === 'string' && path.isAbsolute(b.file)) {
      full = path.resolve(b.file);
      const allowed = [root, ...extras].some((dir) => {
        const rel = path.relative(dir, full);
        return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
      });
      if (!allowed) fail('OUTSIDE_WORKSPACE', `${b.file} is outside the workspace; pass source_folders for folders outside the workspace`);
    } else {
      full = insideFolder(root, b.file);
    }
    if (!fs.existsSync(full)) fail('NOT_FOUND', `no file ${b.file}`);
    const condition = b.condition ? String(b.condition).slice(0, 500) : undefined;
    const relative = path.relative(root, full);
    const file = !relative.startsWith('..') && !path.isAbsolute(relative) ? relative.split(path.sep).join('/') : full;
    return { file, full, line, condition, handle: null };
  }

  dialogText(s) {
    const l = s.launch;
    const program = [l.program || l.module || '', ...[].concat(l.args || [])].filter(Boolean).join(' ');
    const tasks = s.tasks || [];
    return [
      s.goal ? `Goal: ${s.goal}` : null,
      `Folder: ${s.folder.uri.fsPath}`,
      l.request === 'attach' ? this.attachTarget(l, s.processLabel) : null,
      s.task ? `Build first: ${describeTask(s.task.label, tasks)}` : 'Build: none',
      l.preLaunchTask ? `Before the debugger starts (preLaunchTask): ${describeTask(l.preLaunchTask, tasks)}` : null,
      l.postDebugTask ? `After the session (postDebugTask): ${describeTask(l.postDebugTask, tasks)}` : null,
      `Run: "${l.name}" (${l.type}) ${program}`.trim(),
      l.cwd ? `cwd: ${l.cwd}` : null,
      l.env ? `env: ${JSON.stringify(l.env)}` : null,
      l.envFile ? `envFile: ${l.envFile}` : null,
      `Breakpoints: ${s.breakpoints.map((b) => `${b.file}:${b.line}${b.condition ? ` if ${b.condition}` : ''}`).join(', ') || 'none'}`,
      s.functions.length ? `Function breakpoints: ${s.functions.map((b) => b.name).join(', ')}` : null,
      s.sourceFolders.length ? `Breakpoints may also be set in: ${s.sourceFolders.join(', ')}` : null,
      `Limits: ${s.maxSteps} steps, ${s.minutes} minutes`,
      l.request === 'attach'
        ? 'When the session ends: the debugger detaches and the program keeps running'
        : 'When the session ends: the program is stopped',
      '',
      'The AI agent can then read the stack and variables, step and continue.',
      'It cannot evaluate code or change variables. Secret-looking values are hidden from it.',
      '',
      'Launch configuration, exactly as it will be used:',
      l._json,
    ].filter((line) => line !== null).join('\n');
  }

  ask(s) {
    const timeout = setTimeout(() => { if (s.status === 'awaiting_approval') this.update({ status: 'denied', reason: 'no answer within 2 minutes' }); }, APPROVAL_SECONDS * 1000);
    if (timeout.unref) timeout.unref();
    const title = s.launch.request === 'attach'
      ? `AutoDebug: let the AI agent attach the debugger for "${s.processLabel || s.launch.name}"?`
      : `AutoDebug: let the AI agent debug "${s.launch.name}"?`;
    Promise.resolve(this.vscode.window.showWarningMessage(
      title, { modal: true, detail: this.dialogText(s) }, 'Approve',
    )).then((choice) => {
      clearTimeout(timeout);
      if (this.session !== s || s.status !== 'awaiting_approval') return;
      if (choice !== 'Approve') { this.update({ status: 'denied', reason: 'the developer did not approve' }); return; }
      this.log(`approved: ${s.launch.name}`);
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
        const timer = setTimeout(() => {
          try { if (s.taskExecution) s.taskExecution.terminate(); } catch (_) { /* already finished */ }
          resolve('timeout');
        }, s.buildMinutes * this.buildMinuteMs);
        if (timer.unref) timer.unref();
        s.buildTimer = timer;
        const listener = vs.tasks.onDidEndTaskProcess((e) => {
          if (s.taskExecution && e.execution === s.taskExecution) { listener.dispose(); clearTimeout(timer); resolve(e.exitCode); }
        });
        Promise.resolve(vs.tasks.executeTask(task)).then((execution) => { s.taskExecution = execution; }, () => {
          listener.dispose(); clearTimeout(timer); resolve(null);
        });
      });
      if (this.session !== s || s.status === 'ended') return;
      if (code === 'timeout') {
        const unit = s.buildMinutes === 1 ? 'minute' : 'minutes';
        this.update({ status: 'build_failed', message: `the build took longer than ${s.buildMinutes} ${unit}`,
          build: { task: s.task.label, status: 'failed', exit_code: null } });
        return;
      }
      const exitCode = code === undefined ? null : code;
      if (code !== 0) {
        this.update({ status: 'build_failed', exitCode, message: 'see the task output in the terminal',
          build: { task: s.task.label, status: 'failed', exit_code: exitCode } });
        return;
      }
      s.build = { task: s.task.label, status: 'succeeded', exit_code: 0 };
    }
    for (const b of s.breakpoints) b.handle = this.sourceBreakpoint(b);
    for (const fn of s.functions) fn.handle = new vs.FunctionBreakpoint(fn.name);
    vs.debug.addBreakpoints([...s.breakpoints.map((b) => b.handle), ...s.functions.map((b) => b.handle)]);
    s.timer = setTimeout(() => this.end('the session time limit was reached'), s.minutes * 60000);
    if (s.timer.unref) s.timer.unref();
    this.update({ status: 'starting' });
    s.expecting = s.launch.name;
    const configuration = JSON.parse(JSON.stringify(s.launch));
    delete configuration._json;
    const started = await vs.debug.startDebugging(s.folder, configuration);
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
    const info = { verified: new Map(), pending: new Map(), byId: new Map(), capabilities: {} };
    this.trackers.set(dap.id, info);
    this.sessionStarted(dap); // claim it before its first event arrives
    const mine = () => this.session && this.session.dap === dap;
    return {
      onWillReceiveMessage: (m) => {
        if (!m || m.type !== 'request') return;
        if (m.command === 'setBreakpoints' && m.arguments && m.arguments.source) {
          info.pending.set(m.seq, { kind: 'lines', file: m.arguments.source.path, lines: (m.arguments.breakpoints || []).map((b) => b.line) });
        } else if (m.command === 'setFunctionBreakpoints') {
          info.pending.set(m.seq, { kind: 'functions', names: ((m.arguments && m.arguments.breakpoints) || []).map((b) => b.name) });
        }
      },
      onDidSendMessage: (m) => {
        if (!m) return;
        if (m.type === 'response' && m.command === 'initialize' && m.body) info.capabilities = m.body;
        if (m.type === 'response' && info.pending.has(m.request_seq)) {
          const sent = info.pending.get(m.request_seq);
          info.pending.delete(m.request_seq);
          ((m.body && m.body.breakpoints) || []).forEach((bp, i) => {
            const key = sent.kind === 'functions' ? `fn:${sent.names[i]}` : `${this.key(sent.file)}:${sent.lines[i]}`;
            info.verified.set(key, bp);
            if (bp.id != null) info.byId.set(bp.id, key);
          });
          if (mine()) this.update({});
        } else if (m.type === 'event' && m.event === 'breakpoint' && m.body && m.body.breakpoint) {
          const bp = m.body.breakpoint;
          const key = info.byId.get(bp.id);
          if (key) info.verified.set(key, { ...(info.verified.get(key) || {}), ...bp });
          if (this.session) this.update({});
        } else if (m.type === 'event' && m.event === 'output' && mine()) {
          this.capture(m.body);
        } else if (m.type === 'event' && mine()) {
          const run = () => this.event(m);
          this._eventChain = (this._eventChain || Promise.resolve()).then(run, run);
        }
      },
      onExit: (code) => { if (mine() && this.session.status !== 'ended') this.finish('the program exited', code); },
    };
  }

  // Keep the last lines the program printed (stdout, stderr, debug console).
  capture(body) {
    if (!body || body.category === 'telemetry' || typeof body.output !== 'string') return;
    const s = this.session;
    const lines = (s.partial + body.output).split(/\r?\n/);
    s.partial = lines.pop();
    s.output.push(...lines.filter((l) => l.trim()).map((l) => l.slice(0, 500)));
    if (s.output.length > 60) s.output.splice(0, s.output.length - 60);
  }

  async event(m) {
    const s = this.session;
    if (!s) return;
    try {
      if (m.event === 'stopped') {
        const generation = (s.stopGeneration = (s.stopGeneration || 0) + 1);
        s.threadId = m.body.threadId;
        const exception = m.body.reason === 'exception' ? await this.readException(s, m.body.threadId) : null;
        if (this.session !== s || s.stopGeneration !== generation) return;
        await this.locate(s, m.body.reason, m.body.threadId, exception, generation);
      } else if (m.event === 'continued') {
        s.stopGeneration = (s.stopGeneration || 0) + 1;
        this.update({ status: 'running', location: null, reason: null, exception: null });
      } else if (m.event === 'exited') {
        if (s.status !== 'ended') s.exitCode = m.body.exitCode;
      } else if (m.event === 'terminated') {
        if (s.status !== 'ended') this.finish('the program exited', s.exitCode);
      }
    } catch (error) {
      this.log(`error handling ${m.event}: ${error && (error.stack || error)}`);
    }
  }

  async locate(s, reason, threadId, exception = null, generation = null) {
    let location = null;
    try {
      const trace = await s.dap.customRequest('stackTrace', { threadId, startFrame: 0, levels: 1 });
      const frame = trace.stackFrames && trace.stackFrames[0];
      if (frame) location = { file: this.relative(frame.source && frame.source.path), line: frame.line };
    } catch (error) {
      this.log(`error handling stopped: ${error && (error.stack || error)}`);
    }
    if (this.session !== s || (generation != null && s.stopGeneration !== generation)) return;
    const changes = { status: 'paused', reason, location };
    if (exception) changes.exception = exception;
    this.update(changes);
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
    if (bp.verified) return bp.line && bp.line !== b.line ? `moved to line ${bp.line}` : '';
    const adapterMessage = bp.message ? String(bp.message) : '';
    if (s && s.dap && ['starting', 'running', 'paused'].includes(s.status)) {
      return adapterMessage
        ? `not bound yet (${adapterMessage}); it may bind when its module loads`
        : 'not bound yet; it may bind when its module loads';
    }
    return adapterMessage || 'not bound';
  }

  functionVerified(name) {
    const s = this.session;
    const info = s && s.dap && this.trackers.get(s.dap.id);
    const bp = info && info.verified.get(`fn:${name}`);
    return Boolean(bp && bp.verified);
  }

  async readException(s, threadId) {
    const info = s.dap && this.trackers.get(s.dap.id);
    if (!info || !info.capabilities.supportsExceptionInfoRequest) return null;
    try {
      const body = await s.dap.customRequest('exceptionInfo', { threadId });
      return { id: body.exceptionId, description: body.description || '' };
    } catch (_) {
      return null;
    }
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
    if (s.partial && s.partial.trim()) { s.output.push(s.partial.slice(0, 500)); s.partial = ''; }
    clearTimeout(s.timer);
    this.removeBreakpoints(s);
    this.update({ status: 'ended', reason, location: null, exitCode: exitCode === undefined ? null : exitCode });
  }

  removeBreakpoints(s) {
    const handles = [...s.breakpoints, ...(s.functions || [])].map((b) => b.handle).filter(Boolean);
    if (handles.length) this.vscode.debug.removeBreakpoints(handles);
    s.breakpoints.forEach((b) => { b.handle = null; });
    (s.functions || []).forEach((b) => { b.handle = null; });
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
    const levels = Math.max(1, Math.min(Number(args.levels) || 20, 200));
    const start = Math.max(0, Number(args.start_frame) || 0);
    const trace = await s.dap.customRequest('stackTrace', { threadId: s.threadId, startFrame: start, levels });
    const frames = (trace.stackFrames || []).slice(0, levels).map((f) => ({
      id: f.id, name: f.name,
      file: f.source && f.source.path ? this.relative(f.source.path) : '(no source)',
      line: f.line,
    }));
    return { frames, total: trace.totalFrames == null ? start + frames.length : trace.totalFrames };
  }

  async threads(args) {
    const s = this.current('paused', 'running');
    const body = await s.dap.customRequest('threads', {});
    const threads = (body.threads || []).slice(0, 500).map((thread) => ({ id: thread.id, name: thread.name }));
    if (args.select != null) {
      if (s.status !== 'paused') fail('NOT_PAUSED', 'select a thread only while paused');
      const chosen = threads.find((thread) => thread.id === args.select);
      if (!chosen) fail('NOT_FOUND', `no thread ${args.select}`);
      s.threadId = chosen.id;
      s.threadName = chosen.name;
      await this.locate(s, s.reason, chosen.id);
    } else if (s.threadId != null) {
      const current = threads.find((thread) => thread.id === s.threadId);
      if (current) s.threadName = current.name;
    }
    return { threads, current: s.threadId, state: this.snapshot() };
  }

  async exceptions(args) {
    const s = this.current();
    if (!s.dap) fail('NOT_FOUND', 'the debugger is not connected yet');
    const info = this.trackers.get(s.dap.id);
    const filters = (info && info.capabilities && info.capabilities.exceptionBreakpointFilters) || [];
    const offered = filters.map((filter) => ({ id: filter.filter, label: filter.label, default: Boolean(filter.default) }));
    if (Array.isArray(args.enable)) {
      const known = new Set(offered.map((filter) => filter.id));
      const unknown = args.enable.filter((id) => !known.has(id));
      if (unknown.length) {
        fail('BAD_REQUEST', `unknown exception filters: ${unknown.join(', ')}; offered: ${[...known].join(', ') || 'none'}`);
      }
      await s.dap.customRequest('setExceptionBreakpoints', { filters: args.enable });
      s.exceptionFilters = args.enable;
    }
    return { filters: offered };
  }

  async variables(args) {
    const s = this.current('paused');
    let frame = Number(args.frame);
    if (!Number.isInteger(frame)) {
      const top = await s.dap.customRequest('stackTrace', { threadId: s.threadId, startFrame: 0, levels: 1 });
      frame = top.stackFrames[0].id;
    }
    const depth = Math.max(0, Math.min(Number(args.depth) || 0, 3));
    const scopes = await s.dap.customRequest('scopes', { frameId: frame });
    const wanted = Array.isArray(args.names) ? args.names.map(String) : null;
    const searched = (scopes.scopes || []).filter((scope) => !scope.expensive && scope.variablesReference);
    const found = new Map();
    for (const scope of wanted ? searched : searched.slice(0, 1)) {
      const result = await s.dap.customRequest('variables', { variablesReference: scope.variablesReference });
      for (const variable of (result.variables || []).slice(0, 200)) {
        if (!found.has(variable.name) && !/^(special|function) variables$/.test(variable.name)) found.set(variable.name, variable);
      }
    }
    const budget = { nodes: 0 };
    const named = Boolean(wanted);
    let list;
    if (!wanted) list = [...found.values()];
    else {
      list = [];
      for (const name of wanted) {
        const variable = await this.lookup(s, found, name);
        if (variable) list.push({ ...variable, name });
      }
    }
    const variables = [];
    for (const variable of list) variables.push(await this.expand(s, variable, depth, named, budget));
    return { frame, variables };
  }

  async lookup(s, roots, name) {
    const parts = splitPath(name);
    if (!parts.length) return null;
    let current = roots.get(parts[0]);
    if (!current) return null;
    for (const part of parts.slice(1)) {
      if (!current.variablesReference) return null;
      const result = await s.dap.customRequest('variables', { variablesReference: current.variablesReference });
      current = (result.variables || []).find((child) => childMatches(child, part));
      if (!current) return null;
    }
    return current;
  }

  async expand(s, variable, depthLeft, named, budget) {
    if (budget.nodes >= 1000) return { name: variable.name, type: variable.type || '', value: String(variable.value), expandable: true };
    budget.nodes += 1;
    const node = { name: variable.name, type: variable.type || '', value: String(variable.value) };
    if (!variable.variablesReference) return node;
    if (depthLeft <= 0) return { ...node, expandable: true };
    const result = await s.dap.customRequest('variables', { variablesReference: variable.variablesReference });
    const children = result.variables || [];
    const limit = named ? 50 : 20;
    const shown = children.slice(0, limit);
    node.children = [];
    for (const child of shown) {
      if (budget.nodes >= 1000) break;
      node.children.push(await this.expand(s, child, depthLeft - 1, named, budget));
    }
    if (children.length > node.children.length) {
      node.more = children.length - node.children.length;
      node.expandable = true;
    }
    return node;
  }

  async step(args) {
    const s = this.current('paused');
    const command = STEP_COMMANDS[args.kind];
    if (!command) fail('BAD_REQUEST', 'kind is over, into or out');
    if (s.stepsUsed >= s.maxSteps) fail('LIMIT', `the approved limit of ${s.maxSteps} steps is used up`);
    const waitMs = Math.max(0, Math.min(Number(args.wait_ms) || 15000, 60000));
    const before = s.version;
    const stepsBefore = s.stepsUsed;
    const pausedAt = { location: s.location, reason: s.reason };
    s.stepsUsed += 1;
    s.stopGeneration = (s.stopGeneration || 0) + 1;
    this.update({ status: 'running', location: null, reason: null });
    try {
      await s.dap.customRequest(command, { threadId: s.threadId });
    } catch (error) {
      s.stepsUsed = stepsBefore;
      if (this.session === s) this.update({ status: 'paused', location: pausedAt.location, reason: pausedAt.reason });
      throw error;
    }
    await this.waitFor(s, () => s.version > before && s.status !== 'running', waitMs);
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
    s.stopGeneration = (s.stopGeneration || 0) + 1;
    this.update({ status: 'running', location: null, reason: null, exception: null });
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
    const added = (args.add || []).map((b) => this.breakpoint(s.folder, b, s.sourceFolders || []))
      .filter((b) => !s.breakpoints.some((x) => x.file === b.file && x.line === b.line));
    added.forEach((b) => { b.handle = this.sourceBreakpoint(b); });
    if (added.length) this.vscode.debug.addBreakpoints(added.map((b) => b.handle));
    s.breakpoints.push(...added);
    for (const name of args.add_functions || []) {
      if (!s.functions.some((item) => item.name === name)) {
        const handle = new this.vscode.FunctionBreakpoint(name);
        s.functions.push({ name: String(name), handle });
        this.vscode.debug.addBreakpoints([handle]);
      }
    }
    for (const name of args.remove_functions || []) {
      const gone = s.functions.filter((item) => item.name === name);
      if (gone.length) this.vscode.debug.removeBreakpoints(gone.map((item) => item.handle).filter(Boolean));
      s.functions = s.functions.filter((item) => item.name !== name);
    }
    this.update({});
    return { state: this.snapshot() };
  }

  async end(reason) {
    const s = this.session;
    if (!s || s.status === 'ended') return;
    clearTimeout(s.timer);
    clearTimeout(s.buildTimer);
    if (s.taskExecution && s.taskExecution.terminate) {
      try { s.taskExecution.terminate(); } catch (_) { /* the build already finished */ }
    }
    const dap = s.dap;
    const attach = s.launch && s.launch.request === 'attach';
    this.removeBreakpoints(s);
    this.update({ status: 'ended', reason, location: null });
    if (dap) {
      if (attach) {
        try { await dap.customRequest('disconnect', { restart: false, terminateDebuggee: false }); } catch (_) { /* already gone */ }
      }
      try { await this.vscode.debug.stopDebugging(dap); } catch (_) { /* already stopped */ }
    }
  }
}

module.exports = { Bridge, BridgeError, stateFolder, PROTOCOL, VERSION };
