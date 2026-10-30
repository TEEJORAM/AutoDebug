'use strict';
// Registers the `autodebug` MCP server with the IDE itself, so the agent gets the tools without an
// mcp.json entry. `autodebug setup` writes <state folder>/server.json: how to start the server
// ({command, args, env}). Cursor: vscode.cursor.mcp.registerServer. VS Code 1.101+:
// vscode.lm.registerMcpServerDefinitionProvider. A window whose mcp.json files already name
// `autodebug` is left alone, so the agent never sees the tools twice.
const fs = require('fs');
const os = require('os');
const path = require('path');

const NAME = 'autodebug';
const PROVIDER = 'autodebug.server'; // contributes.mcpServerDefinitionProviders in package.json

function readJson(file) {
  try {
    const text = fs.readFileSync(file, 'utf8').replace(/^﻿/, '');
    return JSON.parse(text);
  } catch (_) {
    return undefined;
  }
}

/** The server.json written by setup, or undefined (with the reason logged) when it is missing or wrong. */
function serverConfig(stateFolder, log) {
  const file = path.join(stateFolder, 'server.json');
  const data = readJson(file);
  if (!data) {
    log(`MCP: no ${file}; run \`autodebug setup\` to let this window register the autodebug server`);
    return undefined;
  }
  const env = data.env && typeof data.env === 'object' ? data.env : {};
  if (typeof data.command !== 'string' || !Array.isArray(data.args) || !data.args.every((a) => typeof a === 'string')) {
    log(`MCP: ${file} has no command and args; run \`autodebug setup\` again`);
    return undefined;
  }
  return { command: data.command, args: data.args, env, version: String(data.version || '') };
}

/** Every mcp.json this IDE reads for the open folders, with the key that holds its servers. */
function configFiles(ide, folders, userDir, home = os.homedir()) {
  const files = [];
  if (ide === 'cursor') {
    files.push([path.join(home, '.cursor', 'mcp.json'), 'mcpServers']);
    for (const f of folders) files.push([path.join(f, '.cursor', 'mcp.json'), 'mcpServers']);
  } else {
    if (userDir) files.push([path.join(userDir, 'mcp.json'), 'servers']);
    for (const f of folders) {
      files.push([path.join(f, '.vscode', 'mcp.json'), 'servers']);
      files.push([path.join(f, '.mcp.json'), 'mcpServers']);
    }
  }
  return files;
}

function configuredElsewhere(files) {
  return files.find(([file, key]) => {
    const data = readJson(file);
    return Boolean(data && data[key] && typeof data[key] === 'object' && data[key][NAME]);
  });
}

/**
 * Register the server for this window. Returns what happened, for the log and the tests:
 * 'cursor', 'vscode', 'configured' (an mcp.json already has it), 'no-config' or 'unsupported'.
 */
function register(vscode, context, { stateFolder, log, home = os.homedir() }) {
  const isCursor = Boolean(vscode.cursor && vscode.cursor.mcp && typeof vscode.cursor.mcp.registerServer === 'function');
  const hasProvider = Boolean(vscode.lm && typeof vscode.lm.registerMcpServerDefinitionProvider === 'function'
    && typeof vscode.McpStdioServerDefinition === 'function');
  if (!isCursor && !hasProvider) {
    log('MCP: this IDE has no API to register MCP servers; use `autodebug setup` (it writes mcp.json)');
    return 'unsupported';
  }
  const folders = (vscode.workspace.workspaceFolders || []).map((f) => f.uri.fsPath);
  const userDir = context.globalStorageUri ? path.dirname(path.dirname(context.globalStorageUri.fsPath)) : undefined;
  const found = configuredElsewhere(configFiles(isCursor ? 'cursor' : 'vscode', folders, userDir, home));
  if (found) {
    log(`MCP: ${found[0]} already starts autodebug; not registering it a second time`);
    return 'configured';
  }
  const server = serverConfig(stateFolder, log);
  if (!server) return 'no-config';
  if (isCursor) {
    vscode.cursor.mcp.registerServer({ name: NAME, server: { command: server.command, args: server.args, env: server.env } });
    context.subscriptions.push({ dispose: () => { try { vscode.cursor.mcp.unregisterServer(NAME); } catch (_) { /* window closing */ } } });
    log(`MCP: registered autodebug with Cursor (${server.command})`);
    return 'cursor';
  }
  const definition = new vscode.McpStdioServerDefinition('Autodebug', server.command, server.args, server.env, server.version);
  context.subscriptions.push(vscode.lm.registerMcpServerDefinitionProvider(PROVIDER, {
    provideMcpServerDefinitions: () => [definition],
    resolveMcpServerDefinition: (d) => d,
  }));
  log(`MCP: registered autodebug with VS Code (${server.command})`);
  return 'vscode';
}

module.exports = { register, configFiles, serverConfig, NAME, PROVIDER };
