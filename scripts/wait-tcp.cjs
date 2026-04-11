"use strict";

/** Wait until something accepts TCP connections on host:port (same default as dev API). */
const net = require("net");
const { loadRootEnv } = require("./load-root-env.cjs");
const { DEFAULT_DEV_API_PORT } = require("./dev-api-port.cjs");
loadRootEnv();

const host = process.env.WAIT_TCP_HOST || "127.0.0.1";
const port = Number(
  process.argv[2] ||
    process.env.WAIT_TCP_PORT ||
    process.env.API_PORT ||
    process.env.VITE_API_PORT ||
    DEFAULT_DEV_API_PORT,
);
const timeoutMs = Number(process.env.WAIT_TCP_TIMEOUT_MS || 120_000);
const deadline = Date.now() + timeoutMs;
const pollMs = 300;

function tryConnect() {
  return new Promise((resolve, reject) => {
    const s = net.createConnection({ port, host }, () => {
      s.destroy();
      resolve();
    });
    s.on("error", () => reject());
  });
}

async function main() {
  while (Date.now() < deadline) {
    try {
      await tryConnect();
      process.exit(0);
    } catch {
      await new Promise((r) => setTimeout(r, pollMs));
    }
  }
  console.error(
    `[wait-tcp] Timed out after ${timeoutMs}ms waiting for ${host}:${port} (API not listening).`,
  );
  process.exit(1);
}

main();
