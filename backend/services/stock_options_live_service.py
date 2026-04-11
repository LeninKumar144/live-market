"""
Live NSE stock option chains via Upstox: suggested BUY CE/PE, total OI, OI changes.

Caches full snapshot ~55s to limit API load. Poll deltas (since last successful refresh) are
computed server-side; session vs prev_close comes from exchange prev_oi fields.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from zoneinfo import ZoneInfo

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.market_move import compute_market_move
from analysis.signal_engine import _placement_for_signal
from config.settings import get_settings, load_analysis_parameters
from data.models import StrikeRow, StrikeSnapshot
from data.upstox_client import UpstoxAPIError, UpstoxClient
from utils.helpers import resolve_execution_strike
from services.stock_options_liquidity import liquidity_stock_metas_ordered

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_service_lock = threading.Lock()
_cached_at: float | None = None
_cached_payload: dict[str, Any] | None = None

_equity_ik_cache: dict[str, str] = {}
_last_chain_totals: dict[str, tuple[int, int]] = {}
_last_leg_oi: dict[str, int] = {}
_histories: dict[str, deque[StrikeSnapshot]] = defaultdict(lambda: deque(maxlen=32))

CACHE_TTL_SECONDS = 55.0


def _infer_strike_step(rows: list[StrikeRow]) -> int:
    strikes = sorted({float(r.strike_price) for r in rows})
    if len(strikes) < 2:
        return 50
    diffs: list[int] = []
    for i in range(len(strikes) - 1):
        d = strikes[i + 1] - strikes[i]
        if d <= 0:
            continue
        rd = int(round(d))
        if rd > 0:
            diffs.append(rd)
    step = min(diffs) if diffs else 50
    return max(1, step)


def _adaptive_flat_threshold(spot: float, base_pts: float) -> float:
    s = abs(float(spot))
    return max(float(base_pts), s * 0.0002)


def _leg_key(symbol: str, side: str, strike: float) -> str:
    return f"{symbol}|{side}|{int(round(float(strike)))}"


def _leg_delta_since_last(symbol: str, side: str, strike: float, oi: int) -> int | None:
    k = _leg_key(symbol, side, strike)
    prev = _last_leg_oi.get(k)
    _last_leg_oi[k] = int(oi)
    if prev is None:
        return None
    return int(oi) - int(prev)


def _chain_delta_since_last(symbol: str, ce_sum: int, pe_sum: int) -> tuple[int | None, int | None]:
    prev = _last_chain_totals.get(symbol)
    _last_chain_totals[symbol] = (int(ce_sum), int(pe_sum))
    if prev is None:
        return None, None
    pce, ppe = prev
    return int(ce_sum) - int(pce), int(pe_sum) - int(ppe)


def _build_leg_payload(
    symbol: str,
    side: str,
    strike: float,
    ltp: float,
    row: StrikeRow | None,
    execution_note: str,
) -> dict[str, Any]:
    if row is None:
        return {
            "strike": float(strike),
            "ltp": float(ltp),
            "open_interest": 0,
            "volume": 0,
            "prev_oi": 0,
            "oi_change_vs_prev_close": 0,
            "oi_change_since_last_poll": None,
            "instrument_key": "",
            "execution_note": execution_note,
            "required_margin_inr": None,
            "margin_source": "",
            "premium_estimate_inr": None,
        }
    leg = row.call if side == "CE" else row.put
    oi_ch_pc = int(leg.oi) - int(leg.prev_oi)
    oi_ch_poll = _leg_delta_since_last(symbol, side, strike, int(leg.oi))
    return {
        "strike": float(strike),
        "ltp": float(leg.ltp),
        "open_interest": int(leg.oi),
        "volume": int(leg.volume),
        "prev_oi": int(leg.prev_oi),
        "oi_change_vs_prev_close": oi_ch_pc,
        "oi_change_since_last_poll": oi_ch_poll,
        "instrument_key": str(leg.instrument_key or ""),
        "execution_note": execution_note,
        "required_margin_inr": None,
        "margin_source": "",
        "premium_estimate_inr": None,
    }


def _premium_times_lot(ltp: float, lot: int) -> float:
    return round(max(0.0, float(ltp)) * max(1, int(lot)), 2)


def _margin_total_from_row(m: dict[str, Any]) -> float | None:
    for k in ("total_margin", "required_margin", "final_margin"):
        v = m.get(k)
        if v is None:
            continue
        try:
            x = float(v)
            if x >= 0:
                return x
        except (TypeError, ValueError):
            continue
    return None


def _attach_lot_and_margins(client: UpstoxClient, base: dict[str, Any], underlying_ik: str, expiry: str) -> None:
    """Set option_lot_size and per-leg required_margin_inr (Upstox charges/margin or premium estimate)."""
    if not base.get("ok"):
        base["option_lot_size"] = None
        return

    lot: int | None = None
    try:
        lot = client.fetch_option_lot_size(underlying_ik, expiry)
    except Exception as e:
        logger.debug("option lot_size %s: %s", base.get("symbol"), e)
    base["option_lot_size"] = lot

    ce = base.get("buy_ce")
    pe = base.get("buy_pe")
    if not isinstance(ce, dict):
        ce = None
    if not isinstance(pe, dict):
        pe = None

    if not lot or lot <= 0:
        for leg in (ce, pe):
            if isinstance(leg, dict):
                leg["premium_estimate_inr"] = None
        return

    instruments: list[dict[str, Any]] = []
    order: list[str] = []
    for side, leg in (("CE", ce), ("PE", pe)):
        if not isinstance(leg, dict):
            continue
        ik = str(leg.get("instrument_key") or "").strip()
        if not ik:
            continue
        body: dict[str, Any] = {
            "instrument_key": ik,
            "quantity": int(lot),
            "transaction_type": "BUY",
            "product": "D",
        }
        px = float(leg.get("ltp") or 0.0)
        if px > 0:
            body["price"] = round(px, 2)
        instruments.append(body)
        order.append(side)

    margin_rows: list[Any] = []
    if instruments:
        try:
            margin_rows = client.post_charges_margin(instruments)
        except Exception as e:
            logger.debug("charges/margin %s: %s", base.get("symbol"), e)

    mi = 0
    for side in order:
        leg = ce if side == "CE" else pe
        if not isinstance(leg, dict):
            continue
        est = _premium_times_lot(float(leg.get("ltp") or 0.0), lot)
        leg["premium_estimate_inr"] = est if est > 0 else None

        api_val: float | None = None
        if mi < len(margin_rows) and isinstance(margin_rows[mi], dict):
            api_val = _margin_total_from_row(margin_rows[mi])
        mi += 1

        if api_val is not None and api_val > 0:
            leg["required_margin_inr"] = round(api_val, 2)
            leg["margin_source"] = "upstox"
        elif est > 0:
            leg["required_margin_inr"] = est
            leg["margin_source"] = "premium_estimate"
        else:
            leg["required_margin_inr"] = None
            leg["margin_source"] = ""


def _process_one_stock(
    client: UpstoxClient,
    params: Any,
    meta: dict[str, Any],
) -> dict[str, Any]:
    symbol = str(meta["symbol"])
    zero_totals = {
        "total_call_oi": 0,
        "total_put_oi": 0,
        "total_call_prev_oi": 0,
        "total_put_prev_oi": 0,
        "call_oi_change_vs_prev_close": 0,
        "put_oi_change_vs_prev_close": 0,
        "call_oi_change_since_last_poll": None,
        "put_oi_change_since_last_poll": None,
        "pcr": None,
    }
    base = {
        "symbol": symbol,
        "name": str(meta.get("name") or ""),
        "sector": str(meta.get("sector") or ""),
        "tier": int(meta.get("tier") or 1),
        "liquidity_score": int(meta.get("liquidity_score") or 0),
        "ok": False,
        "error": None,
        "instrument_key": None,
        "expiry": "",
        "spot": 0.0,
        "strike_step": 50,
        "totals": dict(zero_totals),
        "buy_ce": None,
        "buy_pe": None,
        "market_move": {
            "direction": "flat",
            "delta_points": 0.0,
            "delta_pct": 0.0,
            "n_snapshots": 0,
            "from_spot": 0.0,
            "to_spot": 0.0,
            "label": "",
        },
        "option_lot_size": None,
    }

    try:
        ik = _equity_ik_cache.get(symbol)
        if not ik:
            ik = client.resolve_nse_equity_instrument_key(symbol)
            if not ik:
                base["error"] = "No NSE EQ instrument_key from Upstox search"
                return base
            _equity_ik_cache[symbol] = ik

        expiry = client.resolve_expiry(None, ik)
        rows = client.fetch_option_chain(expiry, ik)
        if not rows:
            base["error"] = "Empty option chain"
            base["instrument_key"] = ik
            return base

        spot = float(rows[0].underlying_spot_price or 0.0)
        if spot <= 0:
            for r in rows:
                v = float(r.underlying_spot_price or 0.0)
                if v > 0:
                    spot = v
                    break
        if spot <= 0:
            base["error"] = "Underlying spot not available in option chain"
            base["instrument_key"] = ik
            return base

        step = _infer_strike_step(rows)
        strikes_map: dict[float, StrikeRow] = {float(r.strike_price): r for r in rows}

        snap = StrikeSnapshot(
            captured_at=datetime.now(IST),
            spot=spot,
            expiry=expiry,
            strikes=strikes_map,
        )
        _histories[symbol].append(snap)

        flat_th = _adaptive_flat_threshold(spot, params.stock_market_move_flat_threshold_points)
        mv = compute_market_move(
            _histories[symbol],
            params.market_move_lookback_snapshots,
            flat_th,
        )
        ce_placement, ce_note = _placement_for_signal(
            params.buy_strike_mode,
            "CE",
            mv,
            flat_th,
        )
        pe_placement, pe_note = _placement_for_signal(
            params.buy_strike_mode,
            "PE",
            mv,
            flat_th,
        )

        min_oi = int(params.stock_option_min_open_interest)
        min_vol = int(params.stock_option_min_volume)
        max_steps = int(params.stock_option_buy_strike_max_steps_from_atm)

        ce_strike, _ce_ltp = resolve_execution_strike(
            strikes_map,
            spot,
            step,
            "CE",
            min_oi,
            min_vol,
            max_steps,
            placement=ce_placement,
            otm_steps=params.otm_strike_steps,
        )
        pe_strike, _pe_ltp = resolve_execution_strike(
            strikes_map,
            spot,
            step,
            "PE",
            min_oi,
            min_vol,
            max_steps,
            placement=pe_placement,
            otm_steps=params.otm_strike_steps,
        )

        ce_row = strikes_map.get(ce_strike)
        pe_row = strikes_map.get(pe_strike)

        t_co = sum(int(r.call.oi) for r in rows)
        t_po = sum(int(r.put.oi) for r in rows)
        t_cprev = sum(int(r.call.prev_oi) for r in rows)
        t_pprev = sum(int(r.put.prev_oi) for r in rows)

        d_ce_poll, d_pe_poll = _chain_delta_since_last(symbol, t_co, t_po)

        pcr = (float(t_po) / float(t_co)) if t_co > 0 else None

        base.update(
            {
                "ok": True,
                "error": None,
                "instrument_key": ik,
                "expiry": expiry,
                "spot": spot,
                "strike_step": step,
                "totals": {
                    "total_call_oi": t_co,
                    "total_put_oi": t_po,
                    "total_call_prev_oi": t_cprev,
                    "total_put_prev_oi": t_pprev,
                    "call_oi_change_vs_prev_close": t_co - t_cprev,
                    "put_oi_change_vs_prev_close": t_po - t_pprev,
                    "call_oi_change_since_last_poll": d_ce_poll,
                    "put_oi_change_since_last_poll": d_pe_poll,
                    "pcr": pcr,
                },
                "buy_ce": _build_leg_payload(symbol, "CE", ce_strike, _ce_ltp, ce_row, ce_note),
                "buy_pe": _build_leg_payload(symbol, "PE", pe_strike, _pe_ltp, pe_row, pe_note),
                "market_move": mv,
            }
        )
        _attach_lot_and_margins(client, base, ik, expiry)
        return base

    except UpstoxAPIError as e:
        base["error"] = str(e)
        logger.warning("Stock option chain %s: %s", symbol, e)
        return base
    except Exception as e:
        logger.warning("Stock option chain %s failed: %s", symbol, e)
        base["error"] = str(e)
        return base


def _refresh_payload() -> dict[str, Any]:
    try:
        settings = get_settings()
    except ValidationError as e:
        return {
            "ok": False,
            "error": f"UPSTOX_ACCESS_TOKEN / settings invalid: {e}",
            "stocks": [],
            "disclaimer": "",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "stocks": [],
            "disclaimer": "",
        }

    params = load_analysis_parameters(settings)
    metas = liquidity_stock_metas_ordered()
    client = UpstoxClient(settings, params)
    stocks: list[dict[str, Any]] = []
    try:
        for meta in metas:
            stocks.append(_process_one_stock(client, params, meta))
    finally:
        client.close()

    ok_any = any(s.get("ok") for s in stocks)
    return {
        "ok": ok_any,
        "error": None if ok_any else "All stock chains failed — check token and symbols.",
        "stocks": stocks,
        "disclaimer": (
            "Live CE/PE suggestions use the same ATM/OTM rules as the NIFTY dashboard (analysis.yaml + stock overrides). "
            "OI change vs prev close uses exchange prev_oi; “since last poll” uses the prior successful server refresh "
            f"(cache TTL {int(CACHE_TTL_SECONDS)}s). "
            "Lot size comes from Upstox option contracts; required margin for 1 lot BUY uses POST /charges/margin when "
            "available, else ≈ LTP × lot. Broker SPAN / final margin may differ. Not investment advice."
        ),
    }


def get_stock_options_live(*, force_refresh: bool = False) -> dict[str, Any]:
    """Return cached or freshly built live snapshot (thread-safe)."""
    global _cached_at, _cached_payload
    now = time.time()
    with _service_lock:
        if (
            _cached_payload is not None
            and _cached_at is not None
            and not force_refresh
            and (now - _cached_at) < CACHE_TTL_SECONDS
        ):
            age = now - _cached_at
            out = {**_cached_payload, "refreshed_at": _cached_payload.get("refreshed_at"), "cache_age_seconds": age}
            return out

        body = _refresh_payload()
        refreshed = datetime.now(IST).isoformat()
        body["refreshed_at"] = refreshed
        body["cache_age_seconds"] = 0.0
        _cached_payload = body
        _cached_at = time.time()
        return body
