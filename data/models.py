"""Typed structures for option chain rows and snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class LegMarket:
    """Call or put market fields used by the signal engine."""

    instrument_key: str
    ltp: float
    volume: int
    oi: int
    prev_oi: int

    @property
    def oi_change_session(self) -> int:
        """OI change vs exchange `prev_oi` (typically previous day close OI)."""
        return int(self.oi) - int(self.prev_oi)


@dataclass(slots=True)
class StrikeRow:
    """Single strike from the option chain."""

    strike_price: float
    underlying_spot_price: float
    call: LegMarket
    put: LegMarket
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(slots=True)
class StrikeSnapshot:
    """Point-in-time option chain slice for history / deltas."""

    captured_at: datetime
    spot: float
    expiry: str
    strikes: dict[float, StrikeRow]
