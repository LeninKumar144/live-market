"""
Multi-underlying segment config for index / commodity OI dashboards.

Ids: nifty | banknifty | sensex | mcx
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _env(key: str, default: str = "") -> str:
    v = os.environ.get(key)
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


def _env_int(key: str, default: int) -> int:
    raw = _env(key, str(default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _env_float(key: str, default: float) -> float:
    raw = _env(key, str(default))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True, slots=True)
class SegmentConfig:
    id: str
    display_name: str
    short_label: str
    instrument_key: str
    strike_step: int
    option_lot_size: int
    flat_threshold_points: float
    future_kind: str
    show_india_vix: bool
    show_gift_note: bool
    excel_basename: str
    opening_window_basename: str
    search_query: str = ""
    search_exchange: str = "NSE"
    search_segment: str = "FO"
    route_path: str = ""
    supports_option_chain: bool = True


DEFAULT_SEGMENT = "nifty"


@lru_cache(maxsize=1)
def all_segments() -> dict[str, SegmentConfig]:
    """Built once per process; env overrides apply at first call."""
    return {
        "nifty": SegmentConfig(
            id="nifty",
            display_name="NIFTY 50",
            short_label="NIFTY",
            instrument_key=_env("NIFTY_INSTRUMENT_KEY", "NSE_INDEX|Nifty 50"),
            strike_step=_env_int("NIFTY_STRIKE_STEP", 50),
            option_lot_size=_env_int("NIFTY_OPTION_LOT_SIZE", 65),
            flat_threshold_points=_env_float("NIFTY_FLAT_THRESHOLD", 8.0),
            future_kind="nifty",
            show_india_vix=True,
            show_gift_note=True,
            excel_basename="nifty_oi_live.xlsx",
            opening_window_basename="nifty_opening_window.json",
            route_path="/nifty",
        ),
        "banknifty": SegmentConfig(
            id="banknifty",
            display_name="Bank Nifty",
            short_label="BANKNIFTY",
            instrument_key=_env("BANKNIFTY_INSTRUMENT_KEY", "NSE_INDEX|Nifty Bank"),
            strike_step=_env_int("BANKNIFTY_STRIKE_STEP", 100),
            option_lot_size=_env_int("BANKNIFTY_OPTION_LOT_SIZE", 15),
            flat_threshold_points=_env_float("BANKNIFTY_FLAT_THRESHOLD", 25.0),
            future_kind="banknifty",
            show_india_vix=True,
            show_gift_note=False,
            excel_basename="banknifty_oi_live.xlsx",
            opening_window_basename="banknifty_opening_window.json",
            search_query="BANKNIFTY",
            route_path="/banknifty",
        ),
        "sensex": SegmentConfig(
            id="sensex",
            display_name="SENSEX",
            short_label="SENSEX",
            instrument_key=_env("SENSEX_INSTRUMENT_KEY", "BSE_INDEX|SENSEX"),
            strike_step=_env_int("SENSEX_STRIKE_STEP", 100),
            option_lot_size=_env_int("SENSEX_OPTION_LOT_SIZE", 10),
            flat_threshold_points=_env_float("SENSEX_FLAT_THRESHOLD", 40.0),
            future_kind="sensex",
            show_india_vix=True,
            show_gift_note=False,
            excel_basename="sensex_oi_live.xlsx",
            opening_window_basename="sensex_opening_window.json",
            search_query="SENSEX",
            search_exchange="BSE",
            route_path="/sensex",
        ),
        "mcx": SegmentConfig(
            id="mcx",
            display_name="MCX Crude Oil",
            short_label="MCX",
            # Optional pin for futures quotes; Upstox option-chain API does not support MCX.
            # Leave empty → resolve near-month CRUDEOIL future via instrument search.
            instrument_key=_env("MCX_INSTRUMENT_KEY", ""),
            strike_step=_env_int("MCX_STRIKE_STEP", 50),
            option_lot_size=_env_int("MCX_OPTION_LOT_SIZE", 100),
            flat_threshold_points=_env_float("MCX_FLAT_THRESHOLD", 5.0),
            future_kind="mcx_crude",
            show_india_vix=False,
            show_gift_note=False,
            excel_basename="mcx_crude_oi_live.xlsx",
            opening_window_basename="mcx_crude_opening_window.json",
            search_query=_env("MCX_SEARCH_QUERY", "CRUDEOIL"),
            search_exchange="MCX",
            search_segment="FO",
            route_path="/mcx",
            supports_option_chain=False,
        ),
    }


def get_segment(segment_id: str | None) -> SegmentConfig:
    sid = (segment_id or DEFAULT_SEGMENT).strip().lower()
    segs = all_segments()
    if sid not in segs:
        raise KeyError(f"Unknown segment '{sid}'. Choose from: {', '.join(segs)}")
    return segs[sid]


def enabled_segment_ids() -> list[str]:
    """
    Segments polled in the background OI loop.

    Env `OI_SEGMENTS` = comma list (default: nifty,banknifty,sensex,mcx).
    """
    raw = _env("OI_SEGMENTS", "nifty,banknifty,sensex,mcx")
    segs = all_segments()
    out: list[str] = []
    for part in raw.split(","):
        sid = part.strip().lower()
        if sid and sid in segs and sid not in out:
            out.append(sid)
    return out or [DEFAULT_SEGMENT]


def segment_public_meta(seg: SegmentConfig) -> dict:
    """Small JSON-friendly dict for API / frontend labels."""
    return {
        "id": seg.id,
        "display_name": seg.display_name,
        "short_label": seg.short_label,
        "strike_step": seg.strike_step,
        "show_india_vix": seg.show_india_vix,
        "show_gift_note": seg.show_gift_note,
        "route_path": seg.route_path or f"/{seg.id}",
        "instrument_key": seg.instrument_key,
        "supports_option_chain": bool(seg.supports_option_chain),
    }
