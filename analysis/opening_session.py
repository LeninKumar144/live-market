"""
Opening-session bias cards for the NIFTY dashboard.

Three IST phases:
  pre_open      — before 09:15: overnight OI map + gap cues (no session lean)
  forming_or    — 09:15–09:30: provisional future trend + forming opening range
  post_or       — at/after 09:30: confirmed OR + ΔOI vs 09:15 + future 2×2

Heuristic only — not investment advice.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

PRE_OPEN_END = time(9, 15, 0)
OR_END = time(9, 30, 0)
SESSION_END = time(15, 30, 0)


def session_phase(now: datetime | None = None) -> str:
    """Return pre_open | forming_or | post_or | after_hours."""
    n = now or datetime.now(IST)
    if n.tzinfo is None:
        n = n.replace(tzinfo=IST)
    else:
        n = n.astimezone(IST)
    t = n.time()
    if t < PRE_OPEN_END:
        return "pre_open"
    if t < OR_END:
        return "forming_or"
    if t <= SESSION_END:
        return "post_or"
    return "after_hours"


def compute_gap(
    *,
    open_px: float | None,
    prev_close: float | None,
    ltp: float | None = None,
) -> dict[str, Any]:
    """Gap from session open vs previous close (future or index)."""
    o = float(open_px) if open_px is not None else None
    pc = float(prev_close) if prev_close is not None else None
    if o is None or pc is None or pc <= 0:
        return {
            "open": o,
            "prev_close": pc,
            "gap_points": None,
            "gap_pct": None,
            "direction": "unknown",
            "label": "Gap unavailable",
        }
    pts = o - pc
    pct = (pts / pc) * 100.0
    if abs(pts) < 1.0:
        direction = "flat"
        label = f"Flat open ({pts:+.1f} pts)"
    elif pts > 0:
        direction = "gap_up"
        label = f"Gap up {pts:+.1f} pts ({pct:+.2f}%)"
    else:
        direction = "gap_down"
        label = f"Gap down {pts:+.1f} pts ({pct:+.2f}%)"
    return {
        "open": round(o, 2),
        "prev_close": round(pc, 2),
        "ltp": round(float(ltp), 2) if ltp is not None else None,
        "gap_points": round(pts, 2),
        "gap_pct": round(pct, 3),
        "direction": direction,
        "label": label,
    }


def compute_opening_range(
    bars: list[tuple[datetime, float, float, float, float, int]],
    *,
    minutes: int,
) -> dict[str, Any]:
    """
    High/low of first `minutes` of the cash session from 1-minute bars.

    `bars`: (t, o, h, l, c, v) with IST-aware datetimes.
    """
    if minutes <= 0:
        return _empty_or(minutes)
    win_start = PRE_OPEN_END
    # Inclusive end: 09:15 + N minutes → for 15m use bars with t < 09:30
    end_h = 9
    end_m = 15 + minutes
    if end_m >= 60:
        end_h += end_m // 60
        end_m = end_m % 60
    win_end = time(end_h, end_m, 0)

    highs: list[float] = []
    lows: list[float] = []
    opens: list[float] = []
    closes: list[float] = []
    n = 0
    for t, o, h, low, c, _v in bars:
        tt = t.astimezone(IST).time() if t.tzinfo else t.replace(tzinfo=IST).time()
        if tt < win_start:
            continue
        if tt >= win_end:
            break
        highs.append(float(h))
        lows.append(float(low))
        opens.append(float(o))
        closes.append(float(c))
        n += 1

    if not highs:
        return _empty_or(minutes)

    or_h = max(highs)
    or_l = min(lows)
    or_o = opens[0]
    or_c = closes[-1]
    mid = (or_h + or_l) / 2.0
    if or_c > or_h - (or_h - or_l) * 0.25 and or_c >= or_o:
        close_pos = "near_high"
    elif or_c < or_l + (or_h - or_l) * 0.25 and or_c <= or_o:
        close_pos = "near_low"
    else:
        close_pos = "mid_range"

    return {
        "minutes": minutes,
        "ready": n >= max(1, minutes // 2),  # soft: half the bars is enough to show
        "complete": n >= max(1, minutes - 1),
        "bar_count": n,
        "high": round(or_h, 2),
        "low": round(or_l, 2),
        "open": round(or_o, 2),
        "close": round(or_c, 2),
        "mid": round(mid, 2),
        "range_points": round(or_h - or_l, 2),
        "close_position": close_pos,
    }


def _empty_or(minutes: int) -> dict[str, Any]:
    return {
        "minutes": minutes,
        "ready": False,
        "complete": False,
        "bar_count": 0,
        "high": None,
        "low": None,
        "open": None,
        "close": None,
        "mid": None,
        "range_points": None,
        "close_position": "unknown",
    }


def open_vs_walls(
    *,
    ref_price: float | None,
    support_strike: int | None,
    resistance_strike: int | None,
) -> dict[str, Any]:
    """Where open/spot sits vs overnight PE/CE walls."""
    if ref_price is None or ref_price <= 0:
        return {
            "zone": "unknown",
            "label": "Need open/spot vs OI walls",
            "support_strike": support_strike,
            "resistance_strike": resistance_strike,
        }
    s = support_strike
    r = resistance_strike
    px = float(ref_price)
    if s is not None and r is not None and s < r:
        if px >= r:
            zone = "above_resistance"
            label = f"Open/spot above CE wall {r} — chase vs fade at overhead"
        elif px <= s:
            zone = "below_support"
            label = f"Open/spot below PE wall {s} — bounce vs continuation lower"
        else:
            zone = "inside_range"
            label = f"Inside PE {s} – CE {r} overnight range"
    elif r is not None and px >= r:
        zone = "above_resistance"
        label = f"At/above CE wall {r}"
    elif s is not None and px <= s:
        zone = "below_support"
        label = f"At/below PE wall {s}"
    else:
        zone = "unmapped"
        label = "Walls incomplete — use nearest OI levels"
    return {
        "zone": zone,
        "label": label,
        "support_strike": s,
        "resistance_strike": r,
        "ref_price": round(px, 2),
    }


def session_doi_vs_anchor(
    *,
    now_ce: int,
    now_pe: int,
    early_ce: int | None,
    early_pe: int | None,
) -> dict[str, Any]:
    """Σ CE/PE OI change since the 09:15 chain anchor (not vs prev close)."""
    if early_ce is None or early_pe is None:
        return {
            "available": False,
            "ce_doi": None,
            "pe_doi": None,
            "net_ce_minus_pe": None,
            "bias": "awaiting_915_anchor",
            "label": "Needs first chain snapshot in 09:15–09:30",
        }
    ce_d = int(now_ce) - int(early_ce)
    pe_d = int(now_pe) - int(early_pe)
    net = ce_d - pe_d
    if net > 25_000:
        bias = "call_side_adding"
        label = f"Since 09:15: CE ΔOI {ce_d:+,} vs PE {pe_d:+,} — call side leading"
    elif net < -25_000:
        bias = "put_side_adding"
        label = f"Since 09:15: PE ΔOI {pe_d:+,} vs CE {ce_d:+,} — put side leading"
    else:
        bias = "balanced"
        label = f"Since 09:15: CE ΔOI {ce_d:+,} · PE ΔOI {pe_d:+,} — balanced"
    return {
        "available": True,
        "ce_doi": ce_d,
        "pe_doi": pe_d,
        "net_ce_minus_pe": net,
        "bias": bias,
        "label": label,
        "early_ce_oi": int(early_ce),
        "early_pe_oi": int(early_pe),
    }


def price_vs_or(ltp: float | None, or_block: dict[str, Any]) -> dict[str, Any]:
    if ltp is None or not or_block.get("ready") or or_block.get("high") is None:
        return {"state": "unknown", "label": "OR not ready"}
    h = float(or_block["high"])
    low = float(or_block["low"])
    px = float(ltp)
    if px > h:
        return {"state": "above_or_high", "label": f"Above OR high {h:.0f}"}
    if px < low:
        return {"state": "below_or_low", "label": f"Below OR low {low:.0f}"}
    return {"state": "inside_or", "label": f"Inside OR {low:.0f}–{h:.0f}"}


def _headline_pre_open(
    gap: dict[str, Any],
    walls: dict[str, Any],
    vix: dict[str, Any] | None,
    pcr: float | None,
) -> tuple[str, str, list[str]]:
    lines: list[str] = []
    lines.append(gap.get("label") or "Gap unknown")
    lines.append(walls.get("label") or "OI walls unknown")
    if pcr is not None:
        tone = "bearish overnight PCR" if pcr < 0.9 else ("bullish overnight PCR" if pcr > 1.1 else "neutral overnight PCR")
        lines.append(f"Overnight PCR {pcr:.2f} ({tone}) — positioning map, not today’s trend.")
    if vix and vix.get("ltp") is not None:
        ch = vix.get("net_change")
        ch_s = f" ({ch:+.2f})" if ch is not None else ""
        lines.append(f"India VIX {float(vix['ltp']):.2f}{ch_s} — wider first-15m range when elevated.")

    zone = walls.get("zone")
    gdir = gap.get("direction")
    if gdir == "gap_up" and zone == "above_resistance":
        key, head = "fade_watch", "Pre-open: gap into CE wall — fade watch"
    elif gdir == "gap_down" and zone == "below_support":
        key, head = "bounce_watch", "Pre-open: gap under PE wall — bounce watch"
    elif gdir == "gap_up":
        key, head = "gap_up_bias", "Pre-open: gap-up bias — wait for OR"
    elif gdir == "gap_down":
        key, head = "gap_down_bias", "Pre-open: gap-down bias — wait for OR"
    else:
        key, head = "wait_or", "Pre-open: wait for 09:15–09:30 opening range"
    lines.append("No session lean until the opening range forms.")
    return key, head, lines


def _headline_forming(
    gap: dict[str, Any],
    opening_trend_label: str,
    or15: dict[str, Any],
    vs_or: dict[str, Any],
    doi: dict[str, Any],
) -> tuple[str, str, list[str]]:
    lines: list[str] = [gap.get("label") or "Gap unknown"]
    if opening_trend_label:
        lines.append(f"Future vs 09:15: {opening_trend_label} (provisional).")
    if or15.get("ready"):
        lines.append(
            f"15m OR forming: {or15['low']:.0f}–{or15['high']:.0f} "
            f"({or15.get('bar_count', 0)} bars) · {vs_or.get('label')}"
        )
    else:
        lines.append("Opening range still forming — need 1-minute future bars.")
    if doi.get("available"):
        lines.append(str(doi.get("label")))
    key = "provisional"
    head = "0–15 min: provisional open read"
    ot = (opening_trend_label or "").lower()
    st = vs_or.get("state")
    if "long buildup" in ot and st == "above_or_high":
        key, head = "lean_up_prov", "Provisional: strength above OR (unconfirmed)"
    elif "short buildup" in ot and st == "below_or_low":
        key, head = "lean_down_prov", "Provisional: weakness below OR (unconfirmed)"
    elif st == "inside_or":
        key, head = "range_prov", "Provisional: two-way inside forming OR"
    return key, head, lines


def _headline_post(
    opening_trend_key: str,
    opening_trend_label: str,
    or15: dict[str, Any],
    vs_or: dict[str, Any],
    doi: dict[str, Any],
    gap: dict[str, Any],
) -> tuple[str, str, list[str]]:
    lines: list[str] = []
    if opening_trend_label:
        lines.append(f"09:15–09:30 future: {opening_trend_label}.")
    if or15.get("complete") or or15.get("ready"):
        lines.append(
            f"15m OR {or15['low']:.0f}–{or15['high']:.0f} "
            f"(range {or15.get('range_points')} pts) · close pos {or15.get('close_position')} · {vs_or.get('label')}"
        )
    if doi.get("available"):
        lines.append(str(doi.get("label")))
    lines.append(gap.get("label") or "")

    st = vs_or.get("state")
    ot = opening_trend_key or ""
    db = doi.get("bias") or ""

    up = 0
    down = 0
    if ot == "long_buildup":
        up += 2
    elif ot == "short_buildup":
        down += 2
    elif ot == "short_covering":
        up += 1
    elif ot == "profit_booking":
        down += 1
    if st == "above_or_high":
        up += 2
    elif st == "below_or_low":
        down += 2
    if db == "put_side_adding":
        up += 1
    elif db == "call_side_adding":
        down += 1

    if up - down >= 3:
        key, head = "lean_up", "Post 09:30: trend-up bias until OR low breaks"
    elif down - up >= 3:
        key, head = "lean_down", "Post 09:30: trend-down bias until OR high breaks"
    elif st == "inside_or":
        key, head = "range", "Post 09:30: range day lean — trade OR edges"
    else:
        key, head = "mixed", "Post 09:30: mixed — wait for OR acceptance"
    return key, head, [x for x in lines if x]


def build_opening_session(
    *,
    now: datetime | None = None,
    spot: float,
    pcr: float | None,
    total_ce_oi: int,
    total_pe_oi: int,
    nifty_future: dict[str, Any] | None,
    opening_window_today: dict[str, Any] | None,
    sr_bundle: dict[str, Any] | None,
    future_1m_bars: list[tuple[datetime, float, float, float, float, int]] | None,
    india_vix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    n = now or datetime.now(IST)
    if n.tzinfo is None:
        n = n.replace(tzinfo=IST)
    else:
        n = n.astimezone(IST)
    phase = session_phase(n)

    nf = nifty_future if isinstance(nifty_future, dict) else {}
    open_px = nf.get("ohlc_open")
    # Upstox quote ohlc.close is typically previous close / reference close for the session.
    prev_close = nf.get("ohlc_close")
    ltp = nf.get("ltp")
    gap = compute_gap(open_px=open_px, prev_close=prev_close, ltp=ltp if ltp is not None else spot)

    intraday = (sr_bundle or {}).get("intraday") if isinstance(sr_bundle, dict) else None
    supports = (intraday or {}).get("supports") if isinstance(intraday, dict) else []
    resistances = (intraday or {}).get("resistances") if isinstance(intraday, dict) else []
    top_s = int(supports[0]["strike"]) if supports and isinstance(supports[0], dict) else None
    top_r = int(resistances[0]["strike"]) if resistances and isinstance(resistances[0], dict) else None
    ref = float(open_px) if open_px is not None else (float(spot) if spot else None)
    walls = open_vs_walls(ref_price=ref, support_strike=top_s, resistance_strike=top_r)

    bars = future_1m_bars or []
    or5 = compute_opening_range(bars, minutes=5)
    or15 = compute_opening_range(bars, minutes=15)
    px_now = float(ltp) if ltp is not None else (float(spot) if spot else None)
    vs_or5 = price_vs_or(px_now, or5)
    vs_or15 = price_vs_or(px_now, or15)

    ow = opening_window_today if isinstance(opening_window_today, dict) else {}
    chain_early = ow.get("chain_early") if isinstance(ow.get("chain_early"), dict) else None
    early_ce = int(chain_early["total_ce_oi"]) if chain_early and chain_early.get("total_ce_oi") is not None else None
    early_pe = int(chain_early["total_pe_oi"]) if chain_early and chain_early.get("total_pe_oi") is not None else None
    doi = session_doi_vs_anchor(
        now_ce=int(total_ce_oi),
        now_pe=int(total_pe_oi),
        early_ce=early_ce,
        early_pe=early_pe,
    )

    # Opening future trend (final or provisional)
    trend_key = ""
    trend_label = ""
    provisional = False
    if ow.get("ready") and ow.get("trend_key"):
        trend_key = str(ow.get("trend_key") or "")
        trend_label = str(ow.get("trend_label") or "")
    elif isinstance(ow.get("provisional"), dict) and ow["provisional"].get("trend_key"):
        trend_key = str(ow["provisional"].get("trend_key") or "")
        trend_label = str(ow["provisional"].get("trend_label") or "") + " (live vs 09:15)"
        provisional = True

    if phase == "pre_open":
        bias_key, headline, detail_lines = _headline_pre_open(gap, walls, india_vix, pcr)
    elif phase == "forming_or":
        bias_key, headline, detail_lines = _headline_forming(gap, trend_label, or15, vs_or15, doi)
    else:
        # post_or and after_hours share confirmed card; after hours still show last read
        bias_key, headline, detail_lines = _headline_post(
            trend_key, trend_label, or15, vs_or15, doi, gap
        )

    phase_labels = {
        "pre_open": "Pre-open / at the bell",
        "forming_or": "0–15 minutes (provisional)",
        "post_or": "After 09:30 (confirmed OR)",
        "after_hours": "After hours (last session read)",
    }

    return {
        "disclaimer": (
            "Opening-session heuristic from gap, overnight OI walls, India VIX, "
            "09:15–09:30 future OI/price, and ΔOI vs 09:15 — not advice."
        ),
        "phase": phase,
        "phase_label": phase_labels.get(phase, phase),
        "as_of": n.isoformat(timespec="seconds"),
        "bias_key": bias_key,
        "headline": headline,
        "detail_lines": detail_lines,
        "gap": gap,
        "overnight_walls": {
            **walls,
            "pcr": round(float(pcr), 4) if pcr is not None else None,
            "note": "Overnight / carry-in OI map — not session ΔOI.",
        },
        "india_vix": india_vix,
        "opening_range_5m": or5,
        "opening_range_15m": or15,
        "price_vs_or_5m": vs_or5,
        "price_vs_or_15m": vs_or15,
        "future_trend": {
            "trend_key": trend_key,
            "trend_label": trend_label,
            "is_provisional": provisional,
            "ready": bool(ow.get("ready")),
        },
        "session_doi_vs_915": doi,
        "gift_nifty": {
            "available": False,
            "note": "GIFT Nifty not wired via Upstox in this build — use gap + VIX as open cues.",
        },
    }
