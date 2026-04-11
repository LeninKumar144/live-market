import axios from "axios";

/** Empty baseURL = same-origin; Vite dev server proxies /oi and /hedging to FastAPI. */
const baseURL = import.meta.env.VITE_API_URL?.replace(/\/$/, "") || "";

export const api = axios.create({
  baseURL,
  timeout: 15000,
});
