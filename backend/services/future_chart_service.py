"""Cached NIFTY future 1m candles + OI/PCR/ΔOI/Δvol synthesis for the dashboard chart."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: dict[str, Any] = {}
TTL_SECONDS = 45.0


def _utc_unix(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return int(dt.astimezone(timezone.utc).timestamp())


def _plan_and_candles_from_snap(
    snap: dict[str, Any],
    *,
    ik: str,
    day: Any,
    bars: list[Any],
    chart_warning: str | None,
) -> dict[str, Any]:
    from analysis.oi_future_synthesis import build_trade_plan

    nf = snap.get("nifty_future") if isinstance(snap.get("nifty_future"), dict) else None
    sym = str((nf or {}).get("symbol") or "NIFTY FUT")
    ltp = float((nf or {}).get("ltp") or 0.0)
    spot = float(snap.get("spot") or 0.0)

    lp = snap.get("live_prediction") if isinstance(snap.get("live_prediction"), dict) else {}
    ag = lp.get("aggregate_chain") if isinstance(lp.get("aggregate_chain"), dict) else {}
    ce_doi = int(ag.get("total_ce_oi_change") or 0)
    pe_doi = int(ag.get("total_pe_oi_change") or 0)
    net_cp = int(ag.get("net_call_minus_put_oi_change") or 0)
    bias = str(ag.get("bias") or "")
    vce = ag.get("total_ce_volume_change_since_last_poll")
    vpe = ag.get("total_pe_volume_change_since_last_poll")
    try:
        vce_i = int(vce) if vce is not None else None
    except (TypeError, ValueError):
        vce_i = None
    try:
        vpe_i = int(vpe) if vpe is not None else None
    except (TypeError, ValueError):
        vpe_i = None

    pcr = snap.get("pcr")
    if pcr is not None:
        try:
            pcr = float(pcr)
        except (TypeError, ValueError):
            pcr = None

    tco = snap.get("total_call_oi")
    tpo = snap.get("total_put_oi")
    try:
        tco_i = int(tco) if tco is not None else None
    except (TypeError, ValueError):
        tco_i = None
    try:
        tpo_i = int(tpo) if tpo is not None else None
    except (TypeError, ValueError):
        tpo_i = None

    tcv = snap.get("total_call_volume")
    tpv = snap.get("total_put_volume")
    try:
        tcv_i = int(tcv) if tcv is not None else None
    except (TypeError, ValueError):
        tcv_i = None
    try:
        tpv_i = int(tpv) if tpv is not None else None
    except (TypeError, ValueError):
        tpv_i = None

    sr = snap.get("sr_levels") if isinstance(snap.get("sr_levels"), dict) else None

    plan = build_trade_plan(
        bars,
        pcr=pcr,
        total_call_oi=tco_i,
        total_put_oi=tpo_i,
        total_call_volume=tcv_i,
        total_put_volume=tpv_i,
        ce_doi=ce_doi,
        pe_doi=pe_doi,
        ce_vol_delta_since_last_poll=vce_i,
        pe_vol_delta_since_last_poll=vpe_i,
        bias=bias,
        net_cp=net_cp,
        ltp=ltp,
        sr_levels=sr,
        spot=spot,
        has_future_instrument=bool(ik),
    )

    candles_out = [
        {
            "time_unix": _utc_unix(b.t),
            "time_iso_ist": b.t.astimezone(IST).isoformat(timespec="seconds")
            if b.t.tzinfo
            else b.t.replace(tzinfo=IST).isoformat(timespec="seconds"),
            "open": round(b.o, 2),
            "high": round(b.h, 2),
            "low": round(b.l, 2),
            "close": round(b.c, 2),
            "volume": b.v,
        }
        for b in bars
    ]

    fetched_at = datetime.now(IST).isoformat(timespec="seconds") if candles_out else None
    return {
        "ok": True,
        "error": None,
        "chart_warning": chart_warning,
        "symbol": sym,
        "instrument_key": ik,
        "spot": spot,
        "ltp": ltp,
        "session_day_ist": day.isoformat(),
        "candles": candles_out,
        "trade_plan": plan,
        "chain_refreshed_at": snap.get("updated_at"),
        "candles_fetched_at": fetched_at,
    }


def get_future_chart_payload() -> dict[str, Any]:
    from analysis.oi_future_synthesis import bars_from_tuples
    from config.settings import get_settings, load_analysis_parameters
    from data.upstox_client import UpstoxClient
    from pydantic import ValidationError

    from services.oi_excel_service import get_oi_cache_snapshot

    snap = get_oi_cache_snapshot()
    nf = snap.get("nifty_future") if isinstance(snap.get("nifty_future"), dict) else None
    ik = str((nf or {}).get("instrument_key") or "")
    sym = str((nf or {}).get("symbol") or "NIFTY FUT")
    day = datetime.now(IST).date()
    cache_key = f"{ik or 'no-future'}:{day.isoformat()}"

    now = time.monotonic()
    with _lock:
        hit = _cache.get(cache_key)
        if hit and (now - float(hit["mono"])) < TTL_SECONDS:
            return hit["payload"]

    base_err: dict[str, Any] = {
        "ok": False,
        "error": None,
        "chart_warning": None,
        "symbol": sym,
        "instrument_key": ik,
        "spot": float(snap.get("spot") or 0),
        "ltp": float((nf or {}).get("ltp") or 0.0),
        "session_day_ist": day.isoformat(),
        "candles": [],
        "trade_plan": {},
        "chain_refreshed_at": snap.get("updated_at"),
        "candles_fetched_at": None,
    }

    if not snap.get("updated_at") or snap.get("error"):
        base_err["error"] = str(snap.get("error") or "Option chain not ready — wait for OI refresh.")
        with _lock:
            _cache[cache_key] = {"mono": now, "payload": base_err}
        return base_err

    chart_warning: str | None = None
    rows: list[Any] = []

    if ik:
        try:
            settings = get_settings()
        except ValidationError as e:
            base_err["error"] = f"Settings invalid: {e}"
            with _lock:
                _cache[cache_key] = {"mono": now, "payload": base_err}
            return base_err

        params = load_analysis_parameters(settings)
        client: UpstoxClient | None = None
        try:
            client = UpstoxClient(settings, params)
            rows = client.fetch_1minute_candles(ik, for_day=day)
        except Exception as e:
            logger.warning("Future chart candle fetch failed: %s", e)
            chart_warning = f"1-minute future candles unavailable: {e}"
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
    else:
        chart_warning = (
            "NIFTY index future is not in the OI cache — candle chart is skipped. "
            "Entry/exit below uses Σ CE/PE OI, ΔOI, PCR, and live Σ CE/PE volume & Δvol from the option chain. "
            "Use “Refresh OI now” or check Upstox / contract resolution."
        )

    bars = bars_from_tuples(rows)
    if ik and not chart_warning and not rows:
        chart_warning = "No 1-minute bars returned for this session day (market closed or delayed data)."

    payload = _plan_and_candles_from_snap(snap, ik=ik, day=day, bars=bars, chart_warning=chart_warning)

    with _lock:
        _cache[cache_key] = {"mono": time.monotonic(), "payload": payload}
    return payload
