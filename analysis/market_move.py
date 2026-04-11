"""Underlying spot trend from recent option-chain snapshots (same cadence as polls)."""

from __future__ import annotations

from collections import deque
from typing import Any, Literal

from data.models import StrikeSnapshot

Direction = Literal["up", "down", "flat"]


def compute_market_move(
    history: deque[StrikeSnapshot],
    lookback_snapshots: int,
    flat_threshold_points: float,
) -> dict[str, Any]:
    """
    Compare oldest vs newest spot in the last `lookback_snapshots` frames.

    Returns dict: direction, delta_points, delta_pct, n_snapshots, from_spot, to_spot.
    """
    lb = max(2, int(lookback_snapshots))
    if len(history) < 2:
        return {
            "direction": "flat",
            "delta_points": 0.0,
            "delta_pct": 0.0,
            "n_snapshots": len(history),
            "from_spot": 0.0,
            "to_spot": 0.0,
            "label": "warmup",
        }

    snaps = list(history)[-lb:]
    o = float(snaps[0].spot)
    n = float(snaps[-1].spot)
    d = n - o
    pct = (d / o * 100.0) if o > 0 else 0.0
    th = float(flat_threshold_points)

    if abs(d) < th:
        direction: Direction = "flat"
    elif d > 0:
        direction = "up"
    else:
        direction = "down"

    sign = "+" if d >= 0 else ""
    label = f"{sign}{d:.1f} pts ({direction})"
    return {
        "direction": direction,
        "delta_points": d,
        "delta_pct": pct,
        "n_snapshots": len(snaps),
        "from_spot": o,
        "to_spot": n,
        "label": label,
    }
