"""NIFTY-style listed expiry helpers for leg labels (English weekday + day + month)."""

from __future__ import annotations

from datetime import date

_WD = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MO = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def format_expiry_weekday_day_month(d: date) -> str:
    """e.g. Thu 27 Mar 2026 (locale-independent English)."""
    return f"{_WD[d.weekday()]} {d.day} {_MO[d.month]} {d.year}"


def pick_diagonal_expiry_pair(
    expiries: list[date],
    chain_expiry_iso: str,
    today: date,
) -> tuple[date | None, date | None]:
    """
    Near (short) leg: prefer the expiry of the chain you are trading; else nearest listed.
    Long leg: first listed expiry in a later calendar month than the short; else next listed after short.
    """
    fut = sorted({d for d in expiries if d >= today})
    if not fut:
        return None, None

    short_d: date | None = None
    raw = (chain_expiry_iso or "").strip()[:10]
    if raw:
        try:
            ce = date.fromisoformat(raw)
            if ce in fut:
                short_d = ce
            elif ce >= today:
                short_d = min(fut, key=lambda x: abs((x - ce).days))
        except ValueError:
            pass
    if short_d is None:
        short_d = fut[0]

    long_d: date | None = None
    for d in fut:
        if d <= short_d:
            continue
        if (d.year, d.month) != (short_d.year, short_d.month):
            long_d = d
            break
    if long_d is None:
        for d in fut:
            if d > short_d:
                long_d = d
                break
    if long_d is None:
        long_d = short_d
    return short_d, long_d
