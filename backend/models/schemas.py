from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SignalOut(BaseModel):
    id: str
    type: str = Field(description="BUY CE, BUY PE, POSSIBLE REVERSAL, etc.")
    strike: float | None = None
    reason: str = ""
    time: str = Field("", description="HH:MM display")
    timestamp_iso: str = Field("", description="ISO timestamp for sorting")
    confidence: str = Field("Medium", description="High / Medium / Low")


class SignalsResponse(BaseModel):
    signals: list[SignalOut]
    source: str = Field("", description="json | excel | log | mixed")
    updated_hint: str = ""


class HistoryResponse(BaseModel):
    signals: list[SignalOut]
    total: int
    page: int
    page_size: int
    source: str = ""


class LegSuggestionOut(BaseModel):
    """Suggested execution leg from latest option chain (liquidity + ATM/OTM rules)."""

    side: str = Field(description="CE or PE")
    strike: float
    ltp: float = 0
    open_interest: int = 0
    volume: int = 0
    execution_note: str = Field("", description="ATM vs OTM rationale from config / spot trend")


class SRLevelOut(BaseModel):
    strike: int
    ce_oi: int = 0
    pe_oi: int = 0
    kind: str = ""
    reason: str = ""


class PivotLevelsOut(BaseModel):
    """Classic pivot from prior period H/L/C (refreshed with live daily candles)."""

    pivot: float | None = Field(None, description="Pivot / PP")
    r1: float | None = None
    r2: float | None = None
    s1: float | None = None
    s2: float | None = None
    basis_high: float | None = None
    basis_low: float | None = None
    basis_close: float | None = None
    basis_label: str = ""
    unavailable_reason: str | None = None


class SRHorizonOut(BaseModel):
    """Support / resistance from PE / CE OI walls for one expiry horizon."""

    horizon: str = ""
    expiry_iso: str = ""
    expiry_display: str = ""
    spot: float = 0
    supports: list[SRLevelOut] = Field(default_factory=list)
    resistances: list[SRLevelOut] = Field(default_factory=list)
    note: str = ""
    chain_caption: str | None = None
    pivot_levels: PivotLevelsOut | None = None


class SRLevelsBundle(BaseModel):
    intraday: SRHorizonOut | None = None
    weekly: SRHorizonOut | None = None
    monthly: SRHorizonOut | None = None


class NiftyFutureQuoteOut(BaseModel):
    """Live NIFTY 50 index future (nearest resolved month) from market quote."""

    symbol: str = ""
    instrument_key: str = ""
    ltp: float = 0.0
    oi: int = Field(0, description="Open interest (contracts)")
    volume: int = 0
    net_change: float | None = Field(None, description="Vs previous close (broker field)")
    ohlc_open: float | None = None
    ohlc_high: float | None = None
    ohlc_low: float | None = None
    ohlc_close: float | None = None


class OpeningWindowSnapshotOut(BaseModel):
    at: str = ""
    ltp: float = 0.0
    oi: int = 0
    symbol: str = ""


class OpeningWindowProvisionalOut(BaseModel):
    """Live OI/LTP vs 09:15 anchor while the session is still inside 09:15–09:30 IST."""

    trend_key: str = ""
    trend_label: str = ""
    d_ltp: float = 0.0
    d_oi: int = 0
    ltp: float = 0.0
    oi: int = 0


class OpeningWindowTodayOut(BaseModel):
    date: str = ""
    ready: bool = False
    now_is_before_930: bool = False
    trend_key: str = ""
    trend_label: str = ""
    d_ltp: float | None = None
    d_oi: int | None = None
    early: OpeningWindowSnapshotOut | None = None
    late: OpeningWindowSnapshotOut | None = None
    provisional: OpeningWindowProvisionalOut | None = None


class OpeningWindowHistoryRowOut(BaseModel):
    date: str
    trend_key: str = ""
    trend_label: str = ""
    d_ltp: float | None = None
    d_oi: int | None = None
    early_at: str | None = None
    late_at: str | None = None


class OpeningWindowBlockOut(BaseModel):
    today: OpeningWindowTodayOut | None = None
    history: list[OpeningWindowHistoryRowOut] = Field(default_factory=list)
    note: str = Field(
        "",
        description="How 09:15–09:30 IST window is sampled (first poll in each leg, IST)",
    )


class AggregateChainOiOut(BaseModel):
    total_ce_oi_change: int = 0
    total_pe_oi_change: int = 0
    net_call_minus_put_oi_change: int = 0
    bias: str = Field("", description="call_side_adding | put_side_adding | balanced")
    total_ce_volume_change_since_last_poll: int | None = Field(
        None,
        description="Σ CE volume minus total on prior successful chain refresh (live increment per poll)",
    )
    total_pe_volume_change_since_last_poll: int | None = Field(
        None,
        description="Σ PE volume minus total on prior successful chain refresh (live increment per poll)",
    )


