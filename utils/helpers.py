"""Small pure helpers: strike rounding, ATM selection, timestamps."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from data.models import StrikeRow

IST = ZoneInfo("Asia/Kolkata")


def round_strike(spot: float, step: int) -> float:
    """Round spot to nearest strike on `step` grid (e.g. 50 for NIFTY)."""
    s = float(step)
    return round(spot / s) * s


def atm_strike(spot: float, step: int) -> float:
    return round_strike(spot, step)


def strike_window(spot: float, step: int, radius: int) -> list[float]:
    """List of strikes centered on ATM, inclusive radius in strike steps."""
    mid = atm_strike(spot, step)
    return [mid + i * step for i in range(-radius, radius + 1)]


def _otm_candidate_strikes(
    atm: float,
    step: int,
    side: Literal["CE", "PE"],
    otm_steps: int,
    max_extra_otm: int,
) -> list[float]:
    """Ordered candidates: target OTM first, walk toward ATM, then deeper OTM if needed."""
    n = max(1, int(otm_steps))
    extra = max(0, int(max_extra_otm))
    if side == "CE":
        anchor = atm + n * step
        out: list[float] = []
        k = anchor
        while k >= atm:
            out.append(k)
            k -= step
        for i in range(1, extra + 1):
            out.append(anchor + i * step)
        return out
    anchor = atm - n * step
    out = []
    k = anchor
    while k <= atm:
        out.append(k)
        k += step
    for i in range(1, extra + 1):
        out.append(anchor - i * step)
    return out


def resolve_execution_strike(
    strikes: dict[float, StrikeRow],
    spot: float,
    step: int,
    side: Literal["CE", "PE"],
    min_open_interest: int,
    min_volume: int,
    max_steps_from_atm: int,
    *,
    placement: Literal["atm", "otm"] = "atm",
    otm_steps: int = 1,
) -> tuple[float, float]:
    """
    Strike and LTP for the option to **buy** (execution leg).

    * ``atm``: nearest rounded grid around spot, expanding for liquidity (existing behaviour).
    * ``otm``: CE = strikes above ATM (``ATM + otm_steps * step`` first); PE = below ATM.
      Walks toward ATM if the preferred OTM leg is illiquid, then tries deeper OTM.
    """
    atm = atm_strike(spot, step)

    def leg_ltp(row: StrikeRow) -> float:
        return float(row.call.ltp) if side == "CE" else float(row.put.ltp)

    def leg_ok(row: StrikeRow) -> bool:
        leg = row.call if side == "CE" else row.put
        return leg.oi >= min_open_interest and leg.volume >= min_volume

    if placement == "otm":
        ordered_strikes = _otm_candidate_strikes(
            atm, step, side, otm_steps, max_extra_otm=max_steps_from_atm
        )
    else:
        offsets = [0]
        for i in range(1, max(0, max_steps_from_atm) + 1):
            offsets.extend([i, -i])
        ordered_strikes = sorted({atm + o * step for o in offsets}, key=lambda k: (abs(k - spot), k))

    for k in ordered_strikes:
        row = strikes.get(k)
        if row and leg_ok(row):
            return k, leg_ltp(row)

    for k in ordered_strikes:
        row = strikes.get(k)
        if row:
            return k, leg_ltp(row)

    if placement == "otm":
        return (atm + max(1, int(otm_steps)) * step) if side == "CE" else (atm - max(1, int(otm_steps)) * step), 0.0
    return atm, 0.0


def now_ist() -> datetime:
    return datetime.now(IST)


def format_hhmm(dt: datetime | None = None) -> str:
    t = dt or now_ist()
    if t.tzinfo is None:
        t = t.replace(tzinfo=IST)
    else:
        t = t.astimezone(IST)
    return t.strftime("%H:%M")
