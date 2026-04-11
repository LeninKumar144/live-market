# NIFTY signals web dashboard

FastAPI backend + React (Vite) frontend. Reads signals from:

1. **`backend/data/signals.json`** — append/update from any process (recommended).
2. **`backend/data/signals.xlsx`** — sheet **`Signals`** (see below), or set `SIGNALS_EXCEL_PATH`.
3. **`logs/signals_*.jsonl`** in the project root — same format as the Python analyzer (`SignalLogger`).

Sources are **merged**, de-duplicated, sorted **newest first**.

---

## Run locally

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- API docs: http://127.0.0.1:8000/docs  
- `GET http://127.0.0.1:8000/signals?limit=50`  
- `GET http://127.0.0.1:8000/history?page=1&page_size=100`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173 — Vite proxies `/signals`, `/history`, `/health` to port **8000**.

### Environment (backend)

| Variable | Purpose |
|----------|---------|
| `CORS_ORIGINS` | Comma-separated allowed origins (default `*`). Set to your Vercel URL in production. |
| `SIGNALS_EXCEL_PATH` | Full path to an Excel file (overrides default `backend/data/signals.xlsx`). |
| `SIGNALS_LOG_DIR` | Directory containing `signals_*.log` (default: `<project>/logs`). |

### Environment (frontend)

| Variable | Purpose |
|----------|---------|
| `VITE_API_URL` | Base URL of the API for **production** builds (e.g. `https://xxx.onrender.com`). Leave empty for local dev with proxy. |

---

## Excel format (`signals.xlsx`)

Sheet name: **`Signals`** (or the first sheet if missing).

| Column (flexible names) | Example |
|-------------------------|---------|
| Timestamp / timestamp_iso / datetime | `2026-03-27T10:32:00+05:30` |
| SignalType / type / kind | `BUY CE` |
| Strike / strike_price | `22800` |
| Reason | `Put writing...` |
| Confidence (optional) | `High` |

Column matching is **case-insensitive**; spaces → underscores internally.

---

## JSON format (`signals.json`)

Array of objects:

```json
[
  {
    "id": "optional",
    "type": "BUY CE",
    "strike": 22800,
    "reason": "Put writing detected",
    "timestamp_iso": "2026-03-27T10:32:00+05:30",
    "confidence": "High"
  }
]
```

---

## Deploy backend on Render (free)

1. Push this repo to GitHub.
2. [Render](https://render.com) → **New +** → **Web Service** → connect repo.
3. **Root Directory:** leave blank (repo root), or set to `backend` and adjust commands — see `DEPLOYMENT.md`.
4. **Build Command:** `pip install -r backend/requirements.txt` (from repo root).
5. **Start Command:** `python -m uvicorn render_api:app --host 0.0.0.0 --port $PORT` (from repo root; avoids loading the wrong `main.py`). If Root Directory is `backend`, use `python -m uvicorn main:app ...` instead.
6. **Environment** → add `CORS_ORIGINS=https://your-frontend.vercel.app`
7. Deploy. Note the service URL, e.g. `https://nifty-signals-api.onrender.com`.

**Note:** Free tier sleeps when idle; first request may be slow. For always-on data, use a paid plan or accept cold starts.

**Persisting data:** Render’s filesystem is ephemeral. For production, prefer writing signals to **S3**, a **database**, or redeploy with `signals.json` in the image — or run the analyzer elsewhere and `POST` to your API (future enhancement).

---

## Deploy frontend on Vercel (free)

1. [Vercel](https://vercel.com) → **Add New** → **Project** → import the same repo.
2. **Root Directory:** `frontend`
3. **Framework Preset:** Vite  
4. **Build Command:** `npm run build`  
5. **Output Directory:** `dist`
6. **Environment Variables:** `VITE_API_URL` = your Render API URL (no trailing slash).
7. Deploy.

Open the Vercel URL; the app will call the Render API (ensure `CORS_ORIGINS` includes your Vercel domain).

---

## Wiring the Python analyzer

Your existing logger already writes **`logs/signals_YYYY-MM-DD.log`** (JSON lines). The backend reads that directory by default (`SIGNALS_LOG_DIR`).

Optionally duplicate each alert into `backend/data/signals.json` for a single file you control — or mount/sync `logs/` on the server if you co-locate backend and analyzer.

---

## API summary

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/signals?limit=50` | Latest signals |
| GET | `/history?page=1&page_size=100` | Paginated history |
| GET | `/docs` | Swagger UI |