class WallBreakSignalOut(BaseModel):
    horizon: str = ""
    role: str = Field("", description="resistance | support")
    strike: int = 0
    spot: float = 0.0
    ce_oi: int = 0
    pe_oi: int = 0
    ce_oi_change: int = 0
    pe_oi_change: int = 0
    break_verdict: str = ""
    verdict_label: str = ""
    reason: str = ""


class SessionMovePredictionOut(BaseModel):
    bias_key: str = Field("", description="lean_up | lean_down | range | mixed")
    headline: str = ""
    detail_lines: list[str] = Field(default_factory=list)


class OpeningGapOut(BaseModel):
    open: float | None = None
    prev_close: float | None = None
    ltp: float | None = None
    gap_points: float | None = None
    gap_pct: float | None = None
    direction: str = "unknown"
    label: str = ""


class OpeningRangeOut(BaseModel):
    minutes: int = 15
    ready: bool = False
    complete: bool = False
    bar_count: int = 0
    high: float | None = None
    low: float | None = None
    open: float | None = None
    close: float | None = None
    mid: float | None = None
    range_points: float | None = None
    close_position: str = "unknown"


class OvernightWallsOut(BaseModel):
    zone: str = "unknown"
    label: str = ""
    support_strike: int | None = None
    resistance_strike: int | None = None
    ref_price: float | None = None
    pcr: float | None = None
    note: str = ""


class IndiaVixOut(BaseModel):
    symbol: str = "India VIX"
    instrument_key: str = ""
    ltp: float | None = None
    net_change: float | None = None
    ohlc_open: float | None = None
    ohlc_close: float | None = None


class SessionDoiVs915Out(BaseModel):
    available: bool = False
    ce_doi: int | None = None
    pe_doi: int | None = None
    net_ce_minus_pe: int | None = None
    bias: str = ""
    label: str = ""
    early_ce_oi: int | None = None
    early_pe_oi: int | None = None


class OpeningSessionFutureTrendOut(BaseModel):
    trend_key: str = ""
    trend_label: str = ""
    is_provisional: bool = False
    ready: bool = False


class OpeningSessionOut(BaseModel):
    """Three-phase open bias: pre-open / forming OR / post 09:30."""

    disclaimer: str = ""
    phase: str = Field("", description="pre_open | forming_or | post_or | after_hours")
    phase_label: str = ""
    as_of: str = ""
    bias_key: str = ""
    headline: str = ""
    detail_lines: list[str] = Field(default_factory=list)
    gap: OpeningGapOut = Field(default_factory=OpeningGapOut)
    overnight_walls: OvernightWallsOut = Field(default_factory=OvernightWallsOut)
    india_vix: IndiaVixOut | None = None
    opening_range_5m: OpeningRangeOut = Field(default_factory=OpeningRangeOut)
    opening_range_15m: OpeningRangeOut = Field(default_factory=OpeningRangeOut)
    price_vs_or_5m: dict[str, str] = Field(default_factory=dict)
    price_vs_or_15m: dict[str, str] = Field(default_factory=dict)
    future_trend: OpeningSessionFutureTrendOut = Field(default_factory=OpeningSessionFutureTrendOut)
    session_doi_vs_915: SessionDoiVs915Out = Field(default_factory=SessionDoiVs915Out)
    gift_nifty: dict[str, Any] = Field(default_factory=dict)


class LivePredictionOut(BaseModel):
    """Live OI-based read: opening future trend + intraday wall break hints + session lean."""

    disclaimer: str = ""
    spot: float = 0.0
    opening_trend_key: str = ""
    opening_trend_label: str = ""
    opening_trend_is_provisional: bool = False
    aggregate_chain: AggregateChainOiOut = Field(default_factory=AggregateChainOiOut)
    walls: list[WallBreakSignalOut] = Field(default_factory=list)
    session_move: SessionMovePredictionOut = Field(default_factory=SessionMovePredictionOut)


class SegmentMetaOut(BaseModel):
    """Public segment labels for dashboard nav / titles."""

    id: str = ""
    display_name: str = ""
    short_label: str = ""
    strike_step: int = 50
    show_india_vix: bool = True
    show_gift_note: bool = False
    route_path: str = ""
    instrument_key: str = ""


