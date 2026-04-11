"""
Heuristic: combine Σ CE / Σ PE / PCR / session ΔOI with recent NIFTY future 1m candles.

Not investment advice — rule-based pattern tags + level-style entry / exit / stop from structure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class Bar:
    t: datetime
    o: float
    h: float
    l: float
    c: float
    v: int


def _body(o: float, h: float, l: float, c: float) -> tuple[float, float, float, float]:
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    rng = max(h - l, 1e-9)
    return body, upper, lower, rng


def detect_pattern(bars: list[Bar]) -> tuple[str, str]:
    """Return (pattern_name, pattern_detail)."""
    if len(bars) < 2:
        return ("insufficient_bars", "Need at least two 1-minute bars.")
    a, b = bars[-2], bars[-1]
    bo, bh, bl, bc = b.o, b.h, b.l, b.c
    ao, ah, al, ac = a.o, a.h, a.l, a.c

    bb, bu, b_low, br = _body(bo, bh, bl, bc)
    ab, au, a_low, _ = _body(ao, ah, al, ac)

    # Engulfing
    a_bear = ac < ao
    a_bull = ac > ao
    b_bull = bc > bo
    b_bear = bc < bo
    if a_bear and b_bull and bo < ac and bc > ao and bb > ab * 0.9:
        return ("bullish_engulfing", "Current bar fully engulfs prior bearish body — intraday long bias.")
    if a_bull and b_bear and bo > ac and bc < ao and bb > ab * 0.9:
        return ("bearish_engulfing", "Current bar fully engulfs prior bullish body — intraday short bias.")

    # Hammer / shooting star (last bar)
    if bb > 1e-6:
        if b_low >= 2.0 * bb and bu <= 0.5 * bb and bc >= bo:
            return ("hammer", "Long lower wick vs small real body — potential bullish rejection at lows.")
        if bu >= 2.0 * bb and b_low <= 0.5 * bb and bc <= bo:
            return ("shooting_star", "Long upper wick vs small real body — potential bearish rejection at highs.")

    # Simple trend tag from last 3 closes
    if len(bars) >= 3:
        c0, c1, c2 = bars[-3].c, bars[-2].c, bars[-1].c
        if c2 > c1 > c0:
            return ("higher_closes", "Last three closes rising — short-term upward sequence.")
        if c2 < c1 < c0:
            return ("lower_closes", "Last three closes falling — short-term downward sequence.")

    if bc > bo:
        return ("bullish_bar", "Last bar closed above its open — mild bullish candle.")
    if bc < bo:
        return ("bearish_bar", "Last bar closed below its open — mild bearish candle.")
    return ("doji_like", "Last bar is roughly neutral (open ≈ close).")


def _volume_flow_score(
    ce_vol_delta: int | None,
    pe_vol_delta: int | None,
    total_call_volume: int | None,
    total_put_volume: int | None,
) -> tuple[float, float, list[str]]:
    """
    Live volume tilt: poll-to-poll Σ CE vs Σ PE volume deltas, plus session CE share of total traded volume.

    Returns (long_points, short_points, human_lines for UI / narrative).
    """
    lines: list[str] = []
    sl = ss = 0.0
    if ce_vol_delta is not None and pe_vol_delta is not None:
        net_d = int(ce_vol_delta) - int(pe_vol_delta)
        lines.append(
            f"Live Σ CE Δvol vs Σ PE Δvol (since last chain poll): {ce_vol_delta:+,} vs {pe_vol_delta:+,} (net {net_d:+,})."
        )
        scale = max(abs(ce_vol_delta) + abs(pe_vol_delta), 1)
        thr = max(50_000, int(0.035 * scale))
        if net_d > thr:
            sl += 0.65
            lines.append("Last refresh: CE-side volume built faster than PE — tape supportive for upside / call activity.")
        elif net_d < -thr:
            ss += 0.65
            lines.append("Last refresh: PE-side volume built faster than CE — tape supportive for downside / hedge flow.")
        else:
            lines.append("Last refresh: CE vs PE volume deltas are modest — do not overweight a single poll.")
    if (
        total_call_volume is not None
        and total_put_volume is not None
        and (int(total_call_volume) + int(total_put_volume)) > 0
    ):
        tcv = int(total_call_volume)
        tpv = int(total_put_volume)
        tot = tcv + tpv
        share_ce = tcv / tot
        lines.append(
            f"Session chain volume mix: Σ CE {tcv:,} vs Σ PE {tpv:,} ({share_ce * 100:.1f}% of Σ vol on CE)."
        )
        if share_ce > 0.57:
            sl += 0.4
        elif share_ce < 0.43:
            ss += 0.4
    return sl, ss, lines


def _volume_entry_alignment_note(
    side: str,
    ce_vol_delta: int | None,
    pe_vol_delta: int | None,
) -> str:
    if ce_vol_delta is None or pe_vol_delta is None:
        return ""
    net = int(ce_vol_delta) - int(pe_vol_delta)
    thr = max(40_000, int(0.03 * (abs(ce_vol_delta) + abs(pe_vol_delta) + 1)))
    if side == "long":
        if net >= thr:
            return " Volume confirmation: CE led the last poll’s Δvol vs PE — consistent with the long bias."
        if net <= -thr:
            return " Volume caution: PE led the last poll’s Δvol — consider smaller size or wait for candle / price confirmation."
    if side == "short":
        if net <= -thr:
            return " Volume confirmation: PE led the last poll’s Δvol vs CE — consistent with the short bias."
        if net >= thr:
            return " Volume caution: CE led the last poll’s Δvol — consider smaller size or wait for candle / price confirmation."
    return ""


def _pivot_r1_s1(sr_levels: dict[str, Any] | None) -> tuple[float | None, float | None]:
    if not isinstance(sr_levels, dict):
        return None, None
    intra = sr_levels.get("intraday")
    if not isinstance(intra, dict):
        return None, None
    piv = intra.get("pivot_levels")
    if not isinstance(piv, dict):
        return None, None
    try:
        r1 = float(piv["r1"]) if piv.get("r1") is not None else None
    except (TypeError, ValueError):
        r1 = None
    try:
        s1 = float(piv["s1"]) if piv.get("s1") is not None else None
    except (TypeError, ValueError):
        s1 = None
    return r1, s1


def build_trade_plan(
    bars: list[Bar],
    *,
    pcr: float | None,
    total_call_oi: int | None,
    total_put_oi: int | None,
    total_call_volume: int | None,
    total_put_volume: int | None,
    ce_doi: int,
    pe_doi: int,
    ce_vol_delta_since_last_poll: int | None,
    pe_vol_delta_since_last_poll: int | None,
    bias: str,
    net_cp: int,
    ltp: float,
    sr_levels: dict[str, Any] | None,
    spot: float = 0.0,
    has_future_instrument: bool = True,
) -> dict[str, Any]:
    pattern_name, pattern_detail = detect_pattern(bars)
    r1, s1 = _pivot_r1_s1(sr_levels)

    def chain_snapshot() -> dict[str, Any]:
        return {
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "total_call_volume": total_call_volume,
            "total_put_volume": total_put_volume,
            "total_ce_oi_change": ce_doi,
            "total_pe_oi_change": pe_doi,
            "total_ce_volume_change_since_last_poll": ce_vol_delta_since_last_poll,
            "total_pe_volume_change_since_last_poll": pe_vol_delta_since_last_poll,
        }

    vl, vs, vol_lines = _volume_flow_score(
        ce_vol_delta_since_last_poll,
        pe_vol_delta_since_last_poll,
        total_call_volume,
        total_put_volume,
    )
    oi_lines = [
        f"PCR (PE/CE OI): {pcr:.4f}" if pcr is not None else "PCR (PE/CE OI): —",
        f"Chain OI bias: {bias or '—'} · net (CE−PE) ΔOI: {net_cp:+,}",
        *vol_lines,
    ]

    if not bars:
        score_long = float(vl)
        score_short = float(vs)
        if bias == "call_side_adding":
            score_long += 1.5
        elif bias == "put_side_adding":
            score_short += 1.5
        if net_cp > 0:
            score_long += 0.75
        elif net_cp < 0:
            score_short += 0.75
        if pcr is not None:
            if pcr >= 1.12:
                score_short += 0.5
            if pcr <= 0.88:
                score_long += 0.5

        diff = score_long - score_short
        tick = 0.05
        head = (
            "NIFTY index future is not in the OI cache — this read uses only Σ CE/PE OI, ΔOI, PCR, and live volume deltas."
            if not has_future_instrument
            else "No 1-minute future bars in this response — read uses option-chain OI, ΔOI, PCR, and live volume only."
        )
        chart_narrative = f"{head} {' '.join(vol_lines) if vol_lines else ''}".strip()
        pattern_name = "chain_only" if not has_future_instrument else "awaiting_candles"
        pattern_detail = (
            "Candle patterns skipped; entry/exit anchors use spot vs pivots plus Σ CE/PE volume & ΔOI."
            if not has_future_instrument
            else "Minute futures not in this response; lean from chain + live volume until candles load."
        )

        sp = float(spot or 0.0)
        if sp <= 0:
            return {
                **chain_snapshot(),
                "side": "flat",
                "trend_summary": "Need a valid spot from the chain to anchor chain-only entry levels.",
                "pattern_name": pattern_name,
                "pattern_detail": pattern_detail,
                "entry_price": None,
                "entry_time_iso_ist": None,
                "entry_trigger": "Refresh OI after the market is open so spot and volumes populate.",
                "exit_price": None,
                "exit_label": "",
                "stop_loss": None,
                "oi_metric_lines": oi_lines,
                "chart_narrative": chart_narrative,
                "disclaimer": "Educational synthesis only — not a trade recommendation.",
            }

        if abs(diff) < 1.0:
            return {
                **chain_snapshot(),
                "side": "flat",
                "trend_summary": "Chain OI, ΔOI, PCR, and live volume do not line up for a directional lean without candles.",
                "pattern_name": pattern_name,
                "pattern_detail": pattern_detail,
                "entry_price": round(sp, 2),
                "entry_time_iso_ist": None,
                "entry_trigger": (
                    f"Stand aside for direction; watch spot {sp:.2f} vs pivot / OI walls. "
                    "When Σ CE Δvol vs Σ PE Δvol diverges clearly on the next polls, revisit bias."
                ),
                "exit_price": round(max(r1, sp + 10), 2) if r1 is not None else round(sp + 12, 2),
                "exit_label": "Illustrative upside probe only — needs futures candle confirmation.",
                "stop_loss": round(min(s1, sp - 10), 2) if s1 is not None else round(sp - 12, 2),
                "oi_metric_lines": oi_lines,
                "chart_narrative": chart_narrative,
                "disclaimer": "Educational synthesis only — not a trade recommendation.",
            }

        if diff > 0:
            side = "long"
            entry = round(sp, 2)
            exit_px = round(max(r1, sp + 15), 2) if r1 is not None else round(sp + 18, 2)
            stop = round(min(s1, sp - 12) - tick, 2) if s1 is not None else round(sp - 15, 2)
            summ = "Leaning long from Σ CE/PE ΔOI, PCR, and live volume mix (no 1m future overlay)."
            trig = (
                f"Chain/volume long lean: scale-in anchor near spot {entry:.2f}; "
                f"target toward {exit_px:.2f} (pivot R1 or fixed extension); stop near {stop:.2f}. "
                "Confirm with NIFTY future candles when the chart loads."
            )
            trig += _volume_entry_alignment_note("long", ce_vol_delta_since_last_poll, pe_vol_delta_since_last_poll)
        else:
            side = "short"
            entry = round(sp, 2)
            exit_px = round(min(s1, sp - 15), 2) if s1 is not None else round(sp - 18, 2)
            stop = round(max(r1, sp + 12) + tick, 2) if r1 is not None else round(sp + 15, 2)
            summ = "Leaning short from Σ CE/PE ΔOI, PCR, and live volume mix (no 1m future overlay)."
            trig = (
                f"Chain/volume short lean: anchor near spot {entry:.2f}; "
                f"target toward {exit_px:.2f} (pivot S1 or fixed extension); stop near {stop:.2f}. "
                "Confirm with NIFTY future candles when the chart loads."
            )
            trig += _volume_entry_alignment_note("short", ce_vol_delta_since_last_poll, pe_vol_delta_since_last_poll)

        exit_label = "Targets use prior-session pivots when available; otherwise fixed spot offsets — not guaranteed fills."
        return {
            **chain_snapshot(),
            "side": side,
            "trend_summary": summ,
            "pattern_name": pattern_name,
            "pattern_detail": pattern_detail,
            "entry_price": entry,
            "entry_time_iso_ist": None,
            "entry_trigger": trig,
            "exit_price": exit_px,
            "exit_label": exit_label,
            "stop_loss": stop,
            "oi_metric_lines": oi_lines,
            "chart_narrative": chart_narrative,
            "disclaimer": "Educational synthesis only — not a trade recommendation.",
        }

    last = bars[-1]
    last_ist = last.t.astimezone(IST) if last.t.tzinfo else last.t.replace(tzinfo=IST)
    entry_time_iso = last_ist.isoformat(timespec="seconds")

    recent = bars[-min(len(bars), 30) :]
    swing_hi = max(x.h for x in recent)
    swing_lo = min(x.l for x in recent)
    mid = (swing_hi + swing_lo) / 2.0

    score_long = float(vl)
    score_short = float(vs)

    if pattern_name in ("bullish_engulfing", "hammer", "higher_closes", "bullish_bar"):
        score_long += 2 if pattern_name in ("bullish_engulfing", "hammer") else 1
    if pattern_name in ("bearish_engulfing", "shooting_star", "lower_closes", "bearish_bar"):
        score_short += 2 if pattern_name in ("bearish_engulfing", "shooting_star") else 1

    if bias == "call_side_adding":
        score_long += 1.5
    elif bias == "put_side_adding":
        score_short += 1.5

    if net_cp > 0:
        score_long += 0.75
    elif net_cp < 0:
        score_short += 0.75

    if pcr is not None:
        if pcr >= 1.12:
            score_short += 0.5
        if pcr <= 0.88:
            score_long += 0.5

    diff = score_long - score_short
    tick = 0.05

    narrative_parts = [
        f"Pattern: {pattern_name.replace('_', ' ')} — {pattern_detail}",
        f"Last 30-bar range on future: {swing_lo:.2f} – {swing_hi:.2f} (mid {mid:.2f}).",
    ]
    narrative_parts.extend(vol_lines)
    if r1 is not None and s1 is not None:
        narrative_parts.append(f"Prior-session pivot anchors (index intraday bundle): R1 ≈ {r1:.2f}, S1 ≈ {s1:.2f}.")

    if abs(diff) < 1.0:
        return {
            **chain_snapshot(),
            "side": "flat",
            "trend_summary": "Option OI flow and last candles disagree or are neutral — no single edge.",
            "pattern_name": pattern_name,
            "pattern_detail": pattern_detail,
            "entry_price": round(last.c, 2),
            "entry_time_iso_ist": entry_time_iso,
            "entry_trigger": f"Stand aside unless price breaks {swing_hi:.2f} (bullish) or {swing_lo:.2f} (bearish) with follow-through.",
            "exit_price": round(mid, 2),
            "exit_label": "Mean reversion toward session mid-range if a breakout fails.",
            "stop_loss": None,
            "oi_metric_lines": oi_lines,
            "chart_narrative": " ".join(narrative_parts),
            "disclaimer": "Educational synthesis only — not a trade recommendation.",
        }

    if diff > 0:
        side = "long"
        entry = round(last.c, 2)
        stop = round(min(last.l, last.c) - 2 * tick - 1.0, 2)
        tgt_candidates = [swing_hi]
        if r1 is not None and r1 > entry:
            tgt_candidates.append(r1)
        exit_px = round(max(tgt_candidates), 2)
        trig = (
            f"Long bias: enter at or near last 1m close {entry:.2f} (IST bar ending {entry_time_iso}); "
            f"confirmation if price holds above {mid:.2f}."
        )
        summ = (
            "Leaning long — candles, chain ΔOI / PCR, and live Σ CE vs Σ PE volume flow favour buyers on the future."
        )
        trig += _volume_entry_alignment_note("long", ce_vol_delta_since_last_poll, pe_vol_delta_since_last_poll)
    else:
        side = "short"
        entry = round(last.c, 2)
        stop = round(max(last.h, last.c) + 2 * tick + 1.0, 2)
        tgt_candidates = [swing_lo]
        if s1 is not None and s1 < entry:
            tgt_candidates.append(s1)
        exit_px = round(min(tgt_candidates), 2)
        trig = (
            f"Short bias: enter at or near last 1m close {entry:.2f} (IST bar ending {entry_time_iso}); "
            f"confirmation if price rejects below {mid:.2f}."
        )
        summ = (
            "Leaning short — candles, chain ΔOI / PCR, and live Σ CE vs Σ PE volume flow favour sellers on the future."
        )
        trig += _volume_entry_alignment_note("short", ce_vol_delta_since_last_poll, pe_vol_delta_since_last_poll)

    if side == "long" and exit_px <= entry:
        exit_px = round(entry + max(swing_hi - entry, 5.0), 2)
    if side == "short" and exit_px >= entry:
        exit_px = round(entry - max(entry - swing_lo, 5.0), 2)

    exit_label = "Target = nearer of recent swing or pivot S1/R1 (see narrative)." if r1 or s1 else "Target = recent swing level from last 30 bars."

    return {
        **chain_snapshot(),
        "side": side,
        "trend_summary": summ,
        "pattern_name": pattern_name,
        "pattern_detail": pattern_detail,
        "entry_price": entry,
        "entry_time_iso_ist": entry_time_iso,
        "entry_trigger": trig,
        "exit_price": exit_px,
        "exit_label": exit_label,
        "stop_loss": stop,
        "oi_metric_lines": oi_lines,
        "chart_narrative": " ".join(narrative_parts),
        "disclaimer": "Educational synthesis only — not a trade recommendation.",
    }


def bars_from_tuples(
    rows: list[tuple[datetime, float, float, float, float, int]],
) -> list[Bar]:
    out: list[Bar] = []
    for t, o, h, low, c, v in rows:
        if not all(math.isfinite(x) for x in (o, h, low, c)):
            continue
        if h < max(o, c) or low > min(o, c):
            continue
        out.append(Bar(t=t, o=o, h=h, l=low, c=c, v=int(v or 0)))
    return out
