"""
Rupee P/L and indicative margin from option LTPs × lot size (NIFTY-style index options).

Uses European-style expiry payoff grid for same-expiry legs. Index intrinsic → ₹ via points × lot.
Diagonal / stock legs: partial marks + disclaimers. Broker SPAN may differ from margin_inr.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Literal

Side = Literal["buy", "sell"]
CP = Literal["CE", "PE"]


@dataclass(frozen=True, slots=True)
class OptLeg:
    side: Side
    qty: int
    strike: int
    cp: CP
    raw: str


def nifty_option_lot_size() -> int:
    try:
        return max(1, int(os.environ.get("NIFTY_OPTION_LOT_SIZE", "65")))
    except ValueError:
        return 65


_RE_STD = re.compile(
    r"(?i)^(Buy|Sell)\s+(?:(\d+)\s*x\s+)?(\d+)\s+(CE|PE)(?:\s*·\s*exp\s+.+)?\s*$",
)
_RE_DATED = re.compile(
    r"(?i)^(Buy|Sell)\s+(?:next-month|current-week)\s+(\d+)\s+(CE|PE)\s*$",
)


def parse_option_legs(leg_lines: tuple[str, ...] | list[str]) -> tuple[list[OptLeg], list[str]]:
    """Parse standard option leg strings; return (parsed, skipped descriptive lines)."""
    out: list[OptLeg] = []
    skipped: list[str] = []
    for raw in leg_lines:
        s = (raw or "").strip()
        if not s:
            continue
        if "nifty" in s.lower() and "synthetic" in s.lower():
            skipped.append(s)
            continue
        if "long nifty" in s.lower():
            skipped.append(s)
            continue

        m = _RE_STD.match(s)
        if m:
            side = m.group(1).lower()
            q = int(m.group(2) or 1)
            strike = int(m.group(3))
            cp = m.group(4).upper()
            out.append(OptLeg(side=side, qty=q, strike=strike, cp=cp, raw=s))  # type: ignore[arg-type]
            continue

        m2 = _RE_DATED.match(s)
        if m2:
            side = m2.group(1).lower()
            strike = int(m2.group(2))
            cp = m2.group(3).upper()
            out.append(OptLeg(side=side, qty=1, strike=strike, cp=cp, raw=s))  # type: ignore[arg-type]
            continue

        skipped.append(s)
    return out, skipped


def _ltp_for(strike: int, cp: CP, chain_ltp: dict[str, Any]) -> float | None:
    key = str(int(strike))
    row = chain_ltp.get(key)
    if not isinstance(row, dict):
        return None
    v = row.get("ce" if cp == "CE" else "pe")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _intrinsic(S: float, strike: int, cp: CP) -> float:
    if cp == "CE":
        return max(0.0, S - float(strike))
    return max(0.0, float(strike) - S)


def _settlement_at_S(S: float, legs: list[OptLeg], lot: int) -> float:
    total = 0.0
    for L in legs:
        intr = _intrinsic(S, L.strike, L.cp)
        sign = 1.0 if L.side == "buy" else -1.0
        total += sign * intr * float(L.qty) * float(lot)
    return total


def _premium_paid_net(legs: list[OptLeg], ltps: list[float], lot: int) -> float:
    net = 0.0
    for L, px in zip(legs, ltps):
        flow = px * float(L.qty) * float(lot)
        if L.side == "buy":
            net += flow
        else:
            net -= flow
    return net


def _pnl_at_S(S: float, legs: list[OptLeg], ltps: list[float], lot: int) -> float:
    return _settlement_at_S(S, legs, lot) - _premium_paid_net(legs, ltps, lot)


def _grid_extremes(
    legs: list[OptLeg],
    ltps: list[float],
    lot: int,
    *,
    step: int = 5,
) -> tuple[float | None, float | None]:
    if not legs or len(legs) != len(ltps):
        return None, None
    strikes = [L.strike for L in legs]
    lo = min(strikes) - 200
    hi = max(strikes) + 200
    best = -1e18
    worst = 1e18
    S = float(lo)
    while S <= hi:
        p = _pnl_at_S(S, legs, ltps, lot)
        if p > best:
            best = p
        if p < worst:
            worst = p
        S += float(step)
    return best, worst


def _leg_details(legs: list[OptLeg], chain_ltp: dict[str, Any], lot: int) -> tuple[list[dict[str, Any]], list[float], list[str]]:
    details: list[dict[str, Any]] = []
    ltps: list[float] = []
    missing: list[str] = []
    for L in legs:
        px = _ltp_for(L.strike, L.cp, chain_ltp)
        if px is None:
            missing.append(L.raw)
            details.append(
                {
                    "description": L.raw,
                    "ltp": None,
                    "premium_debit_inr": None,
                    "missing_quote": True,
                }
            )
            ltps.append(0.0)
        else:
            prem = px * float(L.qty) * float(lot)
            debit_inr = prem if L.side == "buy" else -prem
            details.append(
                {
                    "description": L.raw,
                    "ltp": round(px, 2),
                    "premium_debit_inr": round(debit_inr, 2),
                    "missing_quote": False,
                }
            )
            ltps.append(px)
    return details, ltps, missing


def _enrich_same_expiry_grid(
    strategy: str,
    legs: list[str],
    chain_ltp: dict[str, Any],
    lot: int,
    strike_step: int,
) -> dict[str, Any]:
    parsed, skipped = parse_option_legs(legs)
    if not parsed:
        return _empty_metrics(skipped, strategy)

    details, ltps, missing = _leg_details(parsed, chain_ltp, lot)
    if missing:
        return {
            "legs_detail": details,
            "net_premium_inr": None,
            "max_profit_inr": None,
            "max_loss_inr": None,
            "margin_inr": None,
            "pnl_disclaimer": f"Missing LTP for: {', '.join(missing)}. Refresh OI chain.",
            "skipped_legs": skipped,
        }

    net_pre = round(_premium_paid_net(parsed, ltps, lot), 2)
    mp, ml = _grid_extremes(parsed, ltps, lot, step=max(1, min(5, strike_step // 10 or 5)))
    if mp is None or ml is None:
        return _empty_metrics(skipped, strategy)

    max_profit_inr = round(max(0.0, mp), 2)
    max_loss_inr = round(max(0.0, -ml), 2)
    margin_inr = round(max_loss_inr, 2)

    disc = (
        "P/L at expiry vs entry premiums (LTP×lot). European-style intrinsic × lot. "
        "Margin shown ≈ max loss (defined risk); broker SPAN may differ."
    )
    if strategy == "Hedged Straddle":
        disc += " Large moves can alter settlement; verify with full payoff diagram."

    return {
        "legs_detail": details,
        "net_premium_inr": net_pre,
        "max_profit_inr": max_profit_inr,
        "max_loss_inr": max_loss_inr,
        "margin_inr": margin_inr,
        "pnl_disclaimer": disc,
        "skipped_legs": skipped,
    }


def _empty_metrics(skipped: list[str], strategy: str) -> dict[str, Any]:
    return {
        "legs_detail": [],
        "net_premium_inr": None,
        "max_profit_inr": None,
        "max_loss_inr": None,
        "margin_inr": None,
        "pnl_disclaimer": f"No priced option legs parsed for {strategy}.",
        "skipped_legs": skipped,
    }


def _enrich_diagonal(
    legs: list[str],
    chain_ltp: dict[str, Any],
    lot: int,
) -> dict[str, Any]:
    parsed, skipped = parse_option_legs(legs)
    if len(parsed) != 2 or any(L.cp != "CE" for L in parsed):
        return _empty_metrics(skipped, "Diagonal Spread")

    details, ltps, missing = _leg_details(parsed, chain_ltp, lot)
    if missing:
        return {
            "legs_detail": details,
            "net_premium_inr": None,
            "max_profit_inr": None,
            "max_loss_inr": None,
            "margin_inr": None,
            "pnl_disclaimer": "Missing LTP for diagonal legs — refresh OI chain.",
            "skipped_legs": skipped,
        }

    buy_leg = next((L for L in parsed if L.side == "buy"), None)
    sell_leg = next((L for L in parsed if L.side == "sell"), None)
    if not buy_leg or not sell_leg:
        return _empty_metrics(skipped, "Diagonal Spread")

    i_buy = parsed.index(buy_leg)
    i_sell = parsed.index(sell_leg)
    px_buy = ltps[i_buy]
    px_sell = ltps[i_sell]
    net_debit = round((px_buy - px_sell) * float(lot), 2)

    if net_debit > 0:
        max_loss = round(net_debit, 2)
        margin = max_loss
    else:
        max_loss = None
        margin = None

    return {
        "legs_detail": details,
        "net_premium_inr": net_debit,
        "max_profit_inr": None,
        "max_loss_inr": max_loss,
        "margin_inr": margin,
        "pnl_disclaimer": "Net premium uses same-expiry chain LTP for both legs (approximation). Different expiries — path-dependent; confirm with broker.",
        "skipped_legs": skipped,
    }


def _enrich_protective_put(
    legs: list[str],
    chain_ltp: dict[str, Any],
    lot: int,
) -> dict[str, Any]:
    parsed, skipped = parse_option_legs(legs)
    puts = [L for L in parsed if L.cp == "PE" and L.side == "buy"]
    if not puts:
        return _empty_metrics(skipped, "Protective Put")
    L = puts[0]
    px = _ltp_for(L.strike, "PE", chain_ltp)
    details, _, missing = _leg_details(parsed, chain_ltp, lot)
    prem = round(px * float(lot), 2) if px is not None else None
    return {
        "legs_detail": details,
        "net_premium_inr": prem,
        "max_profit_inr": None,
        "max_loss_inr": prem,
        "margin_inr": prem,
        "pnl_disclaimer": "Put leg only: premium × lot is hedge cost. Spot/Future margin is separate (broker).",
        "skipped_legs": skipped,
    }


def _enrich_covered_call(
    legs: list[str],
    chain_ltp: dict[str, Any],
    lot: int,
    spot: float,
) -> dict[str, Any]:
    parsed, skipped = parse_option_legs(legs)
    shorts = [L for L in parsed if L.cp == "CE" and L.side == "sell"]
    if not shorts or spot <= 0:
        return _empty_metrics(skipped, "Covered Call")
    L = shorts[0]
    px = _ltp_for(L.strike, "CE", chain_ltp)
    details, _, missing = _leg_details(parsed, chain_ltp, lot)
    if px is None:
        return {
            "legs_detail": details,
            "net_premium_inr": None,
            "max_profit_inr": None,
            "max_loss_inr": None,
            "margin_inr": None,
            "pnl_disclaimer": "Missing short-call LTP.",
            "skipped_legs": skipped,
        }
    credit = px * float(lot)
    width = float(L.strike) - float(spot)
    approx_max_profit = width * float(lot) + credit
    approx_max_loss = spot * float(lot) - credit
    return {
        "legs_detail": details,
        "net_premium_inr": round(-credit, 2),
        "max_profit_inr": round(max(0.0, approx_max_profit), 2),
        "max_loss_inr": round(max(0.0, approx_max_loss), 2),
        "margin_inr": round(max(0.0, approx_max_loss), 2),
        "pnl_disclaimer": "Synthetic long at spot: max profit ≈ (short strike − spot)×lot + premium; max loss if spot→0 (simplified). Future/index margin extra.",
        "skipped_legs": skipped,
    }


def enrich_strategy_block(
    block: dict[str, Any],
    chain_ltp: dict[str, Any],
    lot: int,
    *,
    strike_step: int,
    spot: float,
) -> dict[str, Any]:
    """Attach INR metrics + per-leg LTP to one hedging block (mutates copy)."""
    strategy = str(block.get("strategy") or "")
    legs = list(block.get("legs") or [])
    out = dict(block)

    if strategy == "Diagonal Spread":
        metrics = _enrich_diagonal(legs, chain_ltp, lot)
    elif strategy == "Protective Put":
        metrics = _enrich_protective_put(legs, chain_ltp, lot)
    elif strategy == "Covered Call":
        metrics = _enrich_covered_call(legs, chain_ltp, lot, spot)
    else:
        metrics = _enrich_same_expiry_grid(strategy, legs, chain_ltp, lot, strike_step)

    out.update(metrics)
    out["lot_size"] = lot
    out["max_profit"] = block.get("max_profit") or ""
    out["max_loss"] = block.get("max_loss") or ""
    out["margin_note"] = block.get("margin_note") or ""
    return out


def enrich_hedging_payload(
    payload: dict[str, Any],
    chain_ltp: dict[str, Any],
    lot: int,
    *,
    strike_step: int,
    spot: float,
) -> dict[str, Any]:
    out = dict(payload)
    for key in ("intraday", "weekly", "monthly", "iron_condor"):
        if key in out and isinstance(out[key], dict):
            out[key] = enrich_strategy_block(out[key], chain_ltp, lot, strike_step=strike_step, spot=spot)

    diag = out.get("diagonal")
    if isinstance(diag, dict):
        rollover = diag.get("rollover") or []
        if not isinstance(rollover, list):
            rollover = []
        short_exp = str(diag.get("short_expiry_display") or "")
        long_exp = str(diag.get("long_expiry_display") or "")
        short_iso = str(diag.get("short_expiry_iso") or "")
        long_iso = str(diag.get("long_expiry_iso") or "")
        skip = {"rollover", "short_expiry_display", "long_expiry_display", "short_expiry_iso", "long_expiry_iso"}
        base = {k: v for k, v in diag.items() if k not in skip}
        enriched = enrich_strategy_block(base, chain_ltp, lot, strike_step=strike_step, spot=spot)
        enriched["rollover"] = rollover
        enriched["short_expiry_display"] = short_exp
        enriched["long_expiry_display"] = long_exp
        enriched["short_expiry_iso"] = short_iso
        enriched["long_expiry_iso"] = long_iso
        out["diagonal"] = enriched

    meta = dict(out.get("meta") or {})
    meta["nifty_option_lot_size"] = lot
    meta["pnl_basis"] = "LTP × lot; intrinsic settlement grid (same expiry) unless noted"
    out["meta"] = meta
    return out