class OIStatusResponse(BaseModel):
    ok: bool = Field(description="True when a successful chain snapshot is cached")
    error: str | None = None
    excel_export_error: str | None = Field(
        None,
        description="Chain succeeded but writing the Excel file failed (e.g. file open in Excel)",
    )
    updated_at: str | None = Field(None, description="ISO timestamp of last successful refresh")
    excel_path: str | None = Field(None, description="Workbook path (CE/PE OI updated on interval)")
    segment: str | None = Field(None, description="Underlying segment id (nifty, banknifty, …)")
    segment_meta: SegmentMetaOut | None = Field(
        None, description="Display labels / flags for this segment"
    )
    spot: float = 0
    expiry: str = ""
    pcr: float | None = None
    total_call_oi: int | None = None
    total_put_oi: int | None = None
    total_call_volume: int | None = Field(
        None,
        description="Sum of traded volume across all CE legs in the chain snapshot (session day)",
    )
    total_put_volume: int | None = Field(
        None,
        description="Sum of traded volume across all PE legs in the chain snapshot (session day)",
    )
    buy_ce: LegSuggestionOut | None = None
    buy_pe: LegSuggestionOut | None = None
    market_move_label: str = ""
    sr_levels: SRLevelsBundle | None = Field(
        None,
        description="Classic pivots (prior day/week/month from index daily candles) + OI walls per expiry horizon",
    )
    nifty_future: NiftyFutureQuoteOut | None = Field(
        None,
        description="Current segment future LTP, OI, session OHLC (same cycle as option chain)",
    )
    opening_window: OpeningWindowBlockOut | None = Field(
        None,
        description="Future OI + LTP change 09:15–09:30 IST (first tick after 09:15 vs first at/after 09:30)",
    )
    live_prediction: LivePredictionOut | None = Field(
        None,
        description="Live opening-window trend + option ΔOI vs OI walls + session bias (refreshed each chain poll)",
    )
    opening_session: OpeningSessionOut | None = Field(
        None,
        description="Pre-open / 0–15m / post-09:30 bias: gap, VIX, OR, ΔOI vs 09:15",
    )
    india_vix: IndiaVixOut | None = Field(
        None,
        description="India VIX quote when available from Upstox",
    )
    auto_update_enabled: bool = True
    update_interval_seconds: float = 60


class FutureChartCandleOut(BaseModel):
    """One-minute future bar (UTC unix time for charting libraries)."""

    time_unix: int = Field(description="Unix seconds UTC — lightweight-charts intraday time")
    time_iso_ist: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0


class OiFutureChartTradePlanOut(BaseModel):
    """Combined Σ CE / Σ PE / PCR / ΔOI + candle-pattern synthesis (heuristic, not advice)."""

    side: str = Field("", description="long | short | flat")
    trend_summary: str = ""
    pattern_name: str = ""
    pattern_detail: str = ""
    total_call_oi: int | None = None
    total_put_oi: int | None = None
    total_call_volume: int | None = None
    total_put_volume: int | None = None
    total_ce_oi_change: int = 0
    total_pe_oi_change: int = 0
    total_ce_volume_change_since_last_poll: int | None = None
    total_pe_volume_change_since_last_poll: int | None = None
    entry_price: float | None = None
    entry_time_iso_ist: str | None = None
    entry_trigger: str = ""
    exit_price: float | None = None
    exit_label: str = ""
    stop_loss: float | None = None
    oi_metric_lines: list[str] = Field(default_factory=list)
    chart_narrative: str = ""
    disclaimer: str = ""


class OiFutureChartResponse(BaseModel):
    ok: bool = False
    error: str | None = None
    chart_warning: str | None = Field(
        None,
        description="Soft notice (e.g. no future key or candle fetch) while trade_plan may still use chain OI/volume",
    )
    symbol: str = ""
    instrument_key: str = ""
    spot: float = 0.0
    ltp: float = 0.0
    session_day_ist: str = ""
    candles: list[FutureChartCandleOut] = Field(default_factory=list)
    trade_plan: OiFutureChartTradePlanOut = Field(default_factory=OiFutureChartTradePlanOut)
    chain_refreshed_at: str | None = None
    candles_fetched_at: str | None = None


class HedgingLegDetail(BaseModel):
    description: str
    ltp: float | None = None
    premium_debit_inr: float | None = Field(None, description="+ = cash out, − = credit (per leg)")
    missing_quote: bool = False


class RolloverGuidanceRow(BaseModel):
    """Diagonal / calendar rollover cue tied to live regime (spot move, bias, vol)."""

    trigger: str = Field(description="Market / position situation")
    action: str = Field(description="Suggested management / roll idea")


class HedgingStrategyBlock(BaseModel):
    """Single horizon recommendation (intraday / weekly / monthly)."""

    strategy: str
    legs: list[str]
    reason: str
    confidence: float = Field(0.7, ge=0.0, le=1.0, description="Model confidence 0–1")
    max_profit: str = Field("", description="Qualitative P/L note")
    max_loss: str = Field("", description="Qualitative risk note")
    margin_note: str = Field("", description="Qualitative margin / SPAN hint")
    legs_detail: list[HedgingLegDetail] = Field(default_factory=list)
    net_premium_inr: float | None = Field(None, description="Net premium paid (+) or received (−) at entry")
    max_profit_inr: float | None = None
    max_loss_inr: float | None = None
    margin_inr: float | None = Field(None, description="Indicative: usually max loss for defined-risk; SPAN may differ")
    pnl_disclaimer: str = ""
    skipped_legs: list[str] = Field(default_factory=list)
    lot_size: int | None = None


