#!/usr/bin/env node
"use strict";

/* npx launcher for the whsearch MCP server.
 *
 * The server itself is Python. This script only:
 *   1. finds a Python >= 3.12 (WHSEARCH_PY or python3/python on PATH),
 *   2. ensures the `whsearch[mcp]` backend is importable
 *      (WHSEARCH_DEV_PATH points at a checkout for local dev,
 *      otherwise pip-installs WHSEARCH_PACKAGE, default pinned release),
 *   3. execs the server with stdio inherited for MCP communication.
 */

const { spawn, spawnSync } = require("node:child_process");
const path = require("node:path");

const BACKEND_VERSION = "0.1.0";
const MIN_PYTHON = [3, 12];

function fail(message) {
  process.stderr.write(`whsearch: ${message}\n`);
  process.exit(1);
}

function tryPython(exe) {
  const probed = spawnSync(exe, ["-c", "import sys; print(sys.version)"], { encoding: "utf8" });
  if (probed.status !== 0) return null;
  const match = /(\d+)\.(\d+)\.(\d+)/.exec(probed.stdout || "");
  if (!match) return null;
  const version = [Number(match[1]), Number(match[2])];
  if (version[0] < MIN_PYTHON[0] || (version[0] === MIN_PYTHON[0] && version[1] < MIN_PYTHON[1])) {
    fail(`found ${exe} with Python ${match[0]} but >= 3.12 is required`);
  }
  return exe;
}

function findPython() {
  if (process.env.WHSEARCH_PY) {
    const exe = tryPython(process.env.WHSEARCH_PY);
    if (!exe) fail(`WHSEARCH_PY=${process.env.WHSEARCH_PY} is not a working Python`);
    return exe;
  }
  for (const candidate of ["python3", "python"]) {
    const exe = tryPython(candidate);
    if (exe) return exe;
  }
  fail("no Python >= 3.12 found (set WHSEARCH_PY to override)");
  return "";
}

function backendEnv(python) {
  const env = { ...process.env };
  const devPath = process.env.WHSEARCH_DEV_PATH;
  if (devPath) {
    const srcDir = path.join(devPath, "src");
    env.PYTHONPATH = env.PYTHONPATH ? `${srcDir}${path.delimiter}${env.PYTHONPATH}` : srcDir;
  }
  return env;
}

function backendAvailable(python, env) {
  const check = spawnSync(python, ["-c", "import whsearch, mcp"], { env });
  return check.status === 0;
}

function installBackend(python, env) {
  const spec = process.env.WHSEARCH_PACKAGE || `whsearch[mcp]==${BACKEND_VERSION}`;
  process.stderr.write(`whsearch: installing backend (${spec})...\n`);
  const install = spawnSync(python, ["-m", "pip", "install", "--quiet", spec], {
    env,
    stdio: "inherit",
  });
  if (install.status !== 0) fail(`pip install failed for ${spec}`);
}

function main() {
  const python = findPython();
  const env = backendEnv(python);
  if (!backendAvailable(python, env)) {
    if (process.env.WHSEARCH_DEV_PATH) {
      fail(`WHSEARCH_DEV_PATH=${process.env.WHSEARCH_DEV_PATH} has no importable backend`);
    }
    installBackend(python, env);
    if (!backendAvailable(python, env)) fail("backend still not importable after install");
  }
  const child = spawn(python, ["-m", "whsearch.mcp.server"], { env, stdio: "inherit" });
  for (const signal of ["SIGINT", "SIGTERM"]) {
    process.on(signal, () => child.kill(signal));
  }
  child.on("exit", (code) => process.exit(code === null ? 1 : code));
  child.on("error", (err) => fail(`failed to start backend: ${err.message}`));
}

main();
