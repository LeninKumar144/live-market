"use strict";

/**
 * Default TCP port for the FastAPI dev server and Vite proxy.
 * Avoid 8000 on Windows: Hyper-V / excluded ranges often cause WinError 10013.
 */
module.exports = { DEFAULT_DEV_API_PORT: 8787 };
