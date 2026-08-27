from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Query

from models.schemas import (
    AggregateChainOiOut,
    DiagonalWidgetBlock,
    FutureChartCandleOut,
    HedgingMetaBlock,
    HedgingResponse,
    HedgingStrategyBlock,
    HistoryResponse,
    IndiaVixOut,
    LegSuggestionOut,
    LivePredictionOut,
    NiftyFutureQuoteOut,
    OiFutureChartResponse,
    OiFutureChartTradePlanOut,
    OIStatusResponse,
    OpeningGapOut,
    OpeningRangeOut,
    OpeningSessionFutureTrendOut,
    OpeningSessionOut,
    OpeningWindowBlockOut,
    OpeningWindowHistoryRowOut,
    OpeningWindowProvisionalOut,
    OpeningWindowSnapshotOut,
    OpeningWindowTodayOut,
    OvernightWallsOut,
    SessionDoiVs915Out,
    SessionMovePredictionOut,
    SRLevelsBundle,
    SignalOut,
    SignalsResponse,
    StockLiveRowOut,
    StockOptionLiquidityRow,
    StockOptionsLiveResponse,
    StockOptionsLiquidityResponse,
    WallBreakSignalOut,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
from services.oi_excel_service import (
    get_oi_cache_snapshot,
    oi_auto_update_enabled,
    oi_update_interval_seconds,
    run_oi_excel_cycle,
    set_oi_fatal_error,
)
from services.hedging_service import get_hedging_response
from services.signals_source import load_all_signals
from services.future_chart_service import get_future_chart_payload
from services.stock_options_liquidity import build_stock_options_liquidity_response
from services.stock_options_live_service import get_stock_options_live

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/signals", response_model=SignalsResponse)
def get_signals(limit: int = Query(50, ge=1, le=500)) -> SignalsResponse:
    rows, src = load_all_signals()
    sliced = rows[:limit]
    return SignalsResponse(
        signals=[SignalOut(**r) for r in sliced],
        source=src,
        updated_hint="Poll every 5-10s from the dashboard",
    )


@router.get("/history", response_model=HistoryResponse)
def get_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
) -> HistoryResponse:
    rows, src = load_all_signals()
    total = len(rows)
    start = (page - 1) * page_size
    chunk = rows[start : start + page_size]
    return HistoryResponse(
        signals=[SignalOut(**r) for r in chunk],
        total=total,
        page=page,
        page_size=page_size,
        source=src,
    )


def _coerce_leg_suggestion(raw: object) -> LegSuggestionOut | None:
    if not isinstance(raw, dict):
        return None
    try:
        return LegSuggestionOut(**raw)
    except Exception:
        logger.debug("Skipping invalid leg suggestion payload", exc_info=True)
        return None


def _coerce_sr_levels(raw: object) -> SRLevelsBundle | None:
    if not isinstance(raw, dict):
        return None
    try:
        return SRLevelsBundle.model_validate(raw)
    except Exception:
        logger.debug("Skipping invalid sr_levels payload", exc_info=True)
        return None


def _coerce_nifty_future(raw: object) -> NiftyFutureQuoteOut | None:
    if not isinstance(raw, dict):
        return None
    try:
        return NiftyFutureQuoteOut(**raw)
    except Exception:
        logger.debug("Skipping invalid nifty_future payload", exc_info=True)
        return None


def _coerce_opening_snapshot(raw: object) -> OpeningWindowSnapshotOut | None:
    if not isinstance(raw, dict):
        return None
    try:
        return OpeningWindowSnapshotOut(
            at=str(raw.get("at") or ""),
            ltp=float(raw.get("ltp") or 0),
            oi=int(raw.get("oi") or 0),
            symbol=str(raw.get("symbol") or ""),
        )
    except Exception:
        return None


def _coerce_live_prediction(raw: object) -> LivePredictionOut | None:
    if not isinstance(raw, dict):
        return None
    try:
        ag = raw.get("aggregate_chain")
        sm = raw.get("session_move")
        walls_raw = raw.get("walls")
        walls: list[WallBreakSignalOut] = []
        if isinstance(walls_raw, list):
            for w in walls_raw:
                if isinstance(w, dict):
                    walls.append(WallBreakSignalOut(**w))
        return LivePredictionOut(
            disclaimer=str(raw.get("disclaimer") or ""),
            spot=float(raw.get("spot") or 0),
            opening_trend_key=str(raw.get("opening_trend_key") or ""),
            opening_trend_label=str(raw.get("opening_trend_label") or ""),
            opening_trend_is_provisional=bool(raw.get("opening_trend_is_provisional")),
            aggregate_chain=AggregateChainOiOut(**ag) if isinstance(ag, dict) else AggregateChainOiOut(),
            walls=walls,
            session_move=(
                SessionMovePredictionOut(
                    bias_key=str(sm.get("bias_key") or ""),
                    headline=str(sm.get("headline") or ""),
                    detail_lines=list(sm.get("detail_lines") or []),
                )
                if isinstance(sm, dict)
                else SessionMovePredictionOut()
            ),
        )
    except Exception:
        logger.debug("Skipping invalid live_prediction payload", exc_info=True)
        return None


