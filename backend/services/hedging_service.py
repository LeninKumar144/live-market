"""Build hedging recommendations from OI cache + merged signals (project-root analysis)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.hedging_engine import build_hedging_payload
from analysis.strategy_pnl import enrich_hedging_payload, nifty_option_lot_size

from services.oi_excel_service import get_oi_cache_snapshot
from services.signals_source import load_all_signals


def _strike_step() -> int:
    try:
        import yaml

        p = PROJECT_ROOT / "config" / "analysis.yaml"
        if not p.is_file():
            return 50
        with p.open(encoding="utf-8") as f:
            y = yaml.safe_load(f) or {}
        return int(y.get("strike_step", 50))
    except Exception:
        return 50


def get_hedging_response() -> dict[str, Any]:
    oi = get_oi_cache_snapshot()
    rows, _src = load_all_signals()
    recent_types = [str(r.get("type") or "") for r in rows[:25]]

    spot = float(oi.get("spot") or 0.0)
    pcr = oi.get("pcr")
    mdir = str(oi.get("market_direction") or "flat")
    dpc = oi.get("market_delta_pct")
    if dpc is not None:
        try:
            dpc = float(dpc)
        except (TypeError, ValueError):
            dpc = None

    expiry = str(oi.get("expiry") or "")

    raw = build_hedging_payload(
        spot=spot,
        strike_step=_strike_step(),
        pcr=float(pcr) if pcr is not None else None,
        market_direction=mdir,
        market_delta_pct=dpc,
        signal_types=recent_types,
        chain_expiry=expiry or None,
        diagonal_long_expiry_display=str(oi.get("diagonal_long_expiry_display") or ""),
        diagonal_short_expiry_display=str(oi.get("diagonal_short_expiry_display") or ""),
        diagonal_long_expiry_iso=str(oi.get("diagonal_long_expiry_iso") or ""),
        diagonal_short_expiry_iso=str(oi.get("diagonal_short_expiry_iso") or ""),
    )
    chain = oi.get("chain_ltp")
    if not isinstance(chain, dict):
        chain = {}
    step = _strike_step()
    return enrich_hedging_payload(
        raw,
        chain,
        nifty_option_lot_size(),
        strike_step=step,
        spot=spot,
    )