class DiagonalWidgetBlock(HedgingStrategyBlock):
    """Diagonal spread + dynamic rollover playbook."""

    rollover: list[RolloverGuidanceRow] = Field(default_factory=list)
    short_expiry_display: str = Field("", description="Near (short call) leg — weekday + day + month")
    long_expiry_display: str = Field("", description="Long-dated leg — weekday + day + month")
    short_expiry_iso: str = Field("", description="YYYY-MM-DD for short leg")
    long_expiry_iso: str = Field("", description="YYYY-MM-DD for long leg")


class HedgingMetaBlock(BaseModel):
    spot: float = 0.0
    atm_strike: int = 0
    strike_step: int = 50
    bias: str = ""
    volatility: str = ""
    pcr: float | None = None
    market_direction: str = ""
    chain_expiry: str = ""
    signal_context: str = ""
    regime_confidence: float = 0.0
    nifty_option_lot_size: int | None = Field(None, description="Lot multiplier for ₹ amounts (env NIFTY_OPTION_LOT_SIZE)")
    pnl_basis: str = ""


class HedgingResponse(BaseModel):
    intraday: HedgingStrategyBlock
    weekly: HedgingStrategyBlock
    monthly: HedgingStrategyBlock
    iron_condor: HedgingStrategyBlock
    diagonal: DiagonalWidgetBlock
    meta: HedgingMetaBlock


class StockOptionLiquidityRow(BaseModel):
    """One NSE equity F&O name with liquidity-oriented notes (curated, not live)."""

    symbol: str
    name: str
    sector: str
    tier: int = Field(ge=1, le=3, description="1 = typically deepest liquidity")
    liquidity_score: int = Field(ge=0, le=100, description="Heuristic sort key within tier")
    expiries_note: str = ""
    highlights: list[str] = Field(default_factory=list)
    option_tips: list[str] = Field(default_factory=list)
    watchouts: list[str] = Field(default_factory=list)


class StockOptionsLiquidityResponse(BaseModel):
    disclaimer: str
    market: str
    stocks: list[StockOptionLiquidityRow]
    how_to_use: list[str] = Field(default_factory=list)


class StockLiveOiTotalsOut(BaseModel):
    total_call_oi: int = 0
    total_put_oi: int = 0
    total_call_prev_oi: int = 0
    total_put_prev_oi: int = 0
    call_oi_change_vs_prev_close: int = 0
    put_oi_change_vs_prev_close: int = 0
    call_oi_change_since_last_poll: int | None = None
    put_oi_change_since_last_poll: int | None = None
    pcr: float | None = None


class StockLiveLegOut(BaseModel):
    strike: float
    ltp: float = 0.0
    open_interest: int = 0
    volume: int = 0
    prev_oi: int = 0
    oi_change_vs_prev_close: int = 0
    oi_change_since_last_poll: int | None = None
    instrument_key: str = ""
    execution_note: str = ""
    required_margin_inr: float | None = Field(
        None,
        description="1 lot BUY: Upstox charges/margin total_margin when available, else ≈ LTP × lot",
    )
    margin_source: str = Field("", description="upstox | premium_estimate | empty")
    premium_estimate_inr: float | None = Field(None, description="LTP × lot (shares) for one long lot")


class MarketMoveSnippetOut(BaseModel):
    direction: str = "flat"
    delta_points: float = 0.0
    delta_pct: float = 0.0
    n_snapshots: int = 0
    from_spot: float = 0.0
    to_spot: float = 0.0
    label: str = ""


class StockLiveRowOut(BaseModel):
    symbol: str
    name: str = ""
    sector: str = ""
    tier: int = 1
    liquidity_score: int = 0
    ok: bool = False
    error: str | None = None
    instrument_key: str | None = None
    expiry: str = ""
    spot: float = 0.0
    strike_step: int = 50
    option_lot_size: int | None = Field(None, description="Contract lot size (shares per lot) for this expiry")
    totals: StockLiveOiTotalsOut = Field(default_factory=StockLiveOiTotalsOut)
    buy_ce: StockLiveLegOut | None = None
    buy_pe: StockLiveLegOut | None = None
    market_move: MarketMoveSnippetOut = Field(default_factory=MarketMoveSnippetOut)


class StockOptionsLiveResponse(BaseModel):
    ok: bool = True
    error: str | None = None
    refreshed_at: str = ""
    cache_age_seconds: float = 0.0
    disclaimer: str = ""
    stocks: list[StockLiveRowOut] = Field(default_factory=list)