def _coerce_india_vix(raw: object) -> IndiaVixOut | None:
    if not isinstance(raw, dict):
        return None
    try:
        ltp = raw.get("ltp")
        return IndiaVixOut(
            symbol=str(raw.get("symbol") or "India VIX"),
            instrument_key=str(raw.get("instrument_key") or ""),
            ltp=float(ltp) if ltp is not None else None,
            net_change=float(raw["net_change"]) if raw.get("net_change") is not None else None,
            ohlc_open=float(raw["ohlc_open"]) if raw.get("ohlc_open") is not None else None,
            ohlc_close=float(raw["ohlc_close"]) if raw.get("ohlc_close") is not None else None,
        )
    except Exception:
        return None


def _coerce_opening_session(raw: object) -> OpeningSessionOut | None:
    if not isinstance(raw, dict):
        return None
    try:
        gap = raw.get("gap") if isinstance(raw.get("gap"), dict) else {}
        walls = raw.get("overnight_walls") if isinstance(raw.get("overnight_walls"), dict) else {}
        or5 = raw.get("opening_range_5m") if isinstance(raw.get("opening_range_5m"), dict) else {}
        or15 = raw.get("opening_range_15m") if isinstance(raw.get("opening_range_15m"), dict) else {}
        ft = raw.get("future_trend") if isinstance(raw.get("future_trend"), dict) else {}
        doi = raw.get("session_doi_vs_915") if isinstance(raw.get("session_doi_vs_915"), dict) else {}
        p5 = raw.get("price_vs_or_5m") if isinstance(raw.get("price_vs_or_5m"), dict) else {}
        p15 = raw.get("price_vs_or_15m") if isinstance(raw.get("price_vs_or_15m"), dict) else {}
        gift = raw.get("gift_nifty") if isinstance(raw.get("gift_nifty"), dict) else {}
        return OpeningSessionOut(
            disclaimer=str(raw.get("disclaimer") or ""),
            phase=str(raw.get("phase") or ""),
            phase_label=str(raw.get("phase_label") or ""),
            as_of=str(raw.get("as_of") or ""),
            bias_key=str(raw.get("bias_key") or ""),
            headline=str(raw.get("headline") or ""),
            detail_lines=list(raw.get("detail_lines") or []),
            gap=OpeningGapOut(**gap) if gap else OpeningGapOut(),
            overnight_walls=OvernightWallsOut(**walls) if walls else OvernightWallsOut(),
            india_vix=_coerce_india_vix(raw.get("india_vix")),
            opening_range_5m=OpeningRangeOut(**or5) if or5 else OpeningRangeOut(minutes=5),
            opening_range_15m=OpeningRangeOut(**or15) if or15 else OpeningRangeOut(minutes=15),
            price_vs_or_5m={str(k): str(v) for k, v in p5.items()},
            price_vs_or_15m={str(k): str(v) for k, v in p15.items()},
            future_trend=OpeningSessionFutureTrendOut(**ft) if ft else OpeningSessionFutureTrendOut(),
            session_doi_vs_915=SessionDoiVs915Out(**doi) if doi else SessionDoiVs915Out(),
            gift_nifty=gift,
        )
    except Exception:
        logger.debug("Skipping invalid opening_session payload", exc_info=True)
        return None


def _coerce_opening_provisional(raw: object) -> OpeningWindowProvisionalOut | None:
    if not isinstance(raw, dict):
        return None
    try:
        return OpeningWindowProvisionalOut(
            trend_key=str(raw.get("trend_key") or ""),
            trend_label=str(raw.get("trend_label") or ""),
            d_ltp=float(raw.get("d_ltp") or 0),
            d_oi=int(raw.get("d_oi") or 0),
            ltp=float(raw.get("ltp") or 0),
            oi=int(raw.get("oi") or 0),
        )
    except Exception:
        return None


