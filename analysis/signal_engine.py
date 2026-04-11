"""
Intraday option-chain signal rules:

* BUY CE: put LTP falling, put volume *acceleration* + spike, put OI change accelerating (writing).
  **Buy strike** = ATM or **OTM CE** (above ATM) per config / spot **move**; **pattern strike** = put leg where setup fired.
* BUY PE: symmetric; **buy strike** = ATM or **OTM PE** (below ATM); **pattern strike** = call leg where setup fired.
* **Market move** over recent polls informs `smart` mode and the live OTM watch line.
* Reversal: combined OI near ATM falling while spot rises.

VWAP filter: spot above VWAP → only CE; below → only PE.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from analysis.market_move import compute_market_move
from config.settings import AnalysisParameters
from data.models import StrikeRow, StrikeSnapshot
from utils.helpers import resolve_execution_strike, strike_window

logger = logging.getLogger(__name__)


class SignalKind(str, Enum):
    BUY_CE = "BUY CE"
    BUY_PE = "BUY PE"
    REVERSAL = "POSSIBLE REVERSAL"


@dataclass(slots=True)
class Signal:
    kind: SignalKind
    strike: float | None
    reason: str
    meta: dict[str, Any] = field(default_factory=dict)


def build_snapshot(rows: list[StrikeRow], captured_at: datetime, expiry: str) -> StrikeSnapshot:
    spot = next((r.underlying_spot_price for r in rows if r.underlying_spot_price > 0), 0.0)
    return StrikeSnapshot(
        captured_at=captured_at,
        spot=spot,
        expiry=expiry,
        strikes={r.strike_price: r for r in rows},
    )


def _liquidity_ok(row: StrikeRow, p: AnalysisParameters) -> bool:
    return (
        row.call.oi >= p.min_open_interest
        and row.put.oi >= p.min_open_interest
        and row.call.volume >= p.min_volume
        and row.put.volume >= p.min_volume
    )


def _three_volume_deltas_put(history: deque[StrikeSnapshot], strike: float) -> tuple[int, int, int] | None:
    """Last three consecutive put volume deltas (oldest → newest). Requires len(history) >= 4."""
    if len(history) < 4:
        return None
    snaps = list(history)[-4:]
    d: list[int] = []
    for i in range(3):
        a = snaps[i].strikes.get(strike)
        b = snaps[i + 1].strikes.get(strike)
        if not a or not b:
            return None
        d.append(int(b.put.volume) - int(a.put.volume))
    return d[0], d[1], d[2]


def _three_oi_deltas_put(history: deque[StrikeSnapshot], strike: float) -> tuple[int, int, int] | None:
    if len(history) < 4:
        return None
    snaps = list(history)[-4:]
    out: list[int] = []
    for i in range(3):
        a = snaps[i].strikes.get(strike)
        b = snaps[i + 1].strikes.get(strike)
        if not a or not b:
            return None
        out.append(int(b.put.oi) - int(a.put.oi))
    return out[0], out[1], out[2]


def _three_volume_deltas_call(history: deque[StrikeSnapshot], strike: float) -> tuple[int, int, int] | None:
    if len(history) < 4:
        return None
    snaps = list(history)[-4:]
    d: list[int] = []
    for i in range(3):
        a = snaps[i].strikes.get(strike)
        b = snaps[i + 1].strikes.get(strike)
        if not a or not b:
            return None
        d.append(int(b.call.volume) - int(a.call.volume))
    return d[0], d[1], d[2]


def _three_oi_deltas_call(history: deque[StrikeSnapshot], strike: float) -> tuple[int, int, int] | None:
    if len(history) < 4:
        return None
    snaps = list(history)[-4:]
    out: list[int] = []
    for i in range(3):
        a = snaps[i].strikes.get(strike)
        b = snaps[i + 1].strikes.get(strike)
        if not a or not b:
            return None
        out.append(int(b.call.oi) - int(a.call.oi))
    return out[0], out[1], out[2]


def _put_price_falling(history: deque[StrikeSnapshot], strike: float) -> bool:
    if len(history) < 2:
        return False
    a = history[-2].strikes.get(strike)
    b = history[-1].strikes.get(strike)
    if not a or not b:
        return False
    return b.put.ltp < a.put.ltp


def _call_price_falling(history: deque[StrikeSnapshot], strike: float) -> bool:
    if len(history) < 2:
        return False
    a = history[-2].strikes.get(strike)
    b = history[-1].strikes.get(strike)
    if not a or not b:
        return False
    return b.call.ltp < a.call.ltp


def _volume_spike(d0: int, d1: int, d2: int, p: AnalysisParameters) -> bool:
    """Latest interval `d2` must exceed multiplier × average of prior two, with floors."""
    if d2 < p.min_volume_delta:
        return False
    if d0 < 0 or d1 < 0:
        return False
    avg = (d0 + d1) / 2.0
    if avg <= 0:
        return False
    return d2 >= p.volume_spike_multiplier * avg


def _oi_change_increasing(d0: int, d1: int, d2: int) -> bool:
    """OI increments accelerating: d2 > d1 > 0 and d1 >= d0 (non-decreasing growth)."""
    return d2 > d1 > 0 and d1 >= d0


def _bullish_put_writing(history: deque[StrikeSnapshot], strike: float, p: AnalysisParameters) -> tuple[bool, str]:
    if not _put_price_falling(history, strike):
        return False, "put LTP not falling"
    vd = _three_volume_deltas_put(history, strike)
    if vd is None:
        return False, "insufficient volume history"
    d0, d1, d2 = vd
    if not (d2 > d1 > 0):
        return False, "put volume not accelerating"
    if not _volume_spike(d0, d1, d2, p):
        return False, "no put volume spike vs prior intervals"
    od = _three_oi_deltas_put(history, strike)
    if od is None:
        return False, "insufficient OI history"
    o0, o1, o2 = od
    if not _oi_change_increasing(o0, o1, o2):
        return False, "put OI change not increasing"
    return True, "Put writing pattern (price ↓, volume ↑, OI chg ↑)"


def _bearish_call_writing(history: deque[StrikeSnapshot], strike: float, p: AnalysisParameters) -> tuple[bool, str]:
    if not _call_price_falling(history, strike):
        return False, "call LTP not falling"
    vd = _three_volume_deltas_call(history, strike)
    if vd is None:
        return False, "insufficient volume history"
    d0, d1, d2 = vd
    if not (d2 > d1 > 0):
        return False, "call volume not accelerating"
    if not _volume_spike(d0, d1, d2, p):
        return False, "no call volume spike vs prior intervals"
    od = _three_oi_deltas_call(history, strike)
    if od is None:
        return False, "insufficient OI history"
    o0, o1, o2 = od
    if not _oi_change_increasing(o0, o1, o2):
        return False, "call OI change not increasing"
    return True, "Call writing pattern (price ↓, volume ↑, OI chg ↑)"


def _combined_oi_near_atm(snap: StrikeSnapshot, spot: float, p: AnalysisParameters) -> int:
    total = 0
    for k in strike_window(spot, p.strike_step, p.reversal_oi_strikes_radius):
        row = snap.strikes.get(k)
        if not row:
            continue
        total += int(row.call.oi) + int(row.put.oi)
    return total


def _reversal(history: deque[StrikeSnapshot], p: AnalysisParameters) -> tuple[bool, str]:
    if len(history) < 2:
        return False, "need prior snapshot"
    prev, cur = history[-2], history[-1]
    if cur.spot <= prev.spot:
        return False, "spot not rising"
    oi_prev = _combined_oi_near_atm(prev, prev.spot, p)
    oi_cur = _combined_oi_near_atm(cur, cur.spot, p)
    if oi_cur >= oi_prev:
        return False, "combined OI not falling"
    return True, "OI ↓ near ATM while spot ↑"


def _normalized_buy_mode(mode: str) -> str:
    m = (mode or "otm").strip().lower()
    return m if m in ("atm", "otm", "smart") else "otm"


def _placement_for_signal(
    mode: str,
    side: Literal["CE", "PE"],
    mv: dict[str, Any],
    flat_pts: float,
) -> tuple[Literal["atm", "otm"], str]:
    """
    Returns (placement, human note for alerts).

    * smart: OTM CE only when move is clearly up; OTM PE only when clearly down; else ATM.
    """
    m = _normalized_buy_mode(mode)
    if m == "atm":
        return "atm", "ATM execution"
    if m == "otm":
        return "otm", "OTM execution"

    d = float(mv.get("delta_points") or 0.0)
    direction = str(mv.get("direction") or "flat")
    th = float(flat_pts)

    if side == "CE":
        if direction == "up" and d >= th:
            return "otm", "OTM execution (smart: spot trending up)"
        return "atm", "ATM execution (smart: flat or down move — safer delta)"

    if direction == "down" and abs(d) >= th:
        return "otm", "OTM execution (smart: spot trending down)"
    return "atm", "ATM execution (smart: flat or up move — safer delta)"


def vwap_side_ok(
    kind: Literal["CE", "PE"],
    spot: float,
    vwap: float | None,
) -> tuple[bool, str]:
    if vwap is None or vwap <= 0:
        return True, "VWAP unavailable - filter skipped"
    if kind == "CE" and spot <= vwap:
        return False, f"spot {spot:.2f} not above VWAP {vwap:.2f}"
    if kind == "PE" and spot >= vwap:
        return False, f"spot {spot:.2f} not below VWAP {vwap:.2f}"
    return True, "VWAP filter OK"


class SignalEngine:
    """Stateful engine: keeps a rolling chain history for interval deltas."""

    def __init__(self, params: AnalysisParameters) -> None:
        self._p = params
        self._history: deque[StrikeSnapshot] = deque(maxlen=32)
        self.last_market_move: dict[str, Any] = {}
        self.last_otm_watch_line: str = ""

    @property
    def history_len(self) -> int:
        return len(self._history)

    def push(self, snap: StrikeSnapshot) -> None:
        self._history.append(snap)

    def _refresh_market_context(self, vwap: float | None) -> None:
        """Spot trend + best liquid OTM CE/PE strikes for dashboard (updates each evaluate)."""
        if len(self._history) < 2:
            self.last_market_move = {}
            self.last_otm_watch_line = ""
            return
        cur = self._history[-1]
        spot = cur.spot
        if spot <= 0:
            self.last_market_move = {}
            self.last_otm_watch_line = ""
            return
        p = self._p
        mv = compute_market_move(
            self._history,
            p.market_move_lookback_snapshots,
            p.market_move_flat_threshold_points,
        )
        self.last_market_move = mv
        ce_strike, _ = resolve_execution_strike(
            cur.strikes,
            spot,
            p.strike_step,
            "CE",
            p.min_open_interest,
            p.min_volume,
            p.buy_strike_max_steps_from_atm,
            placement="otm",
            otm_steps=p.otm_strike_steps,
        )
        pe_strike, _ = resolve_execution_strike(
            cur.strikes,
            spot,
            p.strike_step,
            "PE",
            p.min_open_interest,
            p.min_volume,
            p.buy_strike_max_steps_from_atm,
            placement="otm",
            otm_steps=p.otm_strike_steps,
        )
        extra = ""
        if vwap is not None and vwap > 0:
            extra = f" | spot {'above' if spot > vwap else 'below'} VWAP"
        self.last_otm_watch_line = (
            f"move {mv.get('label', '')} | OTM CE {int(ce_strike)} | OTM PE {int(pe_strike)}{extra}"
        )

    def evaluate(self, vwap: float | None) -> list[Signal]:
        self._refresh_market_context(vwap)

        if len(self._history) < 4:
            logger.debug("Warmup: %s/4 snapshots", len(self._history))
            return []

        cur = self._history[-1]
        spot = cur.spot
        if spot <= 0:
            return []

        mv = self.last_market_move

        targets = strike_window(spot, self._p.strike_step, self._p.strike_radius)
        signals: list[Signal] = []

        # Reversal (underlying-centric)
        ok_rev, why_rev = _reversal(self._history, self._p)
        if ok_rev:
            signals.append(
                Signal(
                    kind=SignalKind.REVERSAL,
                    strike=None,
                    reason=f"{why_rev}; market {mv.get('label', '')}",
                    meta={"spot": spot, "vwap": vwap, "market_move": mv},
                )
            )

        best_ce: tuple[float, str] | None = None
        best_pe: tuple[float, str] | None = None

        for strike in targets:
            row = cur.strikes.get(strike)
            if not row or not _liquidity_ok(row, self._p):
                continue

            ok_bull, bull_reason = _bullish_put_writing(self._history, strike, self._p)
            if ok_bull:
                ok_v, vwhy = vwap_side_ok("CE", spot, vwap)
                if ok_v:
                    if best_ce is None or abs(strike - spot) < abs(best_ce[0] - spot):
                        best_ce = (strike, bull_reason + f"; {vwhy}")

            ok_bear, bear_reason = _bearish_call_writing(self._history, strike, self._p)
            if ok_bear:
                ok_v, vwhy = vwap_side_ok("PE", spot, vwap)
                if ok_v:
                    if best_pe is None or abs(strike - spot) < abs(best_pe[0] - spot):
                        best_pe = (strike, bear_reason + f"; {vwhy}")

        if best_ce:
            pattern_strike = best_ce[0]
            placement, place_note = _placement_for_signal(
                self._p.buy_strike_mode,
                "CE",
                mv,
                self._p.market_move_flat_threshold_points,
            )
            buy_strike, buy_ltp = resolve_execution_strike(
                cur.strikes,
                spot,
                self._p.strike_step,
                "CE",
                self._p.min_open_interest,
                self._p.min_volume,
                self._p.buy_strike_max_steps_from_atm,
                placement=placement,
                otm_steps=self._p.otm_strike_steps,
            )
            signals.append(
                Signal(
                    kind=SignalKind.BUY_CE,
                    strike=buy_strike,
                    reason=f"{best_ce[1]}; {place_note}; market {mv.get('label', '')}",
                    meta={
                        "spot": spot,
                        "vwap": vwap,
                        "expiry": cur.expiry,
                        "pattern_strike": pattern_strike,
                        "pattern_side": "PUT",
                        "buy_ltp": buy_ltp,
                        "buy_leg": "CE",
                        "market_move": mv,
                        "execution_placement": placement,
                        "execution_note": place_note,
                        "otm_strike_steps": self._p.otm_strike_steps,
                    },
                )
            )
        if best_pe:
            pattern_strike = best_pe[0]
            placement, place_note = _placement_for_signal(
                self._p.buy_strike_mode,
                "PE",
                mv,
                self._p.market_move_flat_threshold_points,
            )
            buy_strike, buy_ltp = resolve_execution_strike(
                cur.strikes,
                spot,
                self._p.strike_step,
                "PE",
                self._p.min_open_interest,
                self._p.min_volume,
                self._p.buy_strike_max_steps_from_atm,
                placement=placement,
                otm_steps=self._p.otm_strike_steps,
            )
            signals.append(
                Signal(
                    kind=SignalKind.BUY_PE,
                    strike=buy_strike,
                    reason=f"{best_pe[1]}; {place_note}; market {mv.get('label', '')}",
                    meta={
                        "spot": spot,
                        "vwap": vwap,
                        "expiry": cur.expiry,
                        "pattern_strike": pattern_strike,
                        "pattern_side": "CALL",
                        "buy_ltp": buy_ltp,
                        "buy_leg": "PE",
                        "market_move": mv,
                        "execution_placement": placement,
                        "execution_note": place_note,
                        "otm_strike_steps": self._p.otm_strike_steps,
                    },
                )
            )

        return signals
