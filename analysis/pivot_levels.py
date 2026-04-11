"""
Classic pivot levels from prior period OHLC (High, Low, Close).

P = (H + L + C) / 3
R1 = 2P − L,  S1 = 2P − H
R2 = P + (H − L),  S2 = P − (H − L)

Used for intraday (prior session), weekly (prior ISO week), monthly (prior calendar month).
All driven by live daily candles fetched each refresh.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def _r2(x: float) -> float:
    return round(float(x), 2)


def classic_pivot_pack(h: float, l: float, c: float, *, basis_label: str) -> dict[str, Any]:
    h, l, c = float(h), float(l), float(c)
    if h <= 0 or l <= 0 or h < l:
        return {"basis_label": basis_label, "unavailable_reason": "Invalid H/L/C for pivot."}
    p = (h + l + c) / 3.0
    r1 = 2 * p - l
    s1 = 2 * p - h
    r2 = p + (h - l)
    s2 = p - (h - l)
    return {
        "pivot": _r2(p),
        "r1": _r2(r1),
        "r2": _r2(r2),
        "s1": _r2(s1),
        "s2": _r2(s2),
        "basis_high": _r2(h),
        "basis_low": _r2(l),
        "basis_close": _r2(c),
        "basis_label": basis_label,
        "unavailable_reason": None,
    }


def _bars_before(
    daily: list[tuple[date, float, float, float, float]], today: date
) -> list[tuple[date, float, float, float, float]]:
    return [b for b in daily if b[0] < today]


def pivot_prior_trading_day(
    daily: list[tuple[date, float, float, float, float]], today: date
) -> dict[str, Any] | None:
    """Last completed daily bar strictly before `today` (typically yesterday if market was open)."""
    prev = _bars_before(daily, today)
    if not prev:
        return None
    prev.sort(key=lambda x: x[0])
    d, _o, h, l, c = prev[-1]
    return classic_pivot_pack(h, l, c, basis_label=f"Prior session {d.isoformat()}")


def pivot_prior_calendar_week(
    daily: list[tuple[date, float, float, float, float]], today: date
) -> dict[str, Any] | None:
    """Completed ISO week before the week containing `today` (Mon–Sun aggregate H/L, last day C)."""
    this_monday = today - timedelta(days=today.weekday())
    prev_sunday = this_monday - timedelta(days=1)
    prev_monday = prev_sunday - timedelta(days=6)
    bars = [b for b in daily if prev_monday <= b[0] <= prev_sunday]
    if not bars:
        return None
    bars.sort(key=lambda x: x[0])
    h_mx = max(b[2] for b in bars)
    l_mn = min(b[3] for b in bars)
    c_last = bars[-1][4]
    return classic_pivot_pack(
        h_mx,
        l_mn,
        c_last,
        basis_label=f"Prior week {prev_monday.isoformat()} to {prev_sunday.isoformat()}",
    )


def pivot_prior_calendar_month(
    daily: list[tuple[date, float, float, float, float]], today: date
) -> dict[str, Any] | None:
    """Previous calendar month: max H, min L, last session C in that month."""
    first_this = today.replace(day=1)
    last_prev = first_this - timedelta(days=1)
    y, m = last_prev.year, last_prev.month
    bars = [b for b in daily if b[0].year == y and b[0].month == m]
    if not bars:
        return None
    bars.sort(key=lambda x: x[0])
    h_mx = max(b[2] for b in bars)
    l_mn = min(b[3] for b in bars)
    c_last = bars[-1][4]
    return classic_pivot_pack(
        h_mx,
        l_mn,
        c_last,
        basis_label=f"Prior month {y}-{m:02d}",
    )


def compute_timeframe_pivots(
    daily: list[tuple[date, float, float, float, float]], today: date
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Returns (intraday_basis, weekly_basis, monthly_basis) pivot dicts or None if data missing."""
    return (
        pivot_prior_trading_day(daily, today),
        pivot_prior_calendar_week(daily, today),
        pivot_prior_calendar_month(daily, today),
    )
