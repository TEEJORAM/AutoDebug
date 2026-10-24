'use strict';
// AutoDebug Bridge core (ide-debug-bridge BR-01, BR-04 to BR-08).
//
// Listens on 127.0.0.1 only, accepts one token from a private connection file,
// and performs only what an approval covers. An approval exists only after the
// developer clicks Approve in a modal dialog that lists the whole plan. The
// `vscode` API is passed in so this file can be tested without VS Code.

const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');

const PROTOCOL = 1;
const MAX_MESSAGE = 1024 * 1024;
const DIALOG_SECONDS = 120;
const STEP_KINDS = new Set(['next', 'stepIn', 'stepOut']);
const VERSION = '0.1.0';

class BridgeError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}
const fail = (code, message) => { throw new BridgeError(code, message); };

function defaultBridgesFolder(env = process.env, platform = process.platform, home = os.homedir()) {
  let base;
  if (env.AUTODEBUG_EVIDENCE_DIR) base = env.AUTODEBUG_EVIDENCE_DIR;
  else if (platform === 'win32') base = path.join(env.LOCALAPPDATA || path.join(home, 'AppData', 'Local'), 'autodebug');
  else if (platform === 'darwin') base = path.join(home, 'Library', 'Application Support', 'autodebug');
  else base = path.join(env.XDG_STATE_HOME || path.join(home, '.local', 'state'), 'autodebug');
  return path.join(base, 'bridges');
}

