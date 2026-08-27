"""
Persist NIFTY index future LTP + OI for the 09:15–09:30 IST opening-window trend.

Trend mapping (future OI vs future price, first tick in 09:15–09:29 vs first tick at/after 09:30):
  OI↑ price↑ → Long buildup
  OI↑ price↓ → Short buildup
  OI↓ price↓ → Profit booking
  OI↓ price↑ → Short covering
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
logger = logging.getLogger(__name__)

_lock = threading.Lock()

# First leg: [WIN_START, WIN_END)  ·  Second leg: t >= WIN_END (IST)
WIN_START = time(9, 15, 0)
WIN_END = time(9, 30, 0)

# Bump when sampling rules change so stale same-day JSON is not reused.
WINDOW_ID = "915_930_v1"


def opening_window_json_path(project_root: Path, segment: str = "nifty") -> Path:
    out = project_root / "exports"
    out.mkdir(parents=True, exist_ok=True)
    try:
        from config.segments import get_segment

        name = get_segment(segment).opening_window_basename
    except Exception:
        name = "nifty_opening_window.json" if segment == "nifty" else f"{segment}_opening_window.json"
    return out / name


def _default_store() -> dict[str, Any]:
    return {"version": 2, "by_date": {}}


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return _default_store()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return _default_store()
        raw.setdefault("version", 2)
        raw.setdefault("by_date", {})
        if not isinstance(raw["by_date"], dict):
            raw["by_date"] = {}
        return raw
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Opening window store load failed (%s): %s", path, e)
        return _default_store()


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _classify_trend(d_ltp: float, d_oi: int) -> tuple[str, str]:
    """Return (trend_key, human_label)."""
    flat_p = abs(d_ltp) < 1e-9
    flat_o = d_oi == 0
    if flat_p and flat_o:
        return "neutral", "Neutral (no OI or price change)"
    if flat_o:
        return "neutral_oi", "OI unchanged — trend unclear"
    if flat_p:
        return "neutral_price", "Price unchanged — trend unclear"

    up_p = d_ltp > 0
    up_o = d_oi > 0
    if up_o and up_p:
        return "long_buildup", "Long buildup"
    if up_o and not up_p:
        return "short_buildup", "Short buildup"
    if not up_o and not up_p:
        return "profit_booking", "Profit booking"
    return "short_covering", "Short covering"


def _reset_session_if_window_migrated(sess: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(sess, dict) or sess.get("window_id") != WINDOW_ID:
        return {"window_id": WINDOW_ID}
    return sess


def provisional_from_early(
    early: dict[str, Any],
    *,
    ltp: float,
    oi: int,
    when: datetime,
) -> dict[str, Any] | None:
    """Live trend vs first 9:15-leg tick while still inside [9:15, 9:30)."""
    t = when.astimezone(IST).time()
    if not (WIN_START <= t < WIN_END):
        return None
    d_ltp = float(ltp) - float(early["ltp"])
    d_oi = int(oi) - int(early["oi"])
    k, lab = _classify_trend(d_ltp, d_oi)
    return {
        "trend_key": k,
        "trend_label": lab,
        "d_ltp": d_ltp,
        "d_oi": d_oi,
        "ltp": float(ltp),
        "oi": int(oi),
    }


def record_future_snapshot(
    project_root: Path,
    *,
    when: datetime | None = None,
    ltp: float,
    oi: int,
    symbol: str = "",
    segment: str = "nifty",
) -> dict[str, Any]:
    """
    Record one future quote sample (IST). Updates JSON store and returns a summary for API cache.
    """
    now = when or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)

    d = now.date()
    t = now.time()
    day_key = d.isoformat()
    iso = now.isoformat()

    path = opening_window_json_path(project_root, segment)

    with _lock:
        store = _load(path)
        by_date: dict[str, Any] = store["by_date"]

        sess = _reset_session_if_window_migrated(by_date.get(day_key))
        by_date[day_key] = sess

        # 09:15–09:29:59.999 — first sample in window (anchor for Δ)
        if WIN_START <= t < WIN_END:
            if "early" not in sess:
                sess["early"] = {"at": iso, "ltp": float(ltp), "oi": int(oi), "symbol": symbol}

        # First sample at or after 09:30 (end anchor)
        if t >= WIN_END:
            if "late" not in sess:
                sess["late"] = {"at": iso, "ltp": float(ltp), "oi": int(oi), "symbol": symbol}

        early = sess.get("early")
        late = sess.get("late")
        trend_key = ""
        trend_label = ""
        d_ltp = None
        d_oi = None
        ready = isinstance(early, dict) and isinstance(late, dict)
        if ready:
            d_ltp = float(late["ltp"]) - float(early["ltp"])
            d_oi = int(late["oi"]) - int(early["oi"])
            trend_key, trend_label = _classify_trend(d_ltp, d_oi)
            sess["trend_key"] = trend_key
            sess["trend_label"] = trend_label
            sess["d_ltp"] = d_ltp
            sess["d_oi"] = d_oi

        # Trim old dates (keep last 90 calendar keys)
        keys = sorted(by_date.keys())
        for old in keys[:-90]:
            del by_date[old]

        try:
            _save(path, store)
        except OSError as e:
            logger.warning("Opening window store save failed: %s", e)

        provisional: dict[str, Any] | None = None
        if not ready and isinstance(early, dict):
            provisional = provisional_from_early(early, ltp=float(ltp), oi=int(oi), when=now)

        return {
            "date": day_key,
            "early": early if isinstance(early, dict) else None,
            "late": late if isinstance(late, dict) else None,
            "trend_key": trend_key,
            "trend_label": trend_label,
            "d_ltp": d_ltp,
            "d_oi": d_oi,
            "ready": ready,
            "now_is_before_930": t < WIN_END,
            "provisional": provisional,
            "chain_early": sess.get("chain_early") if isinstance(sess.get("chain_early"), dict) else None,
        }


def today_payload_from_store(project_root: Path, segment: str = "nifty") -> dict[str, Any] | None:
    """Rebuild today's opening-window summary from JSON (e.g. after API restart)."""
    now = datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)
    day_key = now.date().isoformat()
    path = opening_window_json_path(project_root, segment)
    with _lock:
        store = _load(path)
    sess = store.get("by_date", {}).get(day_key)
    if not isinstance(sess, dict):
        return {
            "date": day_key,
            "early": None,
            "late": None,
            "trend_key": "",
            "trend_label": "",
            "d_ltp": None,
            "d_oi": None,
            "ready": False,
            "now_is_before_930": now.time() < WIN_END,
            "provisional": None,
            "chain_early": None,
        }
    early = sess.get("early") if isinstance(sess.get("early"), dict) else None
    late = sess.get("late") if isinstance(sess.get("late"), dict) else None
    trend_key = str(sess.get("trend_key") or "")
    trend_label = str(sess.get("trend_label") or "")
    d_ltp = sess.get("d_ltp")
    d_oi = sess.get("d_oi")
    ready = isinstance(early, dict) and isinstance(late, dict)
    if ready and (not trend_key) and d_ltp is None:
        d_ltp = float(late["ltp"]) - float(early["ltp"])
        d_oi = int(late["oi"]) - int(early["oi"])
        trend_key, trend_label = _classify_trend(d_ltp, d_oi)

    chain_early = sess.get("chain_early") if isinstance(sess.get("chain_early"), dict) else None
    return {
        "date": day_key,
        "early": early,
        "late": late,
        "trend_key": trend_key,
        "trend_label": trend_label,
        "d_ltp": d_ltp,
        "d_oi": d_oi,
        "ready": ready,
        "now_is_before_930": now.time() < WIN_END,
        "provisional": None,
        "chain_early": chain_early,
    }


