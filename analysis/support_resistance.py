"""
OI-based support / resistance from NIFTY option chains.

Support: strikes *below* spot with the largest put OI (put writers often defend downside).
Resistance: strikes *above* spot with the largest call OI (call writers often cap upside).

Intraday / weekly / monthly use different listed expiries when available; otherwise the same
chain is reused and a caption explains it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from data.models import StrikeRow

_IST = ZoneInfo("Asia/Kolkata")


def pick_weekly_monthly_isos(expiries: list[date], chain_expiry_iso: str) -> tuple[str, str]:
    """
    Weekly: next listed expiry after the chain expiry when possible, else the chain expiry.
    Monthly: first listed expiry in a later calendar month than the chain, else farthest listed.
    """
    if not expiries:
        return chain_expiry_iso, chain_expiry_iso
    try:
        chain_d = date.fromisoformat(chain_expiry_iso.strip()[:10])
    except ValueError:
        chain_d = expiries[0]

    weekly_iso = chain_expiry_iso
    for d in expiries:
        if d > chain_d:
            weekly_iso = d.isoformat()
            break
    if weekly_iso == chain_expiry_iso and len(expiries) > 1:
        weekly_iso = expiries[1].isoformat()

    later_month = [
        d
        for d in expiries
        if d >= chain_d and (d.year, d.month) > (chain_d.year, chain_d.month)
    ]
    monthly_d = later_month[-1] if later_month else expiries[-1]
    monthly_iso = monthly_d.isoformat()
    return weekly_iso, monthly_iso


def oi_walls_from_rows(rows: list[StrikeRow], spot: float, *, top_n: int = 3) -> dict[str, Any]:
    if not rows or spot <= 0:
        return {
            "spot": round(spot, 2) if spot else 0.0,
            "supports": [],
            "resistances": [],
            "note": "Insufficient chain or spot for OI-based levels.",
        }

    below = [r for r in rows if float(r.strike_price) < spot]
    above = [r for r in rows if float(r.strike_price) > spot]
    below.sort(key=lambda r: r.put.oi, reverse=True)
    above.sort(key=lambda r: r.call.oi, reverse=True)

    supports = []
    for r in below[:top_n]:
        supports.append(
            {
                "strike": int(r.strike_price),
                "pe_oi": int(r.put.oi),
                "ce_oi": int(r.call.oi),
                "kind": "support",
                "reason": "High PE OI below spot — often watched as a put wall / support zone.",
            }
        )

    resistances = []
    for r in above[:top_n]:
        resistances.append(
            {
                "strike": int(r.strike_price),
                "ce_oi": int(r.call.oi),
                "pe_oi": int(r.put.oi),
                "kind": "resistance",
                "reason": "High CE OI above spot — often watched as a call wall / resistance zone.",
            }
        )

    return {
        "spot": round(spot, 2),
        "supports": supports,
        "resistances": resistances,
        "note": (
            "OI walls from the live option chain. Classic pivot (PP, R1–R2, S1–S2) uses prior "
            "session / week / month index daily OHLC — refreshed with each chain sync."
        ),
    }


def build_sr_bundle(client: Any, chain_expiry_iso: str, primary_rows: list[StrikeRow]) -> dict[str, Any]:
    """Fetch weekly / monthly chains as needed while `client` is still open."""
    from analysis.expiry_calendar import format_expiry_weekday_day_month

    if not primary_rows:
        return {"intraday": None, "weekly": None, "monthly": None}

    exps = client.list_future_expiries()
    w_iso, m_iso = pick_weekly_monthly_isos(exps, chain_expiry_iso)
    spot_i = float(primary_rows[0].underlying_spot_price or 0.0)

    def rows_for(iso: str) -> list[StrikeRow]:
        if iso == chain_expiry_iso:
            return primary_rows
        return client.fetch_option_chain(iso)

    w_rows = rows_for(w_iso)
    if m_iso == chain_expiry_iso:
        m_rows = primary_rows
    elif m_iso == w_iso:
        m_rows = w_rows
    else:
        m_rows = rows_for(m_iso)

    today = datetime.now(_IST).date()
    lookback = today - timedelta(days=220)
    try:
        daily_bars = client.fetch_daily_candles(lookback, today)
    except Exception:
        daily_bars = []

    from analysis.pivot_levels import compute_timeframe_pivots

    p_intraday, p_weekly, p_monthly = compute_timeframe_pivots(daily_bars, today)

    def _pivot_payload(block: dict[str, Any] | None) -> dict[str, Any]:
        if block is None:
            return {
                "unavailable_reason": "Insufficient NIFTY daily candle history for this timeframe.",
                "basis_label": "",
            }
        return block

    def horizon(
        name: str,
        exp_iso: str,
        rws: list[StrikeRow],
        caption: str | None,
        pivot_block: dict[str, Any] | None,
    ) -> dict[str, Any]:
        sp = float(rws[0].underlying_spot_price or spot_i) if rws else spot_i
        try:
            d = date.fromisoformat(exp_iso.strip()[:10])
            disp = format_expiry_weekday_day_month(d)
        except ValueError:
            disp = exp_iso
        out = oi_walls_from_rows(rws, sp, top_n=3)
        out["horizon"] = name
        out["expiry_iso"] = exp_iso
        out["expiry_display"] = disp
        if caption:
            out["chain_caption"] = caption
        out["pivot_levels"] = _pivot_payload(pivot_block)
        return out

    w_caption = None
    if w_iso == chain_expiry_iso:
        w_caption = "Uses the nearest listed expiry (same chain as intraday)."

    m_caption = None
    if m_iso == chain_expiry_iso:
        m_caption = "Uses the nearest listed expiry (same chain as intraday)."
    elif m_iso == w_iso:
        m_caption = "Uses the same expiry as the weekly horizon."

    return {
        "intraday": horizon("intraday", chain_expiry_iso, primary_rows, None, p_intraday),
        "weekly": horizon("weekly", w_iso, w_rows, w_caption, p_weekly),
        "monthly": horizon("monthly", m_iso, m_rows, m_caption, p_monthly),
    }