const sameFolder = (a, b, platform = process.platform) => {
  const norm = (p) => {
    const trimmed = p.replace(/[\\/]+$/, '');
    return platform === 'win32' ? trimmed.replace(/\//g, '\\').toLowerCase() : trimmed;
  };
  return norm(a) === norm(b);
};

// Canonical JSON so "unchanged" means the same content, whatever the key order.
function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`;
  }
  return JSON.stringify(value === undefined ? null : value);
}

const sha256 = (data) => crypto.createHash('sha256').update(data).digest('hex');

class Bridge {
  constructor(vscode, { folder, log, platform = process.platform, now = () => Date.now() } = {}) {
    this.vscode = vscode;
    this.folder = folder || defaultBridgesFolder();
    this.log = log || (() => {});
    this.platform = platform;
    this.now = now;
    this.ide = /cursor/i.test(vscode.env.appName || '') ? 'cursor' : 'vscode';
    const session = String(vscode.env.sessionId || crypto.randomBytes(8).toString('hex')).replace(/[^A-Za-z0-9]/g, '');
    this.windowId = `${this.ide}-${session.slice(0, 12)}-${process.pid}`;
    this.token = crypto.randomBytes(32).toString('hex');
    this.server = null;
    this.listening = false;
    this.requests = new Map();      // request_id -> approval request
    this.resolved = null;           // last resolve_plan snapshot
    this.active = null;             // the one approved case in this window
    this.dap = new Map();           // DAP session id -> tracked state
  }

  // -- lifecycle -----------------------------------------------------------

  get connectionFile() { return path.join(this.folder, `${this.windowId}.json`); }

  workspaceFolders() {
    return (this.vscode.workspace.workspaceFolders || []).map((f) => f.uri.fsPath);
  }

  async start() {
    if (!this.workspaceFolders().length) {
      this.log('no folder is open; AutoDebug Bridge stays idle');
      return;
    }
    this.server = net.createServer((socket) => this.connection(socket));
    await new Promise((resolve, reject) => {
      this.server.once('error', reject);
      this.server.listen(0, '127.0.0.1', resolve);
    });
    this.listening = true;
    this.announce();
    this.log(`ready on 127.0.0.1:${this.server.address().port} for ${this.workspaceFolders().join(', ')}`);
  }

  announce() {
    if (!this.listening) return;
    fs.mkdirSync(this.folder, { recursive: true, mode: 0o700 });
    const data = {
      protocol: PROTOCOL, host: '127.0.0.1', port: this.server.address().port, token: this.token,
      window_id: this.windowId, ide: this.ide, workspace_folders: this.workspaceFolders(), extension_version: VERSION,
    };
    const temporary = `${this.connectionFile}.${process.pid}.tmp`;
    fs.writeFileSync(temporary, JSON.stringify(data), { mode: 0o600 });
    fs.renameSync(temporary, this.connectionFile);
  }

  async stop() {
    await this.end('the IDE window is closing');
    try { fs.unlinkSync(this.connectionFile); } catch (_) { /* already gone */ }
    if (this.server) {
      this.server.close();
      this.server = null;
    }
    this.listening = false;
  }

  // -- protocol --------------------------------------------------------------

  connection(socket) {
    let buffer = Buffer.alloc(0);
    let authenticated = false;
    let queue = Promise.resolve();
    socket.on('error', () => socket.destroy());
    socket.on('data', (chunk) => {
      buffer = Buffer.concat([buffer, chunk]);
      if (buffer.length > MAX_MESSAGE) { socket.destroy(); return; }
      let newline;
      while ((newline = buffer.indexOf(10)) !== -1) {
        const line = buffer.subarray(0, newline).toString('utf8');
        buffer = buffer.subarray(newline + 1);
        let message;
        try { message = JSON.parse(line); } catch (_) { socket.destroy(); return; }
        if (!authenticated) {
          const offered = Buffer.from(String(message && message.hello), 'utf8');
          const expected = Buffer.from(this.token, 'utf8');
          if (message.protocol !== PROTOCOL || offered.length !== expected.length
              || !crypto.timingSafeEqual(offered, expected)) {
            socket.destroy(); // BR-01: wrong token gets no reply
            return;
          }
          authenticated = true;
          socket.write(`${JSON.stringify({ hello: 'ok', protocol: PROTOCOL, window_id: this.windowId })}\n`);
          continue;
        }
        queue = queue.then(() => this.reply(socket, message));
      }
    });
  }

  async reply(socket, message) {
    let response;
    try {
      const result = await this.dispatch(String(message.op), message.args || {});
      response = { id: message.id, ok: true, result: result || {} };
    } catch (error) {
      const code = error instanceof BridgeError ? error.code : 'BACKEND_UNAVAILABLE';
      if (!(error instanceof BridgeError)) this.log(`internal error: ${error && error.stack}`);
      response = { id: message.id, ok: false, error: { code, message: String(error && error.message) } };
    }
    if (!socket.destroyed) socket.write(`${JSON.stringify(response)}\n`);
  }

  async dispatch(op, args) {
    switch (op) {
      case 'describe':
        return {
          window_id: this.windowId, ide: this.ide, ide_version: this.vscode.version,
          extension_version: VERSION, workspace_folders: this.workspaceFolders(),
        };
      case 'resolve_plan': return this.resolvePlan(args);
      case 'request_approval': return this.requestApproval(args);
      case 'approval_status': return this.approvalStatus(args);
      default: break;
    }
    const handlers = {
      build_start: () => this.buildStart(), build_status: () => this.buildStatus(),
      launch: () => this.launch(args), breakpoints: () => this.breakpoints(),
      stop_state: () => this.stopState(), stack: () => this.stack(args), variables: () => this.variables(args),
      step: () => this.step(args), continue: () => this.continue(), end: () => this.end('AutoDebug ended the case'),
    };
    if (!handlers[op]) fail('CAPABILITY_UNSUPPORTED', `unknown operation ${op}`); // no evaluate, ever
    await this.requireApproval(args.approval_id, op);
    return handlers[op]();
  }

  // -- plan resolution (BR-03) ---------------------------------------------

  workspaceFolder(fsPath) {
    const folder = (this.vscode.workspace.workspaceFolders || []).find((f) => sameFolder(f.uri.fsPath, fsPath, this.platform));
    if (!folder) fail('TARGET_MISMATCH', `${fsPath} is not open in this window`);
    return folder;
  }

  insideFile(folder, relative) {
    if (typeof relative !== 'string' || !relative || path.isAbsolute(relative) || /^[A-Za-z]:/.test(relative)
        || relative.split(/[\\/]/).some((part) => part === '' || part === '.' || part === '..')) {
      fail('PERMISSION_DENIED', `breakpoint file must stay inside the workspace: ${relative}`);
    }
    return path.join(folder.uri.fsPath, ...relative.split(/[\\/]/));
  }

  snapshot(plan) {
    const folder = this.workspaceFolder(plan.workspace_folder);
    const launches = this.vscode.workspace.getConfiguration('launch', folder.uri).get('configurations') || [];
    const launch = launches.find((c) => c && c.name === plan.launch_configuration_name);
    if (!launch) fail('TARGET_MISMATCH', `launch configuration "${plan.launch_configuration_name}" not found in .vscode/launch.json`);
    let task = null;
    if (plan.build_task !== null && plan.build_task !== undefined) {
      const tasks = this.vscode.workspace.getConfiguration('tasks', folder.uri).get('tasks') || [];
      task = tasks.find((t) => t && t.label === plan.build_task) || null;
      if (!task) fail('TARGET_MISMATCH', `build task "${plan.build_task}" not found in .vscode/tasks.json`);
    }
    const files = {};
    for (const relative of plan.files) {
      let data;
      try { data = fs.readFileSync(this.insideFile(folder, relative)); } catch (error) {
        if (error instanceof BridgeError) throw error;
        fail('TARGET_MISMATCH', `breakpoint file not found: ${relative}`);
      }
      files[relative] = data;
    }
    const launchCopy = JSON.parse(JSON.stringify(launch));
    const taskCopy = task ? JSON.parse(JSON.stringify(task)) : null;
    const fingerprint = sha256(canonical({
      launch: launchCopy, task: taskCopy,
      files: Object.fromEntries(Object.entries(files).map(([k, v]) => [k, sha256(v)])),
    }));
    return { folder, launch: launchCopy, task: taskCopy, files, fingerprint };
  }

  planOf(args) {
    return {
      workspace_folder: String(args.workspace_folder), launch_configuration_name: String(args.launch_configuration_name),
      build_task: args.build_task === null || args.build_task === undefined ? null : String(args.build_task),
      files: Array.isArray(args.files) ? args.files.map(String) : [],
    };
  }

  resolvePlan(args) {
    const plan = this.planOf(args);
    const snap = this.snapshot(plan);
    this.resolved = { plan, snap };
    return {
      launch: snap.launch, task: snap.task,
      files: Object.fromEntries(Object.entries(snap.files).map(([k, v]) => [k, v.toString('base64')])),
    };
  }

  // -- approval (BR-04) --------------------------------------------------------

  describePlan(request) {
    const { snap, plan } = request;
    const launch = snap.launch;
    const program = launch.program || launch.module || launch.name;
    const lines = [
      `Workspace: ${plan.workspace_folder}`,
      snap.task ? `Build first: task "${snap.task.label}" (${[snap.task.command, ...(snap.task.args || [])].join(' ')})` : 'Build: none',
      `Run under the debugger: "${launch.name}" (${launch.type}: ${program}${launch.args ? ` ${[].concat(launch.args).join(' ')}` : ''})`,
      `Stop at: ${request.breakpoints.map((b) => `${b.file}:${b.line}`).join(', ')}`,
      `Limits: up to ${request.maxSteps} steps, ${Math.round(request.seconds / 6) / 10} minutes`,
      '',
      'The AI agent may then read the call stack and variables and step through the code.',
      'It cannot evaluate expressions or change variables. Secret-looking values are hidden.',
      request.reportToWorkspace ? 'A report will be written to autodebug-reports in this folder.' : '',
    ];
    return lines.filter((line, i) => line !== '' || i === 5).join('\n');
  }

  requestApproval(args) {
    if (!this.resolved) fail('NOT_APPROVED', 'resolve the plan first');
    if (this.active) fail('POLICY_LIMIT', `case ${this.active.caseId} is still active in this window; complete or cancel it, or reload the window`);
    const raw = args.plan && typeof args.plan === 'object' ? args.plan : {};
    const plan = this.planOf(raw);
    if (canonical(plan) !== canonical(this.resolved.plan)) fail('PLAN_CHANGED', 'approval request differs from the resolved plan');
    const snap = this.snapshot(plan);
    if (snap.fingerprint !== this.resolved.snap.fingerprint) fail('PLAN_CHANGED', 'files changed since the plan was resolved');
    // Everything shown in the dialog is what gets enforced: one source of truth.
    const breakpoints = (Array.isArray(raw.breakpoints) ? raw.breakpoints : [])
      .map((b) => ({ file: String(b.file), line: Number(b.line) }));
    if (!breakpoints.length || breakpoints.some((b) => !Number.isInteger(b.line) || b.line < 1)
        || breakpoints.some((b) => !plan.files.includes(b.file))) {
      fail('PLAN_CHANGED', 'breakpoints must be positive lines in the resolved files');
    }
    const maxSteps = Number(raw.max_steps);
    if (!Number.isInteger(maxSteps) || maxSteps < 1) fail('POLICY_LIMIT', 'max_steps must be a positive integer');
    const requestId = crypto.randomBytes(8).toString('hex');
    const request = {
      status: 'pending', caseId: String(args.case_id), digest: String(args.digest), plan, snap, breakpoints, maxSteps,
      reportToWorkspace: raw.report_to_workspace === true,
      seconds: Math.max(1, Math.min(Number(args.expires_in_seconds) || 600, 3600)),
    };
    this.requests.set(requestId, request);
    this.log(`approval requested for case ${request.caseId} (digest ${request.digest.slice(0, 12)})`);
    const timer = setTimeout(() => { if (request.status === 'pending') request.status = 'expired'; }, DIALOG_SECONDS * 1000);
    if (timer.unref) timer.unref();
    Promise.resolve(this.vscode.window.showWarningMessage(
      `AutoDebug wants to debug "${plan.launch_configuration_name}" for case ${request.caseId}`,
      { modal: true, detail: this.describePlan(request) }, 'Approve', 'Deny',
    )).then((choice) => {
      clearTimeout(timer);
      if (request.status !== 'pending') return; // answered too late: stays expired
      if (choice === 'Approve') {
        request.status = 'approved';
        request.approvalId = crypto.randomBytes(16).toString('hex');
        request.expiresAt = this.now() + request.seconds * 1000;
        this.log(`developer approved case ${request.caseId}`);
      } else {
        request.status = 'denied';
        this.log(`developer denied case ${request.caseId}`);
      }
    }, () => { request.status = 'denied'; });
    return { request_id: requestId };
  }

  approvalStatus(args) {
    const request = this.requests.get(String(args.request_id));
    if (!request) fail('NOT_APPROVED', 'unknown approval request');
    if (request.status === 'approved' && !this.active) {
      this.active = { ...request, stepsTaken: 0, build: null, session: null, added: [], dapId: null };
      const timer = setTimeout(() => this.end('the approval expired'), request.seconds * 1000);
      if (timer.unref) timer.unref();
      this.active.timer = timer;
    }
    return request.status === 'approved' ? { status: 'approved', approval_id: request.approvalId } : { status: request.status };
  }

  async requireApproval(approvalId, op) {
    const active = this.active;
    if (!active || typeof approvalId !== 'string' || approvalId !== active.approvalId) {
      fail('NOT_APPROVED', 'no approval from the developer covers this operation');
    }
    if (this.now() >= active.expiresAt) {
      await this.end('the approval expired');
      fail('APPROVAL_EXPIRED', 'the approval expired; ask the developer again');
    }
    if (op === 'end') return;
    const snap = this.snapshot(active.plan);
    if (snap.fingerprint !== active.snap.fingerprint) {
      await this.end('the launch configuration, build task or a breakpoint file changed');
      fail('PLAN_CHANGED', 'the launch configuration, build task or a breakpoint file changed after approval');
    }
  }

  // -- build (BR-05) -----------------------------------------------------------

  async buildStart() {
    const active = this.active;
    if (!active.snap.task) fail('CAPABILITY_UNSUPPORTED', 'the plan has no build task');
    if (active.build) fail('POLICY_LIMIT', 'the build already ran');
    const all = await this.vscode.tasks.fetchTasks();
    const task = all.find((t) => t.name === active.snap.task.label
      && t.scope && t.scope.uri && sameFolder(t.scope.uri.fsPath, active.plan.workspace_folder, this.platform));
    if (!task) fail('TARGET_MISMATCH', `build task "${active.snap.task.label}" is not available`);
    active.build = { status: 'running', exitCode: null, execution: null };
    active.build.execution = await this.vscode.tasks.executeTask(task);
    this.log(`build task "${task.name}" started`);
    return { status: 'running' };
  }

  taskEnded(event) {
    const build = this.active && this.active.build;
    if (!build || event.execution !== build.execution) return;
    build.exitCode = typeof event.exitCode === 'number' ? event.exitCode : null;
    build.status = build.exitCode === 0 ? 'succeeded' : 'failed';
    this.log(`build finished with exit code ${build.exitCode}`);
  }

  buildStatus() {
    const build = this.active.build;
    if (!build) fail('NOT_APPROVED', 'the build has not started');
    // The task's output stays in the IDE's terminal; the extension API cannot read it.
    const tail = build.status === 'failed' ? ['see the task output in the IDE terminal'] : [];
    return { status: build.status, exit_code: build.exitCode, output_tail: tail };
  }

  // -- launch and breakpoints (BR-06) -----------------------------------------

  tracker(session) {
    const state = { session, stop: null, ended: false, pid: null, executable: null, verified: new Map(), pending: new Map(),
      stopCount: 0, waiters: [] };
    this.dap.set(session.id, state);
    const notify = () => { const waiters = state.waiters; state.waiters = []; waiters.forEach((w) => w()); };
    return {
      onWillReceiveMessage: (m) => {
        if (m && m.type === 'request' && m.command === 'setBreakpoints' && m.arguments && m.arguments.source) {
          state.pending.set(m.seq, { file: m.arguments.source.path, lines: (m.arguments.breakpoints || []).map((b) => b.line) });
        }
      },
      onDidSendMessage: (m) => {
        if (!m) return;
        if (m.type === 'response' && m.command === 'setBreakpoints' && state.pending.has(m.request_seq)) {
          const sent = state.pending.get(m.request_seq);
          state.pending.delete(m.request_seq);
          ((m.body && m.body.breakpoints) || []).forEach((bp, i) => {
            state.verified.set(`${this.key(sent.file)}:${sent.lines[i]}`, { bound: bp.verified === true, line: bp.line, message: bp.message || '' });
          });
          notify();
        } else if (m.type === 'event' && m.event === 'process') {
          state.pid = typeof m.body.systemProcessId === 'number' ? m.body.systemProcessId : 0;
          state.executable = path.basename(String(m.body.name || ''));
          notify();
        } else if (m.type === 'event' && m.event === 'stopped') {
          state.stopCount += 1;
          state.stop = { id: `stop-${state.stopCount}`, reason: m.body.reason, threadId: m.body.threadId, frame: null };
          notify();
        } else if (m.type === 'event' && m.event === 'continued') {
          state.stop = null;
        } else if (m.type === 'event' && (m.event === 'terminated' || m.event === 'exited')) {
          state.ended = true;
          state.stop = null;
          notify();
        }
      },
      onExit: () => { state.ended = true; notify(); },
    };
  }

  key(file) { return this.platform === 'win32' ? String(file).toLowerCase() : String(file); }

  wait(state, condition, ms) {
    if (condition()) return Promise.resolve(true);
    return new Promise((resolve) => {
      const timer = setTimeout(() => resolve(condition()), ms);
      const check = () => { if (condition()) { clearTimeout(timer); resolve(true); } else state.waiters.push(check); };
      state.waiters.push(check);
    });
  }

  sessionStarted(session) {
    const active = this.active;
    if (active && active.launching && !active.dapId && session.configuration && session.configuration.name === active.snap.launch.name) {
      active.dapId = session.id;
      active.session = session;
    }
  }

  sessionEnded(session) {
    const state = this.dap.get(session.id);
    if (state) { state.ended = true; state.stop = null; state.waiters.splice(0).forEach((w) => w()); }
  }

  async launch() {
    const active = this.active;
    if (active.snap.task && (!active.build || active.build.status !== 'succeeded')) fail('NOT_APPROVED', 'the build has not succeeded');
    if (active.session) fail('POLICY_LIMIT', 'this case already launched');
    const vs = this.vscode;
    active.added = active.breakpoints.map((bp) => new vs.SourceBreakpoint(
      new vs.Location(vs.Uri.file(this.insideFile(active.snap.folder, bp.file)), new vs.Position(bp.line - 1, 0)), true));
    vs.debug.addBreakpoints(active.added);
    active.launching = true;
    let started;
    try {
      started = await vs.debug.startDebugging(active.snap.folder, active.snap.launch.name);
    } finally {
      active.launching = false;
    }
    if (started && !active.session) {
      // onDidStartDebugSession normally fires first; allow it a moment.
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    if (!started || !active.session) fail('BACKEND_UNAVAILABLE', `"${active.snap.launch.name}" did not start; check the Debug Console`);
    const state = this.dap.get(active.dapId);
    await this.wait(state, () => state.pid !== null || state.ended, 4000);
    this.log(`launched "${active.snap.launch.name}" (pid ${state.pid || 'unknown'})`);
    return {
      debug_session_id: active.dapId, pid: state.pid || 0,
      process_start_id: `${active.dapId}-${crypto.randomBytes(4).toString('hex')}`, executable: state.executable || '',
    };
  }

  current() {
    const active = this.active;
    const state = active && active.dapId ? this.dap.get(active.dapId) : null;
    if (!state) fail('NOT_PAUSED', 'nothing has been launched');
    return state;
  }

  async breakpoints() {
    const active = this.active;
    const state = this.current();
    const wanted = active.breakpoints.map((bp) => `${this.key(this.insideFile(active.snap.folder, bp.file))}:${bp.line}`);
    await this.wait(state, () => wanted.every((k) => state.verified.has(k)) || state.ended, 3000);
    return {
      results: active.breakpoints.map((bp, i) => {
        const info = state.verified.get(wanted[i]);
        return { file: bp.file, line: bp.line, bound: Boolean(info && info.bound),
          message: info ? info.message : 'the debugger has not confirmed this breakpoint' };
      }),
    };
  }

  relative(file) {
    const root = this.active.snap.folder.uri.fsPath;
    if (!file) return '';
    const rel = path.relative(root, file);
    return rel && !rel.startsWith('..') && !path.isAbsolute(rel) ? rel.split(path.sep).join('/') : `(outside workspace) ${path.basename(file)}`;
  }

  async topFrame(state) {
    if (!state.stop.frame) {
      const response = await state.session.customRequest('stackTrace', { threadId: state.stop.threadId, startFrame: 0, levels: 1 });
      const frame = (response && response.stackFrames && response.stackFrames[0]) || {};
      state.stop.frame = { file: this.relative(frame.source && frame.source.path), line: frame.line };
    }
    return state.stop.frame;
  }

  async stopState() {
    const state = this.current();
    if (state.ended) return { state: 'ended' };
    if (!state.stop) return { state: 'running' };
    const frame = await this.topFrame(state);
    const planned = state.stop.reason === 'breakpoint'
      ? this.active.breakpoints.find((bp) => bp.file.replace(/\\/g, '/') === frame.file && bp.line === frame.line) : undefined;
    return {
      state: 'paused', stop_id: state.stop.id, reason: state.stop.reason, generation: state.stopCount,
      location: frame, planned_breakpoint: planned ? { file: planned.file, line: planned.line } : null,
    };
  }

  paused() {
    const state = this.current();
    if (state.ended || !state.stop) fail('NOT_PAUSED', 'the program is not paused');
    return state;
  }

  // -- inspection and stepping (BR-07) ------------------------------------------

  async stack(args) {
    const state = this.paused();
    const levels = Math.max(1, Math.min(Number(args.levels) || 20, 50));
    const response = await state.session.customRequest('stackTrace', { threadId: state.stop.threadId, startFrame: 0, levels });
    return {
      frames: ((response && response.stackFrames) || []).slice(0, levels).map((f) => ({
        frame: String(f.id), name: String(f.name), file: this.relative(f.source && f.source.path), line: f.line,
      })),
    };
  }

  async variables(args) {
    const state = this.paused();
    const frameId = Number(args.frame_id);
    if (!Number.isInteger(frameId)) fail('POLICY_LIMIT', 'frame_id must come from autodebug_get_stack');
    const scopes = await state.session.customRequest('scopes', { frameId });
    const found = new Map();
    for (const scope of (scopes && scopes.scopes) || []) {
      if (scope.expensive || !scope.variablesReference) continue;
      const response = await state.session.customRequest('variables', { variablesReference: scope.variablesReference });
      for (const v of ((response && response.variables) || []).slice(0, 200)) {
        if (!found.has(v.name)) found.set(v.name, v);
      }
    }
    if (args.names === null || args.names === undefined) {
      return { names: [...found.values()].map((v) => ({ name: v.name, type: v.type || '' })) };
    }
    const values = {};
    for (const name of [].concat(args.names).map(String)) {
      if (found.has(name)) values[name] = String(found.get(name).value);
    }
    return { variables: values };
  }

  async step(args) {
    const active = this.active;
    const state = this.paused();
    if (!STEP_KINDS.has(args.kind)) fail('CAPABILITY_UNSUPPORTED', 'step kind must be next, stepIn or stepOut');
    if (active.stepsTaken >= active.maxSteps) fail('POLICY_LIMIT', 'the approved step budget is used up');
    const threadId = state.stop.threadId;
    const before = state.stopCount;
    state.stop = null;
    active.stepsTaken += 1;
    await state.session.customRequest(args.kind, { threadId });
    await this.wait(state, () => state.stopCount > before || state.ended, 3000);
    return {};
  }

  async continue() {
    const state = this.paused();
    const threadId = state.stop.threadId;
    state.stop = null;
    await state.session.customRequest('continue', { threadId });
    return {};
  }

  // -- ending (BR-08) -------------------------------------------------------------

  async end(reason) {
    const active = this.active;
    if (!active) return {};
    this.active = null;
    clearTimeout(active.timer);
    const request = [...this.requests.values()].find((r) => r.approvalId === active.approvalId);
    if (request) request.status = 'ended';
    try {
      if (active.session) await this.vscode.debug.stopDebugging(active.session);
    } catch (_) { /* already stopped */ }
    if (active.added.length) this.vscode.debug.removeBreakpoints(active.added);
    this.log(`case ${active.caseId} ended: ${reason}`);
    return {};
  }
}

module.exports = { Bridge, BridgeError, defaultBridgesFolder, canonical, sameFolder, PROTOCOL, VERSION };