def merge_provisional_into_today(today_dict: dict[str, Any], future_ltp: float | None, future_oi: int | None) -> None:
    """Attach live vs-9:15-anchor trend during 09:15–09:30 when final leg not yet captured."""
    if future_ltp is None or future_oi is None:
        return
    now = datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)
    early = today_dict.get("early")
    if not isinstance(early, dict) or today_dict.get("ready"):
        today_dict.pop("provisional", None)
        return
    prov = provisional_from_early(early, ltp=float(future_ltp), oi=int(future_oi), when=now)
    if prov:
        today_dict["provisional"] = prov
    else:
        today_dict.pop("provisional", None)


def record_chain_early_anchor(
    project_root: Path,
    *,
    when: datetime | None = None,
    total_ce_oi: int,
    total_pe_oi: int,
    total_ce_volume: int = 0,
    total_pe_volume: int = 0,
    pcr: float | None = None,
    spot: float = 0.0,
    support_strike: int | None = None,
    resistance_strike: int | None = None,
    segment: str = "nifty",
) -> dict[str, Any] | None:
    """
    Persist first option-chain totals inside 09:15–09:30 for session ΔOI vs 09:15.

    Returns the stored chain_early dict (existing or newly written).
    """
    now = when or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)

    t = now.time()
    if not (WIN_START <= t < WIN_END):
        # Outside window: return existing anchor if present
        day_key = now.date().isoformat()
        path = opening_window_json_path(project_root, segment)
        with _lock:
            store = _load(path)
            sess = store.get("by_date", {}).get(day_key)
            if isinstance(sess, dict) and isinstance(sess.get("chain_early"), dict):
                return sess["chain_early"]
        return None

    day_key = now.date().isoformat()
    iso = now.isoformat()
    path = opening_window_json_path(project_root, segment)

    with _lock:
        store = _load(path)
        by_date: dict[str, Any] = store["by_date"]
        sess = _reset_session_if_window_migrated(by_date.get(day_key))
        by_date[day_key] = sess

        if "chain_early" not in sess:
            sess["chain_early"] = {
                "at": iso,
                "total_ce_oi": int(total_ce_oi),
                "total_pe_oi": int(total_pe_oi),
                "total_ce_volume": int(total_ce_volume),
                "total_pe_volume": int(total_pe_volume),
                "pcr": float(pcr) if pcr is not None else None,
                "spot": float(spot),
                "support_strike": support_strike,
                "resistance_strike": resistance_strike,
            }
            try:
                _save(path, store)
            except OSError as e:
                logger.warning("Opening window chain_early save failed: %s", e)

        return sess.get("chain_early") if isinstance(sess.get("chain_early"), dict) else None


