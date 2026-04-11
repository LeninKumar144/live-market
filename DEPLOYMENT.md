# Web dashboard — local run & free hosting

The React UI calls a **FastAPI** backend and focuses on **OI** and **hedging** (live polls). Signal rows are still merged on the server for `GET /signals` / hedging logic from (in order): `backend/data/signals.json`, Excel (`SIGNALS_EXCEL_PATH` or `backend/data/signals.xlsx`), and `logs/signals_*.log` — the dashboard does **not** show a static signals table.

---

## Run locally

### 1) Backend (from repo root)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

- API: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- `GET /signals` — latest signals (JSON)
- `GET /history` — paginated history

Optional: copy `backend/data/signals.example.json` → `backend/data/signals.json` to see sample rows without Excel.

### 2) Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Vite proxies `/oi`, `/hedging`, `/health` to port 8000.

### 3) Production-like frontend (pointed at a remote API)

```bash
cd frontend
set VITE_API_URL=https://your-api.example.com
npm run build
npm run preview
```

---

## Excel format (sheet `Signals`)

The backend reads the first sheet named **Signals** (or the first sheet if that name is missing). Supported column names (case-insensitive, spaces ok):

| Column (any of) | Example |
|-----------------|--------|
| Type / SignalType / Kind | `BUY CE`, `BUY PE` |
| Strike / Strike_price | `22800` |
| Reason / Message | Put writing… |
| Timestamp / Time / Datetime | Excel datetime or ISO string |
| Confidence / Conf | `High`, `Medium`, `Low` |

**Tip:** Save as `.xlsx` under `backend/data/signals.xlsx` or set env `SIGNALS_EXCEL_PATH` to an absolute path the API can read.

---

## Deploy backend on Render (free tier)

1. Push this repo to GitHub.
2. Render → **New** → **Web Service** → connect the repo.
3. **Root directory:** `backend`
4. **Build command:** `pip install -r requirements.txt`
5. **Start command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. **Environment variables** (minimum for OI/hedging features; signals-only needs fewer):
   - `UPSTOX_ACCESS_TOKEN` — if you use chain/OI sync
   - `SIGNALS_EXCEL_PATH` — optional path to a persistent volume file if you use Excel on Render
7. Note: free instances **sleep** when idle; first request may be slow.

CORS is permissive by default (`CORS_ORIGINS=*`). For a single known frontend origin you can set:

`CORS_ORIGINS=https://your-app.vercel.app`

---

## Deploy frontend on Vercel (free)

1. Import the GitHub repo in Vercel.
2. **Root directory:** `frontend`
3. **Framework preset:** Vite  
4. **Build command:** `npm run build`  
5. **Output directory:** `dist`
6. **Environment variable:** `VITE_API_URL` = your Render service URL, e.g. `https://nifty-api.onrender.com` (no trailing slash).

`frontend/vercel.json` rewrites SPA routes to `index.html`.

After deploy, open the Vercel URL; the browser will call `VITE_API_URL/oi`, `/hedging`, etc.

---

## Real-time behavior

- The dashboard **polls** `GET /oi/status` and `GET /hedging` on fixed intervals (OI and hedging sections).
- **Signals** (`/signals`, Excel, JSON, logs) still update hedging context on the server when those files change; use the API docs or a client if you need the signal list in the UI again.

---

## Project layout (web)

```
backend/
  main.py              # FastAPI app
  api/routes.py        # /signals, /history, /oi, /hedging, …
  services/signals_source.py
  models/schemas.py
  data/signals.json    # optional native store
frontend/
  src/
    api/client.js      # axios; VITE_API_URL in production
    pages/Home.jsx
  vercel.json
```
