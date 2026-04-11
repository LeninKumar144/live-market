"use strict";

/**
 * Start FastAPI (uvicorn) from backend/ with a Python that has deps installed.
 * Honors PYTHON (full path or launcher name) when set.
 */
const { spawn } = require("child_process");
const path = require("path");
const { loadRootEnv } = require("./load-root-env.cjs");
const { DEFAULT_DEV_API_PORT } = require("./dev-api-port.cjs");
loadRootEnv();

const backendDir = path.join(__dirname, "..", "backend");
const apiPort = String(
  process.env.API_PORT || process.env.VITE_API_PORT || DEFAULT_DEV_API_PORT,
);
const uvicornArgs = [
  "-m",
  "uvicorn",
  "main:app",
  "--reload",
  "--host",
  "127.0.0.1",
  "--port",
  apiPort,
];

const fromEnv = process.env.PYTHON && process.env.PYTHON.trim();
const candidates = fromEnv
  ? [[fromEnv, uvicornArgs]]
  : process.platform === "win32"
    ? [
        ["py", ["-3", ...uvicornArgs]],
        ["python", uvicornArgs],
      ]
    : [
        ["python3", uvicornArgs],
        ["python", uvicornArgs],
      ];

function run(index) {
  if (index >= candidates.length) {
    console.error(
      "[dev:api] Could not start API: no working Python. Install Python 3, then:\n" +
        "  cd backend && pip install -r requirements.txt\n" +
        "Or set PYTHON to your interpreter (e.g. .venv\\Scripts\\python.exe).",
    );
    process.exit(1);
  }
  const [cmd, args] = candidates[index];
  const child = spawn(cmd, args, {
    cwd: backendDir,
    stdio: "inherit",
    env: process.env,
    windowsHide: true,
  });
  child.on("error", (err) => {
    if (err && err.code === "ENOENT") {
      run(index + 1);
      return;
    }
    console.error(err);
    process.exit(1);
  });
  child.on("exit", (code, signal) => {
    if (signal) {
      process.exit(1);
    }
    if (code !== 0 && code !== null) {
      process.exit(code);
    }
  });
}

run(0);