def _coerce_opening_window(c: dict) -> OpeningWindowBlockOut | None:
    from services.opening_window_service import build_history_rows, merge_provisional_into_today, today_payload_from_store

    today_raw = c.get("opening_window_today")
    if not isinstance(today_raw, dict):
        today_raw = today_payload_from_store(PROJECT_ROOT)
    if isinstance(today_raw, dict):
        today_raw = {**today_raw}

    nf = c.get("nifty_future")
    if isinstance(today_raw, dict) and isinstance(nf, dict):
        fl = nf.get("ltp")
        fo = nf.get("oi")
        merge_provisional_into_today(
            today_raw,
            future_ltp=float(fl) if fl is not None else None,
            future_oi=int(fo) if fo is not None else None,
        )

    hist = c.get("opening_window_history")
    if not isinstance(hist, list) or not hist:
        hist = build_history_rows(PROJECT_ROOT, limit=30)
    rows: list[OpeningWindowHistoryRowOut] = []
    for item in hist:
        if not isinstance(item, dict):
            continue
        try:
            rows.append(OpeningWindowHistoryRowOut(**item))
        except Exception:
            continue
    today_out: OpeningWindowTodayOut | None = None
    if isinstance(today_raw, dict):
        try:
            nb = today_raw.get("now_is_before_930")
            if nb is None:
                nb = today_raw.get("now_is_before_915")
            today_out = OpeningWindowTodayOut(
                date=str(today_raw.get("date") or ""),
                ready=bool(today_raw.get("ready")),
                now_is_before_930=bool(nb) if nb is not None else False,
                trend_key=str(today_raw.get("trend_key") or ""),
                trend_label=str(today_raw.get("trend_label") or ""),
                d_ltp=today_raw.get("d_ltp") if today_raw.get("d_ltp") is not None else None,
                d_oi=today_raw.get("d_oi") if today_raw.get("d_oi") is not None else None,
                early=_coerce_opening_snapshot(today_raw.get("early")),
                late=_coerce_opening_snapshot(today_raw.get("late")),
                provisional=_coerce_opening_provisional(today_raw.get("provisional")),
            )
        except Exception:
            today_out = None
    note = (
        "Uses NIFTY index future: anchor = first poll in 09:15-09:29 IST; compare to first poll at/after 09:30. "
        "Between 09:15 and 09:30, today's trend updates live vs that anchor. "
        "Keep the backend running through the open so both legs are captured."
    )
    return OpeningWindowBlockOut(today=today_out, history=rows, note=note)


def _oi_status_from_cache() -> OIStatusResponse:
    c = get_oi_cache_snapshot()
    buy_ce = c.get("buy_ce")
    buy_pe = c.get("buy_pe")
    return OIStatusResponse(
        ok=bool(c.get("updated_at")) and c.get("error") is None,
        error=c.get("error"),
        excel_export_error=c.get("excel_export_error"),
        updated_at=c.get("updated_at"),
        excel_path=c.get("excel_path"),
        spot=float(c.get("spot") or 0),
        expiry=str(c.get("expiry") or ""),
        pcr=c.get("pcr"),
        total_call_oi=c.get("total_call_oi"),
        total_put_oi=c.get("total_put_oi"),
        total_call_volume=c.get("total_call_volume"),
        total_put_volume=c.get("total_put_volume"),
        buy_ce=_coerce_leg_suggestion(buy_ce),
        buy_pe=_coerce_leg_suggestion(buy_pe),
        market_move_label=str(c.get("market_move_label") or ""),
        sr_levels=_coerce_sr_levels(c.get("sr_levels")),
        nifty_future=_coerce_nifty_future(c.get("nifty_future")),
        opening_window=_coerce_opening_window(c),
        live_prediction=_coerce_live_prediction(c.get("live_prediction")),
        opening_session=_coerce_opening_session(c.get("opening_session")),
        india_vix=_coerce_india_vix(c.get("india_vix")),
        auto_update_enabled=oi_auto_update_enabled(),
        update_interval_seconds=oi_update_interval_seconds(),
    )


@router.get("/oi/status", response_model=OIStatusResponse)
def get_oi_status() -> OIStatusResponse:
    """Latest CE/PE OI snapshot, Excel path, and suggested BUY CE / BUY PE strikes."""
    return _oi_status_from_cache()