def attach_chain_early_to_today(
    today_dict: dict[str, Any], project_root: Path, segment: str = "nifty"
) -> None:
    """Ensure today's opening_window payload includes chain_early from the JSON store."""
    if not isinstance(today_dict, dict):
        return
    if isinstance(today_dict.get("chain_early"), dict):
        return
    day_key = str(today_dict.get("date") or datetime.now(IST).date().isoformat())
    path = opening_window_json_path(project_root, segment)
    with _lock:
        store = _load(path)
    sess = store.get("by_date", {}).get(day_key)
    if isinstance(sess, dict) and isinstance(sess.get("chain_early"), dict):
        today_dict["chain_early"] = sess["chain_early"]


def build_history_rows(
    project_root: Path, limit: int = 30, segment: str = "nifty"
) -> list[dict[str, Any]]:
    """Recent days with computed trend (newest first)."""
    path = opening_window_json_path(project_root, segment)
    with _lock:
        store = _load(path)
    by_date = store.get("by_date") or {}
    rows: list[dict[str, Any]] = []
    for day_key in sorted(by_date.keys(), reverse=True):
        sess = by_date[day_key]
        if not isinstance(sess, dict):
            continue
        if "trend_key" not in sess:
            continue
        rows.append(
            {
                "date": day_key,
                "trend_key": sess.get("trend_key", ""),
                "trend_label": sess.get("trend_label", ""),
                "d_ltp": sess.get("d_ltp"),
                "d_oi": sess.get("d_oi"),
                "early_at": (sess.get("early") or {}).get("at"),
                "late_at": (sess.get("late") or {}).get("at"),
            }
        )
        if len(rows) >= limit:
            break
    return rows
