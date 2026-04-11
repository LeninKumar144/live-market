"""
Hedging and multi-leg strategy recommendations from market context, OI/PCR, and signal flow.

Integrates with chain-derived spot/PCR and optional CE/PE signal labels. Strike ladder uses
NIFTY-style grid (default step 50). Rupee max P/L and indicative margin are computed in
``strategy_pnl`` from chain LTP × lot when ``chain_ltp`` is populated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Bias = Literal["bullish", "bearish", "neutral"]
VolRegime = Literal["high", "normal", "low"]


@dataclass(frozen=True, slots=True)
class MarketCondition:
    """Output of detect_market_condition()."""

    bias: Bias
    volatility: VolRegime
    spot: float
    atm_strike: int
    strike_step: int
    pcr: float | None
    market_direction: str
    market_delta_pct: float | None
    signal_hint: str
    confidence: float  # 0.0–1.0 aggregate


@dataclass(frozen=True, slots=True)
class StrategyRecommendation:
    strategy: str
    legs: tuple[str, ...]
    reason: str
    confidence: float
    max_profit_note: str = ""
    max_loss_note: str = ""
    margin_note: str = ""


def _round_atm(spot: float, step: int) -> int:
    s = max(1, int(step))
    return int(round(float(spot) / s) * s)


def _signal_bias(signal_types: list[str]) -> tuple[Bias | None, int, int]:
    """Infer directional tilt from recent signal type strings."""
    ce = 0
    pe = 0
    for t in signal_types:
        u = (t or "").upper()
        if "BUY" in u and "CE" in u and "PE" not in u:
            ce += 2
        elif "BUY" in u and "PE" in u:
            pe += 2
        elif "CE" in u and "PE" not in u:
            ce += 1
        elif "PE" in u and "CE" not in u:
            pe += 1
        elif "REVERSAL" in u or "CAUTION" in u:
            pass
    if ce > pe + 1:
        return "bullish", ce, pe
    if pe > ce + 1:
        return "bearish", ce, pe
    if ce > 0 or pe > 0:
        return "neutral", ce, pe
    return None, ce, pe


def _direction_from_label(direction: str) -> str:
    d = (direction or "").strip().lower()
    if d in ("up", "down", "flat"):
        return d
    if "up" in d:
        return "up"
    if "down" in d:
        return "down"
    return "flat"


def detect_market_condition(
    *,
    spot: float,
    strike_step: int = 50,
    pcr: float | None = None,
    market_direction: str = "flat",
    market_delta_pct: float | None = None,
    signal_types: list[str] | None = None,
) -> MarketCondition:
    """
    Fuse spot trend (from chain snapshots), PCR skew, and recent signal types into a regime.

    Volatility regime uses a simple heuristic: large |Δ%| or extreme PCR → elevated vol state.
    """
    step = max(1, int(strike_step))
    spot_eff = float(spot) if spot > 0 else 22000.0
    atm = _round_atm(spot_eff, step)

    sigs = list(signal_types or [])
    sig_bias, ce_n, pe_n = _signal_bias(sigs)
    md = _direction_from_label(market_direction)

    if sig_bias == "bullish":
        bias: Bias = "bullish"
    elif sig_bias == "bearish":
        bias = "bearish"
    elif sig_bias == "neutral" and ce_n > 0 and pe_n > 0:
        bias = "neutral"
    elif md == "up":
        bias = "bullish"
    elif md == "down":
        bias = "bearish"
    else:
        bias = "neutral"

    dp = float(market_delta_pct) if market_delta_pct is not None else 0.0
    pcr_v: float | None = None
    if pcr is not None:
        try:
            pcr_v = float(pcr)
        except (TypeError, ValueError):
            pcr_v = None

    vol: VolRegime = "normal"
    if abs(dp) >= 0.12:
        vol = "high"
    elif pcr_v is not None and (pcr_v >= 1.25 or pcr_v <= 0.72):
        vol = "high"
    elif abs(dp) < 0.03 and md == "flat":
        vol = "low"

    # Confidence: agreement between trend and signals
    agree = 0.55
    if sig_bias in ("bullish", "bearish"):
        if (sig_bias == "bullish" and md == "up") or (sig_bias == "bearish" and md == "down"):
            agree = 0.82
        elif md == "flat":
            agree = 0.68
        elif (sig_bias == "bullish" and md == "down") or (sig_bias == "bearish" and md == "up"):
            agree = 0.45
    else:
        if md != "flat":
            agree = 0.62
        else:
            agree = 0.50
    if pcr_v is not None and vol == "high":
        agree = min(0.95, agree + 0.06)

    hint = f"signals CE×{ce_n} PE×{pe_n}, spot Δ≈{dp:.2f}%, PCR={pcr_v if pcr_v is not None else 'n/a'}"

    return MarketCondition(
        bias=bias,
        volatility=vol,
        spot=float(spot) if spot > 0 else 0.0,
        atm_strike=atm,
        strike_step=step,
        pcr=pcr_v,
        market_direction=md,
        market_delta_pct=market_delta_pct,
        signal_hint=hint,
        confidence=round(min(0.97, max(0.35, agree)), 2),
    )


def _legs_bull_call_spread(atm: int, step: int) -> tuple[str, ...]:
    lo = atm
    hi = atm + step
    return (f"Buy {lo} CE", f"Sell {hi} CE")


def _legs_bull_put_spread(atm: int, step: int) -> tuple[str, ...]:
    sell_k = atm
    buy_k = atm - step
    return (f"Sell {sell_k} PE", f"Buy {buy_k} PE")


def _legs_bear_put_spread(atm: int, step: int) -> tuple[str, ...]:
    hi = atm
    lo = atm - step
    return (f"Buy {hi} PE", f"Sell {lo} PE")


def _legs_hedged_straddle(atm: int, step: int) -> tuple[str, ...]:
    w = step * 2
    return (
        f"Buy {atm} CE",
        f"Buy {atm} PE",
        f"Sell {atm + w} CE",
        f"Sell {atm - w} PE",
    )


def _legs_iron_condor(atm: int, step: int) -> tuple[str, ...]:
    w = step
    return (
        f"Sell {atm + w} CE",
        f"Buy {atm + 2 * w} CE",
        f"Sell {atm - w} PE",
        f"Buy {atm - 2 * w} PE",
    )


def _legs_call_butterfly(atm: int, step: int) -> tuple[str, ...]:
    return (
        f"Buy {atm - step} CE",
        f"Sell 2x {atm} CE",
        f"Buy {atm + step} CE",
    )


def _legs_protective_put(atm: int, step: int) -> tuple[str, ...]:
    return ("Long NIFTY / synthetic spot exposure", f"Buy {atm - step} PE")


def _legs_covered_call(atm: int, step: int) -> tuple[str, ...]:
    return ("Long NIFTY / synthetic spot exposure", f"Sell {atm + step} CE")


def _legs_diagonal_bull_ce(
    atm: int,
    step: int,
    long_expiry_display: str = "",
    short_expiry_display: str = "",
) -> tuple[str, ...]:
    if long_expiry_display and short_expiry_display:
        return (
            f"Buy {atm} CE · exp {long_expiry_display}",
            f"Sell {atm + step} CE · exp {short_expiry_display}",
        )
    return (
        f"Buy next-month {atm} CE",
        f"Sell current-week {atm + step} CE",
    )


def recommend_intraday_strategy(cond: MarketCondition) -> StrategyRecommendation:
    atm, st = cond.atm_strike, cond.strike_step

    if cond.volatility == "high":
        legs = _legs_hedged_straddle(atm, st)
        return StrategyRecommendation(
            strategy="Hedged Straddle",
            legs=legs,
            reason="Elevated vol / two-sided expansion risk — long ATM straddle with short OTM strangle to cap cost.",
            confidence=round(min(0.95, cond.confidence + 0.05), 2),
            max_profit_note="Large if spot moves beyond short wings; capped near shorts if pinned.",
            max_loss_note="Net debit of long straddle minus short strangle credit (finite if all same expiry).",
            margin_note="Multi-leg margin typically below naked straddle; verify SPAN with broker.",
        )

    if cond.bias == "bearish":
        legs = _legs_bear_put_spread(atm, st)
        return StrategyRecommendation(
            strategy="Bear Put Spread",
            legs=legs,
            reason="Bearish bias intraday — defined-risk put vertical.",
            confidence=cond.confidence,
            max_profit_note="Spread width minus net debit (if long debit spread).",
            max_loss_note="Limited to premium paid (debit spread).",
            margin_note="Limited risk; margin ~ max loss scenario for most brokers.",
        )

    if cond.bias == "bullish":
        if cond.market_direction == "up" and (cond.market_delta_pct or 0) > 0.05:
            legs = _legs_bull_call_spread(atm, st)
            name = "Bull Call Spread"
            reason = "Bullish momentum — debit call spread for upside with capped risk."
            mp = "Capped at (high strike − low strike) × lot − net debit."
            ml = "Net premium paid."
        else:
            legs = _legs_bull_put_spread(atm, st)
            name = "Bull Put Spread"
            reason = "Bullish with support / grind-up — credit put spread."
            mp = "Credit received; max profit if spot ≥ short put at expiry."
            ml = "Width − credit (max loss if spot ≤ long put)."

        return StrategyRecommendation(
            strategy=name,
            legs=legs,
            reason=reason,
            confidence=cond.confidence,
            max_profit_note=mp,
            max_loss_note=ml,
            margin_note="Credit spreads may require cash/margin for short leg risk.",
        )

    # Neutral intraday default: light credit via bull put at support proxy
    legs = _legs_bull_put_spread(atm, st)
    return StrategyRecommendation(
        strategy="Bull Put Spread",
        legs=legs,
        reason="No strong directional edge — conservative credit put spread slightly OTM.",
        confidence=round(cond.confidence * 0.85, 2),
        max_profit_note="Full credit if both puts expire OTM.",
        max_loss_note="Strike width − credit received.",
        margin_note="Monitor short put assignment risk into expiry.",
    )


def recommend_weekly_strategy(cond: MarketCondition) -> StrategyRecommendation:
    atm, st = cond.atm_strike, cond.strike_step

    if cond.bias == "neutral" or cond.volatility == "low":
        if cond.volatility == "low":
            legs = _legs_call_butterfly(atm, st)
            return StrategyRecommendation(
                strategy="Butterfly Spread",
                legs=legs,
                reason="Low realized drift — butterfly targets pin near ATM.",
                confidence=round(min(0.9, cond.confidence + 0.08), 2),
                max_profit_note="Peak at centre strike if pinned; decay-friendly.",
                max_loss_note="Net debit paid for fly.",
                margin_note="Defined risk; margin ≈ max loss.",
            )
        legs = _legs_iron_condor(atm, st)
        return StrategyRecommendation(
            strategy="Iron Condor",
            legs=legs,
            reason="Sideways weekly range — short OTM strangle with long wings.",
            confidence=cond.confidence,
            max_profit_note="Full credit if spot stays between short strikes.",
            max_loss_note="Wing width − credit (per side).",
            margin_note="Short options margin; portfolio margin may reduce vs legs.",
        )

    if cond.bias == "bullish":
        strong = cond.market_direction == "up" and (cond.market_delta_pct or 0) > 0.05
        if strong:
            legs = _legs_bull_call_spread(atm, st)
            name = "Bull Call Spread"
            reason = "Weekly bullish momentum — call debit spread for upside."
            mp, ml = "Width − debit.", "Debit paid."
        else:
            legs = _legs_bull_put_spread(atm, st)
            name = "Bull Put Spread"
            reason = "Weekly bullish / grind-up bias — credit put spread (alternative to call vertical)."
            mp, ml = "Credit if both puts expire OTM.", "Width − credit received."
        return StrategyRecommendation(
            strategy=name,
            legs=legs,
            reason=reason,
            confidence=cond.confidence,
            max_profit_note=mp,
            max_loss_note=ml,
            margin_note="Limited risk; verify short-strike margin.",
        )

    if cond.bias == "bearish":
        legs = _legs_bear_put_spread(atm, st)
        return StrategyRecommendation(
            strategy="Bear Put Spread",
            legs=legs,
            reason="Weekly bearish view — put debit spread.",
            confidence=cond.confidence,
            max_profit_note="Width − debit.",
            max_loss_note="Debit paid.",
            margin_note="Limited risk.",
        )

    legs = _legs_iron_condor(atm, st)
    return StrategyRecommendation(
        strategy="Iron Condor",
        legs=legs,
        reason="Mixed cues — neutral income with defined wings.",
        confidence=round(cond.confidence * 0.9, 2),
        max_profit_note="Credit retained inside range.",
        max_loss_note="Wing width − credit.",
        margin_note="Check SPAN for short legs.",
    )


def recommend_monthly_strategy(cond: MarketCondition) -> StrategyRecommendation:
    atm, st = cond.atm_strike, cond.strike_step

    if cond.bias == "bullish" and cond.volatility != "high":
        legs = _legs_diagonal_bull_ce(atm, st)
        return StrategyRecommendation(
            strategy="Diagonal Spread",
            legs=legs,
            reason="Moderate bullish trend — longer-dated long call vs short near-term call for theta harvest.",
            confidence=cond.confidence,
            max_profit_note="Path-dependent; benefits from slow grind up + vol stability.",
            max_loss_note="Typically net debit; max loss if long leg worthless and short unhedged — model with matrix.",
            margin_note="Diagonal margin combines long & short expiries; broker-specific.",
        )

    if cond.bias == "bearish" or (cond.pcr is not None and cond.pcr < 0.85):
        legs = _legs_protective_put(atm, st)
        return StrategyRecommendation(
            strategy="Protective Put",
            legs=legs,
            reason="Hedge tail risk — long put vs spot/long synthetic.",
            confidence=round(min(0.92, cond.confidence + 0.05), 2),
            max_profit_note="Unlimited upside on spot minus put cost.",
            max_loss_note="Put premium (insurance cost).",
            margin_note="Long option margin minimal vs short options.",
        )

    legs = _legs_covered_call(atm, st)
    return StrategyRecommendation(
        strategy="Covered Call",
        legs=legs,
        reason="Income on existing / synthetic long — sell OTM call vs position.",
        confidence=round(cond.confidence * 0.88, 2),
        max_profit_note="Call premium + upside to short strike.",
        max_loss_note="Downside on underlying less premium (undefined without other hedge).",
        margin_note="Covered call margin tied to underlying exposure.",
    )


def recommend_iron_condor_widget(cond: MarketCondition) -> StrategyRecommendation:
    """Always-on iron condor around current ATM (same geometry as weekly neutral IC)."""
    atm, st = cond.atm_strike, cond.strike_step
    legs = _legs_iron_condor(atm, st)
    return StrategyRecommendation(
        strategy="Iron Condor",
        legs=legs,
        reason=(
            f"Defined-risk range income: short OTM CE/PE at ±{st} from ATM {atm}, "
            f"long wings at ±{2 * st}. Fits neutral / chop when IV is not pinned extremely low."
        ),
        confidence=round(min(0.92, cond.confidence + 0.05), 2),
        max_profit_note="Net credit if index settles between short strikes at expiry.",
        max_loss_note="Larger of call or put wing width × lot − net credit (per side).",
        margin_note="Short legs drive SPAN; portfolio margin often below sum of legs.",
    )


def recommend_diagonal_widget(
    cond: MarketCondition,
    *,
    long_expiry_display: str = "",
    short_expiry_display: str = "",
) -> StrategyRecommendation:
    """Bull call diagonal: long back-month CE vs short front-week CE (theta + upside)."""
    atm, st = cond.atm_strike, cond.strike_step
    legs = _legs_diagonal_bull_ce(atm, st, long_expiry_display, short_expiry_display)
    bias_note = (
        "Aligns with constructive / grind-up tape."
        if cond.bias == "bullish"
        else "Carry structure — watch if bias turns bearish."
    )
    exp_note = ""
    if long_expiry_display and short_expiry_display:
        exp_note = (
            f"Long leg expiry: {long_expiry_display} (weekday + date). "
            f"Short leg expiry: {short_expiry_display}."
        )
    reason_parts = [
        f"Long-dated {atm} CE vs shorter-dated short {atm + st} CE — harvest roll yield.",
    ]
    if exp_note:
        reason_parts.append(exp_note)
    reason_parts.append(bias_note)
    reason = " ".join(reason_parts)
    return StrategyRecommendation(
        strategy="Diagonal Spread",
        legs=legs,
        reason=reason,
        confidence=cond.confidence,
        max_profit_note="Path-dependent; peaks with slow rise through short strike then roll.",
        max_loss_note="Often net debit of long minus short premium; tail risk if long leg collapses.",
        margin_note="Two expiries — margin is broker-specific (diagonal / calendar rules).",
    )


def diagonal_rollover_guidance(
    cond: MarketCondition,
    *,
    short_expiry_display: str = "",
    long_expiry_display: str = "",
) -> list[dict[str, str]]:
    """
    Actionable rollover cues driven by the same regime inputs as the rest of the dashboard.

    Not trade advice — user must match to their strikes, fills, and risk limits.
    """
    md = cond.market_direction
    bias = cond.bias
    vol = cond.volatility
    atm = cond.atm_strike
    st = cond.strike_step
    rows: list[dict[str, str]] = []

    if long_expiry_display and short_expiry_display:
        rows.append(
            {
                "trigger": "Snapshot expiries (from contract list)",
                "action": (
                    f"Long (buy) CE targets {long_expiry_display}; short (sell) CE targets "
                    f"{short_expiry_display}. On each roll, line up the next listed NIFTY session "
                    "expiry after these dates at your broker."
                ),
            }
        )

    if vol == "high":
        rows.append(
            {
                "trigger": "Volatility regime: elevated (Δ% or PCR stress)",
                "action": "Avoid adding fresh short gamma; if short call is threatened, buy it back first, then reset higher or skip re-short until range stabilizes.",
            }
        )

    if md == "up":
        rows.append(
            {
                "trigger": "Spot trending up (live chain move)",
                "action": f"If the short CE approaches ITM, roll it up one strike step (+{st}) and/or to the next weekly expiry to reset delta while keeping the long {atm} CE anchor.",
            }
        )
        if bias == "bullish":
            rows.append(
                {
                    "trigger": "Trend + bullish bias",
                    "action": "Let winners run: after rolling the short up, consider widening the short strike only if premium is still attractive vs theta need.",
                }
            )

    if md == "down":
        rows.append(
            {
                "trigger": "Spot fading / pullback",
                "action": "If the short OTM call is comfortably safe, harvest decay. If spot approaches the short strike, roll the short down in strike or forward in time before delta flips against you.",
            }
        )
        if bias == "bearish":
            rows.append(
                {
                    "trigger": "Bearish shift vs a bullish diagonal",
                    "action": "Close or roll down the short CE to cut negative delta; either hold the long LEAP for a bounce or exit the structure to free margin.",
                }
            )

    if md == "flat":
        rows.append(
            {
                "trigger": "Sideways / mean-reverting tape",
                "action": f"Time-decay friendly: roll the short leg to the following week at the same or adjacent strike (±{st}) to collect another premium cycle without moving the long leg.",
            }
        )

    rows.append(
        {
            "trigger": "Short leg has captured ~50–70% of max theoretical gain",
            "action": "Take profit on the short call, then re-short at a higher strike or next expiry to rebuild the diagonal (reset theta).",
        }
    )

    rows.append(
        {
            "trigger": "Long leg approaching 21–35 DTE",
            "action": "Roll the long CE out in time and slightly up to restore duration and vega; re-establish the short leg against the new long.",
        }
    )

    rows.append(
        {
            "trigger": "PCR / OI skew flips strongly bearish while spot holds",
            "action": "Reduce size or tighten the short strike; consider pairing with a cheap OTM put for crash convexity before the next roll.",
        }
    )

    return rows


def _serialize_block(rec: StrategyRecommendation) -> dict[str, Any]:
    return {
        "strategy": rec.strategy,
        "legs": list(rec.legs),
        "reason": rec.reason,
        "confidence": rec.confidence,
        "max_profit": rec.max_profit_note,
        "max_loss": rec.max_loss_note,
        "margin_note": rec.margin_note,
    }


def build_hedging_payload(
    *,
    spot: float,
    strike_step: int = 50,
    pcr: float | None = None,
    market_direction: str = "flat",
    market_delta_pct: float | None = None,
    signal_types: list[str] | None = None,
    chain_expiry: str | None = None,
    diagonal_long_expiry_display: str = "",
    diagonal_short_expiry_display: str = "",
    diagonal_long_expiry_iso: str = "",
    diagonal_short_expiry_iso: str = "",
) -> dict[str, Any]:
    """
    Full response body for GET /hedging: horizons + dedicated iron condor & diagonal widgets + meta.
    """
    cond = detect_market_condition(
        spot=spot,
        strike_step=strike_step,
        pcr=pcr,
        market_direction=market_direction,
        market_delta_pct=market_delta_pct,
        signal_types=signal_types,
    )
    intra = recommend_intraday_strategy(cond)
    week = recommend_weekly_strategy(cond)
    month = recommend_monthly_strategy(cond)
    ic = recommend_iron_condor_widget(cond)
    dg = recommend_diagonal_widget(
        cond,
        long_expiry_display=diagonal_long_expiry_display.strip(),
        short_expiry_display=diagonal_short_expiry_display.strip(),
    )

    return {
        "intraday": _serialize_block(intra),
        "weekly": _serialize_block(week),
        "monthly": _serialize_block(month),
        "iron_condor": _serialize_block(ic),
        "diagonal": {
            **_serialize_block(dg),
            "rollover": diagonal_rollover_guidance(
                cond,
                short_expiry_display=diagonal_short_expiry_display.strip(),
                long_expiry_display=diagonal_long_expiry_display.strip(),
            ),
            "short_expiry_display": diagonal_short_expiry_display.strip(),
            "long_expiry_display": diagonal_long_expiry_display.strip(),
            "short_expiry_iso": diagonal_short_expiry_iso.strip(),
            "long_expiry_iso": diagonal_long_expiry_iso.strip(),
        },
        "meta": {
            "spot": cond.spot,
            "atm_strike": cond.atm_strike,
            "strike_step": cond.strike_step,
            "bias": cond.bias,
            "volatility": cond.volatility,
            "pcr": cond.pcr,
            "market_direction": cond.market_direction,
            "chain_expiry": chain_expiry or "",
            "signal_context": cond.signal_hint,
            "regime_confidence": cond.confidence,
        },
    }


