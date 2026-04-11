"""
Live, OI-only heuristics: session bias from opening-window future trend + option OI / ΔOI vs walls.

Not investment advice — uses exchange prev_oi vs current OI and intraday OI walls from the chain.
"""

from __future__ import annotations

from typing import Any

from data.models import StrikeRow


def _threshold_from_oi(oi: int) -> int:
    """Minimum |ΔOI| to treat as meaningful vs noise at a wall."""
    return max(2500, int(0.004 * max(oi, 1)))


def _strike_row(strikes_map: dict[float, StrikeRow], strike: int) -> StrikeRow | None:
    k = float(strike)
    return strikes_map.get(k)


def _opening_bias_scores(opening: dict[str, Any] | None) -> tuple[int, int, str, str]:
    """Return (up_pts, down_pts, trend_key, trend_label)."""
    if not opening or not isinstance(opening, dict):
        return 0, 0, "", ""
    if opening.get("ready") and opening.get("trend_key"):
        k = str(opening.get("trend_key") or "")
        lab = str(opening.get("trend_label") or "")
    elif opening.get("provisional") and isinstance(opening["provisional"], dict):
        k = str(opening["provisional"].get("trend_key") or "")
        lab = str(opening["provisional"].get("trend_label") or "") + " (live vs 09:15 anchor)"
    else:
        return 0, 0, "", ""

    up = down = 0
    if k == "long_buildup":
        up += 3
    elif k == "short_buildup":
        down += 3
    elif k == "profit_booking":
        down += 1
        up += 0
    elif k == "short_covering":
        up += 2
    elif k.startswith("neutral"):
        pass
    return up, down, k, lab


def _wall_signals_for_horizon(
    horizon_name: str,
    horizon: dict[str, Any] | None,
    strikes_map: dict[float, StrikeRow],
    *,
    max_walls: int = 2,
) -> list[dict[str, Any]]:
    if not horizon or not isinstance(horizon, dict):
        return []
    out: list[dict[str, Any]] = []
    spot = float(horizon.get("spot") or 0)

    for side, role in (("resistances", "resistance"), ("supports", "support")):
        items = horizon.get(side) or []
        if not isinstance(items, list):
            continue
        for w in items[:max_walls]:
            if not isinstance(w, dict):
                continue
            sk = int(w.get("strike") or 0)
            if sk <= 0:
                continue
            row = _strike_row(strikes_map, sk)
            if row is None:
                continue
            ce_oi = int(row.call.oi)
            pe_oi = int(row.put.oi)
            ce_d = int(row.call.oi) - int(row.call.prev_oi)
            pe_d = int(row.put.oi) - int(row.put.prev_oi)

            if role == "resistance":
                thr = _threshold_from_oi(ce_oi)
                if ce_d <= -thr:
                    verdict = "break_up_more_likely"
                    label = "Resistance break-up more likely"
                    reason = f"CE OI at {sk} unwinding (Δ {ce_d:,}) vs wall — writers covering often precedes a push through."
                elif ce_d >= thr:
                    verdict = "hold_cap_more_likely"
                    label = "Resistance likely to cap"
                    reason = f"Fresh CE OI building at {sk} (Δ {ce_d:+,}) — call writers adding overhead supply."
                else:
                    verdict = "neutral"
                    label = "Wall neutral"
                    reason = f"CE OI change at {sk} is small vs threshold (~{thr:,}) — no clear break signal."
            else:
                thr = _threshold_from_oi(pe_oi)
                if pe_d <= -thr:
                    verdict = "break_down_more_likely"
                    label = "Support break-down more likely"
                    reason = f"PE OI at {sk} falling (Δ {pe_d:,}) — put writers covering can loosen the floor."
                elif pe_d >= thr:
                    verdict = "hold_floor_more_likely"
                    label = "Support likely to hold"
                    reason = f"PE OI adding at {sk} (Δ {pe_d:+,}) — put writers reinforcing the zone."
                else:
                    verdict = "neutral"
                    label = "Floor neutral"
                    reason = f"PE OI change at {sk} is small vs threshold (~{thr:,}) — no clear break signal."

            out.append(
                {
                    "horizon": horizon_name,
                    "role": role,
                    "strike": sk,
                    "spot": round(spot, 2),
                    "ce_oi": ce_oi,
                    "pe_oi": pe_oi,
                    "ce_oi_change": ce_d,
                    "pe_oi_change": pe_d,
                    "break_verdict": verdict,
                    "verdict_label": label,
                    "reason": reason,
                }
            )
    return out