@router.post("/oi/refresh", response_model=OIStatusResponse)
def post_oi_refresh() -> OIStatusResponse:
    """Run one immediate fetch → Excel + cache update (may take a few seconds)."""
    try:
        run_oi_excel_cycle()
    except Exception as e:
        logger.exception("OI refresh failed")
        set_oi_fatal_error(str(e))
    return _oi_status_from_cache()


def _coerce_future_chart(raw: dict) -> OiFutureChartResponse:
    candles: list[FutureChartCandleOut] = []
    for x in raw.get("candles") or []:
        if isinstance(x, dict):
            try:
                candles.append(FutureChartCandleOut(**x))
            except Exception:
                continue
    tp_raw = raw.get("trade_plan") if isinstance(raw.get("trade_plan"), dict) else {}
    try:
        trade_plan = OiFutureChartTradePlanOut(**tp_raw)
    except Exception:
        trade_plan = OiFutureChartTradePlanOut()
    return OiFutureChartResponse(
        ok=bool(raw.get("ok")),
        error=raw.get("error"),
        chart_warning=raw.get("chart_warning"),
        symbol=str(raw.get("symbol") or ""),
        instrument_key=str(raw.get("instrument_key") or ""),
        spot=float(raw.get("spot") or 0),
        ltp=float(raw.get("ltp") or 0),
        session_day_ist=str(raw.get("session_day_ist") or ""),
        candles=candles,
        trade_plan=trade_plan,
        chain_refreshed_at=raw.get("chain_refreshed_at"),
        candles_fetched_at=raw.get("candles_fetched_at"),
    )


@router.get("/oi/future-chart", response_model=OiFutureChartResponse)
def get_oi_future_chart() -> OiFutureChartResponse:
    """
    NIFTY index future 1-minute candles (when available) plus a heuristic plan from Σ CE/PE OI, PCR,
    session ΔOI, live Σ CE/PE volume & poll Δvol, candle patterns, and optional pivot R1/S1 from the OI cache.
    If the future instrument is missing or candles fail, `chart_warning` is set and the plan may use chain-only logic.
    """
    raw = get_future_chart_payload()
    return _coerce_future_chart(raw if isinstance(raw, dict) else {})


@router.get("/stock-options/live", response_model=StockOptionsLiveResponse)
def get_stock_options_live_endpoint(force: bool = Query(False, description="Bypass short cache")) -> StockOptionsLiveResponse:
    """
    Live option chain per tracked stock: suggested BUY CE/PE, total OI, OI change (vs prev close
    and vs prior server refresh). Requires UPSTOX_ACCESS_TOKEN. Refreshes are cached ~55s unless force=true.
    """
    raw = get_stock_options_live(force_refresh=force)
    stocks = [StockLiveRowOut.model_validate(s) for s in raw.get("stocks") or []]
    return StockOptionsLiveResponse(
        ok=bool(raw.get("ok")),
        error=raw.get("error"),
        refreshed_at=str(raw.get("refreshed_at") or ""),
        cache_age_seconds=float(raw.get("cache_age_seconds") or 0),
        disclaimer=str(raw.get("disclaimer") or ""),
        stocks=stocks,
    )


@router.get("/stock-options/liquidity", response_model=StockOptionsLiquidityResponse)
def get_stock_options_liquidity() -> StockOptionsLiquidityResponse:
    """
    Curated high-liquidity NSE equity F&O names for stock-option trading, with sector and notes.

    Data is static guidance, not a live chain. Use for screening; verify quotes and lots with your broker.
    """
    raw = build_stock_options_liquidity_response()
    return StockOptionsLiquidityResponse(
        disclaimer=raw["disclaimer"],
        market=raw["market"],
        stocks=[StockOptionLiquidityRow(**s) for s in raw["stocks"]],
        how_to_use=list(raw.get("how_to_use") or []),
    )


@router.get("/hedging", response_model=HedgingResponse)
def get_hedging() -> HedgingResponse:
    """
    Multi-horizon hedging / spread suggestions from live OI cache + recent CE/PE signals.

    Strikes are illustrative (NIFTY grid); validate premiums and margin with your broker.
    """
    raw = get_hedging_response()
    return HedgingResponse(
        intraday=HedgingStrategyBlock(**raw["intraday"]),
        weekly=HedgingStrategyBlock(**raw["weekly"]),
        monthly=HedgingStrategyBlock(**raw["monthly"]),
        iron_condor=HedgingStrategyBlock(**raw["iron_condor"]),
        diagonal=DiagonalWidgetBlock(**raw["diagonal"]),
        meta=HedgingMetaBlock(**raw["meta"]),
    )
