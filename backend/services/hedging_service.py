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


def get_hedging_response(segment: str = "nifty") -> dict[str, Any]:
    from config.segments import get_segment
    from services.signals_source import load_all_signals

    sid = (segment or "nifty").strip().lower()
    try:
        seg = get_segment(sid)
        strike_step = int(seg.strike_step)
        lot_size = int(seg.option_lot_size)
    except KeyError:
        strike_step = 50
        lot_size = nifty_option_lot_size()

    oi = get_oi_cache_snapshot(sid)
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
        strike_step=strike_step,
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
    return enrich_hedging_payload(
        raw,
        chain,
        lot_size,
        strike_step=strike_step,
        spot=spot,
    )