def _aggregate_chain_oi_change(rows: list[StrikeRow]) -> tuple[int, int, int]:
    tce = tpe = 0
    for r in rows:
        tce += int(r.call.oi) - int(r.call.prev_oi)
        tpe += int(r.put.oi) - int(r.put.prev_oi)
    return tce, tpe, tce - tpe


def _session_headline(
    up: int,
    down: int,
    net_cp: int,
    opening_label: str,
) -> tuple[str, str, list[str]]:
    diff = up - down
    lines: list[str] = []
    if net_cp > 50_000:
        lines.append(f"Chain-wide: call-side OI adding faster than puts (net CE−PE ΔOI ≈ {net_cp:+,}).")
    elif net_cp < -50_000:
        lines.append(f"Chain-wide: put-side OI adding faster than calls (net CE−PE ΔOI ≈ {net_cp:+,}).")
    else:
        lines.append("Chain-wide: CE vs PE OI changes are balanced — no strong one-sided build from totals alone.")

    if opening_label:
        lines.append(f"Opening window (future): {opening_label}.")

    if diff >= 3:
        key = "lean_up"
        head = "Session lean: upside"
        lines.append("Combined opening bias + wall read skews toward strength / continuation higher.")
    elif diff <= -3:
        key = "lean_down"
        head = "Session lean: downside"
        lines.append("Combined opening bias + wall read skews toward weakness / continuation lower.")
    elif abs(diff) <= 1:
        key = "range"
        head = "Session lean: range / two-way"
        lines.append("Signals conflict or are flat — expect two-way trade between key OI walls.")
    else:
        key = "mixed"
        head = "Session lean: mixed"
        lines.append("Upside and downside OI cues are offset — watch the nearest walls for a trigger.")

    return key, head, lines


def build_live_prediction(
    *,
    spot: float,
    rows: list[StrikeRow],
    sr_bundle: dict[str, Any] | None,
    opening_window_today: dict[str, Any] | None,
) -> dict[str, Any]:
    strikes_map = {float(r.strike_price): r for r in rows}
    tce_d, tpe_d, net_cp = _aggregate_chain_oi_change(rows)

    if net_cp > 40_000:
        chain_bias = "call_side_adding"
    elif net_cp < -40_000:
        chain_bias = "put_side_adding"
    else:
        chain_bias = "balanced"

    up_o, down_o, ok, olab = _opening_bias_scores(opening_window_today)

    walls: list[dict[str, Any]] = []
    intraday = (sr_bundle or {}).get("intraday") if isinstance(sr_bundle, dict) else None
    walls.extend(_wall_signals_for_horizon("intraday", intraday, strikes_map, max_walls=2))

    up_w = down_w = 0
    for w in walls:
        v = w.get("break_verdict")
        if v == "break_up_more_likely":
            up_w += 2
        elif v == "hold_cap_more_likely":
            down_w += 1
        elif v == "break_down_more_likely":
            down_w += 2
        elif v == "hold_floor_more_likely":
            up_w += 1

    if net_cp > 50_000:
        up_w += 1
    elif net_cp < -50_000:
        down_w += 1

    bias_key, headline, detail_lines = _session_headline(
        up_o + up_w,
        down_o + down_w,
        net_cp,
        olab,
    )

    opening_live = bool(
        opening_window_today
        and not opening_window_today.get("ready")
        and isinstance(opening_window_today.get("provisional"), dict)
    )

    return {
        "disclaimer": "Heuristic read from live chain OI / ΔOI and opening-window future trend — not advice.",
        "spot": round(spot, 2),
        "opening_trend_key": ok,
        "opening_trend_label": olab,
        "opening_trend_is_provisional": opening_live,
        "aggregate_chain": {
            "total_ce_oi_change": tce_d,
            "total_pe_oi_change": tpe_d,
            "net_call_minus_put_oi_change": net_cp,
            "bias": chain_bias,
        },
        "walls": walls,
        "session_move": {
            "bias_key": bias_key,
            "headline": headline,
            "detail_lines": detail_lines,
        },
    }
