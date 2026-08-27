import { createRequire } from "module";
import path from "path";
import { fileURLToPath } from "url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { DEFAULT_DEV_API_PORT } = require("../scripts/dev-api-port.cjs");

export default defineConfig(({ mode }) => {
  const rootDir = path.join(__dirname, "..");
  const rootEnv = loadEnv(mode, rootDir, "");
  const apiPort =
    process.env.API_PORT ||
    process.env.VITE_API_PORT ||
    rootEnv.API_PORT ||
    rootEnv.VITE_API_PORT ||
    String(DEFAULT_DEV_API_PORT);
  const apiTarget = `http://127.0.0.1:${apiPort}`;

  return {
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/health": { target: apiTarget, changeOrigin: true },
      "/oi": { target: apiTarget, changeOrigin: true },
      "/hedging": { target: apiTarget, changeOrigin: true },
      "/segments": { target: apiTarget, changeOrigin: true },
      "/stock-options": { target: apiTarget, changeOrigin: true },
    },
  },
};
});
