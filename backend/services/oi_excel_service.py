"""
Fetch NIFTY option-chain CE/PE OI, write Excel on an interval, and derive suggested buy strikes.

Uses project-root Upstox client and analysis helpers (sys.path includes parent of backend/).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

IST = ZoneInfo("Asia/Kolkata")
logger = logging.getLogger(__name__)

# Index future: OI change vs price change (replaces verbose CALL/PUT × volume cheat sheets).
OI_VS_PRICE_FUTURE_LEGEND = pd.DataFrame(
    {
        "OI_vs_price": [
            "OI↑ + price↑ → Long buildup",
            "OI↑ + price↓ → Short buildup",
            "OI↓ + price↓ → Profit booking",
            "OI↓ + price↑ → Short covering",
        ],
    }
)

_lock = threading.Lock()
_history: deque[Any] = deque(maxlen=32)
_cache: dict[str, Any] = {
    "updated_at": None,
    "excel_path": None,
    "error": None,
    "nifty_future": None,
    "opening_window_today": None,
    "opening_window_history": [],
    "spot": 0.0,
    "expiry": "",
    "pcr": None,
    "total_call_oi": None,
    "total_put_oi": None,
    "total_call_volume": None,
    "total_put_volume": None,
    "buy_ce": None,
    "buy_pe": None,
    "market_move_label": "",
    "market_direction": "flat",
    "market_delta_pct": None,
    "chain_ltp": {},
    "diagonal_short_expiry_display": "",
    "diagonal_long_expiry_display": "",
    "diagonal_short_expiry_iso": "",
    "diagonal_long_expiry_iso": "",
    "excel_export_error": None,
    "sr_levels": None,
    "live_prediction": None,
}


def oi_excel_path() -> Path:
    raw = os.environ.get("OI_EXCEL_PATH", "").strip()
    if raw:
        return Path(raw)
    out_dir = PROJECT_ROOT / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / "nifty_oi_live.xlsx"


def oi_update_interval_seconds() -> float:
    return max(15.0, float(os.environ.get("OI_EXCEL_INTERVAL_SECONDS", "60")))


def oi_auto_update_enabled() -> bool:
    return os.environ.get("OI_AUTO_UPDATE", "1").strip().lower() not in ("0", "false", "no", "off")


def oi_history_max_rows() -> int:
    return max(100, min(50_000, int(os.environ.get("OI_HISTORY_MAX_ROWS", "5000"))))


def _quote_key_map(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (data or {}).items():
        if not isinstance(v, dict):
            continue
        canon = k.replace(":", "|", 1)
        out[canon] = v
        out[k] = v
    return out


def _try_imports():
    from analysis.market_move import compute_market_move
    from analysis.signal_engine import _placement_for_signal
    from config.settings import get_settings, load_analysis_parameters
    from data.models import StrikeSnapshot
    from data.upstox_client import UpstoxAPIError, UpstoxClient
    from utils.helpers import resolve_execution_strike

    return (
        compute_market_move,
        _placement_for_signal,
        get_settings,
        load_analysis_parameters,
        StrikeSnapshot,
        UpstoxAPIError,
        UpstoxClient,
        resolve_execution_strike,
    )


def run_oi_excel_cycle() -> None:
    """Fetch chain, update Excel (Summary + Strikewise + History append), refresh suggestion cache."""
    try:
        (
            compute_market_move,
            _placement_for_signal,
            get_settings,
            load_analysis_parameters,
            StrikeSnapshot,
            UpstoxAPIError,
            UpstoxClient,
            resolve_execution_strike,
        ) = _try_imports()
    except ImportError as e:
        msg = f"Import error: {e}"
        logger.warning("OI cycle skipped: %s", msg)
        with _lock:
            _cache["error"] = msg
        return

    try:
        settings = get_settings()
    except ValidationError as e:
        msg = "UPSTOX_ACCESS_TOKEN / settings invalid — set .env in project root"
        logger.warning("OI cycle skipped: %s (%s)", msg, e)
        with _lock:
            _cache["error"] = msg
        return
    except Exception as e:
        msg = str(e)
        logger.warning("OI cycle skipped (settings): %s", e)
        with _lock:
            _cache["error"] = msg
        return

    params = load_analysis_parameters(settings)
    client: Any = None
    short_disp = ""
    long_disp = ""
    short_iso = ""
    long_iso = ""
    rows: list[Any] = []
    expiry = ""
    sr_bundle: dict[str, Any] | None = None
    nifty_future_payload: dict[str, Any] | None = None
    opening_today: dict[str, Any] | None = None
    try:
        client = UpstoxClient(settings, params)
        expiry = client.resolve_expiry(settings.option_expiry_date)
        rows = client.fetch_option_chain(expiry)
        try:
            from analysis.expiry_calendar import format_expiry_weekday_day_month, pick_diagonal_expiry_pair

            exps = client.list_future_expiries()
            today_ist = datetime.now(IST).date()
            s_d, l_d = pick_diagonal_expiry_pair(exps, expiry, today_ist)
            if s_d:
                short_disp = format_expiry_weekday_day_month(s_d)
                short_iso = s_d.isoformat()
            if l_d:
                long_disp = format_expiry_weekday_day_month(l_d)
                long_iso = l_d.isoformat()
        except Exception as e:
            logger.debug("Diagonal expiry labels skipped: %s", e)
        if rows:
            try:
                from analysis.support_resistance import build_sr_bundle

                sr_bundle = build_sr_bundle(client, expiry, rows)
            except Exception as e:
                logger.warning("Support/resistance bundle skipped: %s", e)
                sr_bundle = None

        fut_key: str | None = None
        fut_sym = ""
        try:
            fut_key, fut_sym = client.find_nifty_index_future("current_month")
        except UpstoxAPIError:
            try:
                fut_key, fut_sym = client.find_nifty_index_future("near_month")
            except UpstoxAPIError as e:
                logger.debug("NIFTY index future lookup skipped: %s", e)

        if fut_key:
            try:
                from services.opening_window_service import record_future_snapshot

                raw_q = client.fetch_market_quotes([fut_key])
                qmap = _quote_key_map(raw_q)
                q = qmap.get(fut_key)
                if q and isinstance(q, dict):
                    ohlc = q.get("ohlc") or {}
                    nc = q.get("net_change")
                    nifty_future_payload = {
                        "symbol": str(q.get("symbol") or fut_sym or ""),
                        "instrument_key": fut_key,
                        "ltp": float(q.get("last_price") or 0.0),
                        "oi": int(q.get("oi") or 0),
                        "volume": int(q.get("volume") or 0),
                        "net_change": float(nc) if nc is not None else None,
                        "ohlc_open": float(ohlc["open"]) if ohlc.get("open") is not None else None,
                        "ohlc_high": float(ohlc["high"]) if ohlc.get("high") is not None else None,
                        "ohlc_low": float(ohlc["low"]) if ohlc.get("low") is not None else None,
                        "ohlc_close": float(ohlc["close"]) if ohlc.get("close") is not None else None,
                    }
                    opening_today = record_future_snapshot(
                        PROJECT_ROOT,
                        ltp=nifty_future_payload["ltp"],
                        oi=nifty_future_payload["oi"],
                        symbol=nifty_future_payload["symbol"],
                    )
            except Exception as e:
                logger.warning("NIFTY future quote / opening window: %s", e)
    except UpstoxAPIError as e:
        logger.warning("Upstox option chain failed: %s", e)
        with _lock:
            _cache["error"] = str(e)
        return
    except Exception as e:
        logger.exception("OI cycle failed")
        with _lock:
            _cache["error"] = str(e)
        return
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    if not rows:
        with _lock:
            _cache["error"] = "Empty option chain"
        return

    spot = float(rows[0].underlying_spot_price or 0.0)
    strikes_map = {float(r.strike_price): r for r in rows}

    snap = StrikeSnapshot(
        captured_at=datetime.now(IST),
        spot=spot,
        expiry=expiry,
        strikes=strikes_map,
    )
    _history.append(snap)

    mv = compute_market_move(
        _history,
        params.market_move_lookback_snapshots,
        params.market_move_flat_threshold_points,
    )
    ce_placement, ce_note = _placement_for_signal(
        params.buy_strike_mode,
        "CE",
        mv,
        params.market_move_flat_threshold_points,
    )
    pe_placement, pe_note = _placement_for_signal(
        params.buy_strike_mode,
        "PE",
        mv,
        params.market_move_flat_threshold_points,
    )

    ce_strike, ce_ltp = resolve_execution_strike(
        strikes_map,
        spot,
        params.strike_step,
        "CE",
        params.min_open_interest,
        params.min_volume,
        params.buy_strike_max_steps_from_atm,
        placement=ce_placement,
        otm_steps=params.otm_strike_steps,
    )
    pe_strike, pe_ltp = resolve_execution_strike(
        strikes_map,
        spot,
        params.strike_step,
        "PE",
        params.min_open_interest,
        params.min_volume,
        params.buy_strike_max_steps_from_atm,
        placement=pe_placement,
        otm_steps=params.otm_strike_steps,
    )

    records = []
    for r in rows:
        records.append(
            {
                "Strike": int(r.strike_price),
                "CE_OI": r.call.oi,
                "PE_OI": r.put.oi,
                "CE_Volume": r.call.volume,
                "PE_Volume": r.put.volume,
                "CE_Prev_OI": r.call.prev_oi,
                "PE_Prev_OI": r.put.prev_oi,
                "CE_OI_Change": r.call.oi - r.call.prev_oi,
                "PE_OI_Change": r.put.oi - r.put.prev_oi,
                "CE_LTP": r.call.ltp,
                "PE_LTP": r.put.ltp,
            }
        )

    df = pd.DataFrame(records)
    total_ce = int(df["CE_OI"].sum())
    total_pe = int(df["PE_OI"].sum())
    total_ce_vol = int(df["CE_Volume"].sum())
    total_pe_vol = int(df["PE_Volume"].sum())
    pcr = (total_pe / total_ce) if total_ce else 0.0

    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    summary = pd.DataFrame(
        [
            {"Field": "Last updated (IST)", "Value": now_str},
            {"Field": "Underlying spot (chain)", "Value": spot},
            {"Field": "Chain expiry", "Value": expiry},
            {"Field": "Total Call (CE) OI", "Value": total_ce},
            {"Field": "Total Put (PE) OI", "Value": total_pe},
            {"Field": "Put/Call OI ratio (PCR)", "Value": round(pcr, 6)},
            {"Field": "Total Call volume", "Value": total_ce_vol},
            {"Field": "Total Put volume", "Value": total_pe_vol},
            {"Field": "Suggested BUY CE strike", "Value": int(ce_strike)},
            {"Field": "Suggested BUY PE strike", "Value": int(pe_strike)},
        ]
    )

    chain_ltp: dict[str, dict[str, float]] = {}
    for r in rows:
        k = str(int(r.strike_price))
        chain_ltp[k] = {
            "ce": float(r.call.ltp),
            "pe": float(r.put.ltp),
        }

    r_ce = strikes_map.get(ce_strike)
    r_pe = strikes_map.get(pe_strike)
    buy_ce = {
        "side": "CE",
        "strike": float(ce_strike),
        "ltp": float(ce_ltp),
        "open_interest": int(r_ce.call.oi) if r_ce else 0,
        "volume": int(r_ce.call.volume) if r_ce else 0,
        "execution_note": ce_note,
    }
    buy_pe = {
        "side": "PE",
        "strike": float(pe_strike),
        "ltp": float(pe_ltp),
        "open_interest": int(r_pe.put.oi) if r_pe else 0,
        "volume": int(r_pe.put.volume) if r_pe else 0,
        "execution_note": pe_note,
    }

    out_path = oi_excel_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    hist_df = pd.DataFrame()
    if out_path.is_file():
        try:
            hist_df = pd.read_excel(out_path, sheet_name="History")
        except (ValueError, OSError, PermissionError):
            hist_df = pd.DataFrame()

    hist_row = pd.DataFrame(
        [
            {
                "Timestamp_IST": now_str,
                "Spot": spot,
                "Expiry": expiry,
                "Total_CE_OI": total_ce,
                "Total_PE_OI": total_pe,
                "PCR": round(pcr, 6),
                "Buy_CE_Strike": int(ce_strike),
                "Buy_PE_Strike": int(pe_strike),
            }
        ]
    )
    hist_df = pd.concat([hist_df, hist_row], ignore_index=True).tail(oi_history_max_rows())

    updated_iso = datetime.now(IST).isoformat()
    try:
        from services.opening_window_service import build_history_rows

        hist_rows = build_history_rows(PROJECT_ROOT, limit=30)
    except Exception as e:
        logger.debug("opening_window history: %s", e)
        hist_rows = []

    live_prediction: dict[str, Any] | None = None
    try:
        from analysis.live_market_prediction import build_live_prediction

        live_prediction = build_live_prediction(
            spot=spot,
            rows=rows,
            sr_bundle=sr_bundle,
            opening_window_today=opening_today,
        )
    except Exception as e:
        logger.debug("live_prediction skipped: %s", e)

    vol_d_ce: int | None = None
    vol_d_pe: int | None = None
    with _lock:
        prev_cv = _cache.get("total_call_volume")
        prev_pv = _cache.get("total_put_volume")
    try:
        if prev_cv is not None:
            vol_d_ce = int(total_ce_vol) - int(prev_cv)
        if prev_pv is not None:
            vol_d_pe = int(total_pe_vol) - int(prev_pv)
    except (TypeError, ValueError):
        vol_d_ce = None
        vol_d_pe = None

    if isinstance(live_prediction, dict):
        ag = live_prediction.get("aggregate_chain")
        if isinstance(ag, dict):
            ag["total_ce_volume_change_since_last_poll"] = vol_d_ce
            ag["total_pe_volume_change_since_last_poll"] = vol_d_pe

    with _lock:
        upd: dict[str, Any] = {
            "updated_at": updated_iso,
            "excel_path": str(out_path.resolve()),
            "error": None,
            "excel_export_error": None,
            "spot": spot,
            "expiry": expiry,
            "pcr": round(pcr, 6),
            "total_call_oi": total_ce,
            "total_put_oi": total_pe,
            "total_call_volume": total_ce_vol,
            "total_put_volume": total_pe_vol,
            "buy_ce": buy_ce,
            "buy_pe": buy_pe,
            "market_move_label": str(mv.get("label") or ""),
            "market_direction": str(mv.get("direction") or "flat"),
            "market_delta_pct": float(mv["delta_pct"])
            if mv.get("delta_pct") is not None
            else None,
            "chain_ltp": chain_ltp,
            "diagonal_short_expiry_display": short_disp,
            "diagonal_long_expiry_display": long_disp,
            "diagonal_short_expiry_iso": short_iso,
            "diagonal_long_expiry_iso": long_iso,
            "sr_levels": sr_bundle,
            "live_prediction": live_prediction,
            "opening_window_history": hist_rows,
        }
        if nifty_future_payload is not None:
            upd["nifty_future"] = nifty_future_payload
        if opening_today is not None:
            upd["opening_window_today"] = opening_today
        _cache.update(upd)

    try:
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            summary.to_excel(writer, sheet_name="Summary", index=False)
            df.to_excel(writer, sheet_name="Strikewise_CE_PE_OI", index=False)
            hist_df.to_excel(writer, sheet_name="History", index=False)
            OI_VS_PRICE_FUTURE_LEGEND.to_excel(writer, sheet_name="OI_vs_price_future", index=False)
        logger.info("OI Excel updated: %s rows -> %s", len(df), out_path)
    except (PermissionError, OSError) as e:
        hint = (
            "Could not write Excel - the file may be open in Excel or another app. "
            "Close it or set OI_EXCEL_PATH to a different path. Dashboard data still updated."
        )
        logger.warning("OI Excel write failed (%s): %s", type(e).__name__, e)
        with _lock:
            _cache["excel_export_error"] = f"{hint} ({type(e).__name__})"
    except Exception as e:
        logger.warning("OI Excel write failed: %s", e)
        with _lock:
            _cache["excel_export_error"] = f"Excel export failed: {e}"


def set_oi_fatal_error(message: str) -> None:
    """Record a hard failure so /oi/* still returns 200 with a structured error."""
    with _lock:
        _cache["error"] = message


def get_oi_cache_snapshot() -> dict[str, Any]:
    with _lock:
        return dict(_cache)
