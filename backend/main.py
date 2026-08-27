"""
FastAPI app for the NIFTY signals dashboard.

Run locally:
  cd backend
  pip install -r requirements.txt
  uvicorn main:app --reload --host 0.0.0.0 --port 8787
  (or `npm run dev` from repo root — default dev API port is 8787; set API_PORT to override)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from services.oi_excel_service import (
    oi_auto_update_enabled,
    oi_update_interval_seconds,
    run_all_oi_excel_cycles,
)

logger = logging.getLogger(__name__)

_origins = os.environ.get("CORS_ORIGINS", "*").strip()
allow_origins = [o.strip() for o in _origins.split(",") if o.strip()] if _origins != "*" else ["*"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if oi_auto_update_enabled():
        async def _oi_loop() -> None:
            await asyncio.sleep(2)
            while True:
                try:
                    await asyncio.to_thread(run_all_oi_excel_cycles)
                except Exception:
                    logger.exception("Background OI Excel update failed")
                await asyncio.sleep(oi_update_interval_seconds())

        task = asyncio.create_task(_oi_loop())
    yield
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="NIFTY Signals API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/")
def root() -> dict:
    return {
        "service": "nifty-signals-api",
        "docs": "/docs",
        "signals": "/signals",
        "history": "/history",
        "segments": "/segments",
        "oi_status": "/oi/{segment}/status (alias: /oi/status → nifty)",
        "oi_refresh": "POST /oi/{segment}/refresh",
        "oi_future_chart": "/oi/{segment}/future-chart",
        "hedging": "/hedging/{segment} (alias: /hedging → nifty)",
        "stock_options_liquidity": "/stock-options/liquidity (NSE F&O liquidity guide)",
        "stock_options_live": "/stock-options/live (live CE/PE + OI, Upstox)",
    }
