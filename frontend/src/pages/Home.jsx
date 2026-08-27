import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";
import SRLevelsPanel from "../components/SRLevelsPanel.jsx";
import OpeningSessionCards from "../components/OpeningSessionCards.jsx";
import { OiFutureChartWithDetails, OiFutureTradePlanOnly } from "../components/OiFutureChartWidgets.jsx";
import "./Home.css";

const OI_REFRESH_MS = 15000;
const FUTURE_CHART_REFRESH_MS = 20000;
const HEDGING_REFRESH_MS = 12000;

const inrFmt = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

function formatInr(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return inrFmt.format(Number(v));
}

function formatNetPremium(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  if (n === 0) return formatInr(0);
  return n > 0 ? `Pay ${formatInr(n)}` : `Receive ${formatInr(Math.abs(n))}`;
}

function wallVerdictClass(verdict) {
  const v = String(verdict || "");
  if (v === "break_up_more_likely" || v === "hold_floor_more_likely") return "wall-verdict wall-verdict--support-up";
  if (v === "break_down_more_likely" || v === "hold_cap_more_likely") return "wall-verdict wall-verdict--resist-dn";
  return "wall-verdict wall-verdict--neutral";
}

function OiPriceFutureLegend() {
  return (
    <div className="oi-future-legend-wrap">
      <h3 className="oi-future-legend-wrap__title">OI vs price (index future)</h3>
      <div className="openwin-legend muted small">
        <div>
          <strong>OI↑</strong> + <strong>price↑</strong> → Long buildup
        </div>
        <div>
          <strong>OI↑</strong> + <strong>price↓</strong> → Short buildup
        </div>
        <div>
          <strong>OI↓</strong> + <strong>price↓</strong> → Profit booking
        </div>
        <div>
          <strong>OI↓</strong> + <strong>price↑</strong> → Short covering
        </div>
      </div>
    </div>
  );
}

function legLine(row) {
  const desc = row.description || "";
  const ltp = row.ltp != null && !row.missing_quote ? ` @ LTP ${Number(row.ltp).toFixed(2)}` : row.missing_quote ? " (no quote)" : "";
  let flow = "";
  if (row.premium_debit_inr != null && !row.missing_quote) {
    const p = Number(row.premium_debit_inr);
    flow = p >= 0 ? ` · pay ${formatInr(p)}` : ` · rcv ${formatInr(Math.abs(p))}`;
  }
  return `${desc}${ltp}${flow}`;
}

function HedgingStrategyCard({ horizon, horizonClass, data }) {
  if (!data) return null;
  const confPct = Math.round((data.confidence ?? 0) * 100);
  const rows =
    data.legs_detail && data.legs_detail.length > 0
      ? data.legs_detail
      : (data.legs || []).map((t) => ({ description: t, ltp: null, missing_quote: true }));
  const rollover = Array.isArray(data.rollover) ? data.rollover : [];

  return (
    <article className={`hedge-card hedge-card--${horizonClass}`}>
      <div className="hedge-card__top">
        <span className="hedge-card__horizon">{horizon}</span>
        <span className="hedge-card__conf" title="Heuristic confidence">
          {confPct}%
        </span>
      </div>
      <h3 className="hedge-card__strategy">{data.strategy}</h3>
      {(data.long_expiry_display || data.short_expiry_display) && (
        <div className="hedge-diag-expiry" aria-label="Listed expiries for diagonal legs">
          <div className="hedge-diag-expiry__row">
            <span className="hedge-diag-expiry__k">Long leg (buy CE)</span>
            <span
              className="hedge-diag-expiry__v"
              title={data.long_expiry_iso ? `ISO ${data.long_expiry_iso}` : undefined}
            >
              {data.long_expiry_display || "—"}
            </span>
          </div>
          <div className="hedge-diag-expiry__row">
            <span className="hedge-diag-expiry__k">Short leg (sell CE)</span>
            <span
              className="hedge-diag-expiry__v"
              title={data.short_expiry_iso ? `ISO ${data.short_expiry_iso}` : undefined}
            >
              {data.short_expiry_display || "—"}
            </span>
          </div>
        </div>
      )}
      {data.lot_size != null && (
        <p className="hedge-card__lot muted small">Lot × {data.lot_size} (NIFTY index options)</p>
      )}
      <ul className="hedge-card__legs">
        {rows.map((row, i) => (
          <li key={`${row.description}-${i}`}>{legLine(row)}</li>
        ))}
      </ul>

      <div className="hedge-card__inr">
        <div className="hedge-card__inr-cell">
          <span className="hedge-card__inr-label">Net premium (entry)</span>
          <span className="hedge-card__inr-val">{formatNetPremium(data.net_premium_inr)}</span>
        </div>
        <div className="hedge-card__inr-cell">
          <span className="hedge-card__inr-label">Max profit (expiry)</span>
          <span className="hedge-card__inr-val hedge-card__inr-val--pos">{formatInr(data.max_profit_inr)}</span>
        </div>
        <div className="hedge-card__inr-cell">
          <span className="hedge-card__inr-label">Max loss (expiry)</span>
          <span className="hedge-card__inr-val hedge-card__inr-val--neg">{formatInr(data.max_loss_inr)}</span>
        </div>
        <div className="hedge-card__inr-cell">
          <span className="hedge-card__inr-label">Indicative margin</span>
          <span className="hedge-card__inr-val">{formatInr(data.margin_inr)}</span>
        </div>
      </div>

      {data.pnl_disclaimer && <p className="hedge-card__disc muted small">{data.pnl_disclaimer}</p>}

      {rollover.length > 0 && (
        <div className="hedge-rollover">
          <h4 className="hedge-rollover__title">Rollover playbook</h4>
          <p className="hedge-rollover__hint muted small">
            Cues update with the same live regime as the rest of the dashboard (spot move, bias, vol).
            Not personalized to your fills.
          </p>
          <ul className="hedge-rollover__list">
            {rollover.map((row, i) => (
              <li key={i} className="hedge-rollover__item">
                <span className="hedge-rollover__trigger">{row.trigger}</span>
                <span className="hedge-rollover__action">{row.action}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="hedge-card__reason">{data.reason}</p>
      {(data.max_profit || data.max_loss || data.margin_note) && (
        <dl className="hedge-card__pl">
          {data.max_profit ? (
            <>
              <dt>Notes · max profit</dt>
              <dd>{data.max_profit}</dd>
            </>
          ) : null}
          {data.max_loss ? (
            <>
              <dt>Notes · max loss</dt>
              <dd>{data.max_loss}</dd>
            </>
          ) : null}
          {data.margin_note ? (
            <>
              <dt>Notes · margin</dt>
              <dd>{data.margin_note}</dd>
            </>
          ) : null}
        </dl>
      )}
    </article>
  );
}

export default function Home() {
  const [oi, setOi] = useState(null);
  const [oiLoading, setOiLoading] = useState(false);
  const [oiBoot, setOiBoot] = useState(true);
  const [hedging, setHedging] = useState(null);
  const [hedgingErr, setHedgingErr] = useState(null);
  const [futureChart, setFutureChart] = useState(null);

  const fetchOi = useCallback(async () => {
    try {
      const { data } = await api.get("/oi/status");
      setOi(data);
    } catch (e) {
      setOi({
        ok: false,
        error: e?.message || "Failed to load OI / strike suggestions",
        buy_ce: null,
        buy_pe: null,
      });
    } finally {
      setOiBoot(false);
    }
  }, []);

  const fetchHedging = useCallback(async () => {
    setHedgingErr(null);
    try {
      const { data } = await api.get("/hedging");
      setHedging(data);
    } catch (e) {
      setHedging(null);
      setHedgingErr(e?.message || "Failed to load hedging strategies");
    }
  }, []);

  const refreshOiNow = useCallback(async () => {
    setOiLoading(true);
    try {
      const { data } = await api.post("/oi/refresh", null, { timeout: 60000 });
      setOi(data);
    } catch (e) {
      setOi({
        ok: false,
        error: e?.message || "OI refresh failed",
        buy_ce: null,
        buy_pe: null,
      });
    } finally {
      setOiLoading(false);
    }
  }, []);

  const fetchFutureChart = useCallback(async () => {
    try {
      const { data } = await api.get("/oi/future-chart");
      setFutureChart(data);
    } catch (e) {
      setFutureChart({
        ok: false,
        error: e?.message || "Failed to load future chart",
        candles: [],
        trade_plan: {},
      });
    }
  }, []);

  useEffect(() => {
    fetchOi();
    const id = setInterval(fetchOi, OI_REFRESH_MS);
    return () => clearInterval(id);
  }, [fetchOi]);

  useEffect(() => {
    fetchFutureChart();
    const id = setInterval(fetchFutureChart, FUTURE_CHART_REFRESH_MS);
    return () => clearInterval(id);
  }, [fetchFutureChart]);

  useEffect(() => {
    fetchHedging();
    const id = setInterval(fetchHedging, HEDGING_REFRESH_MS);
    return () => clearInterval(id);
  }, [fetchHedging]);

  const chainTime =
    oi?.updated_at &&
    new Date(oi.updated_at).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });

  return (
    <>
      <header className="dash-header">
        <div>
          <h1 className="title">NIFTY OI &amp; hedging</h1>
          <p className="subtitle">
            Live option chain, OI support/resistance &amp; Excel · OI poll {OI_REFRESH_MS / 1000}s · hedging{" "}
            {HEDGING_REFRESH_MS / 1000}s
          </p>
        </div>
        <div className="header-meta">
          {oiBoot && <span className="pill pill--load">Loading chain…</span>}
          {oiLoading && !oiBoot && <span className="pill pill--load">Refreshing chain…</span>}
          {oi?.ok && chainTime && (
            <span className="pill pill--ok" title="Last successful option-chain snapshot">
              Chain {chainTime}
            </span>
          )}
          {oi && !oi.ok && oi.error && <span className="pill pill--err">Chain: setup required</span>}
        </div>
      </header>

      <section className="card oi-panel">
        <div className="card-head oi-panel__head">
          <div>
            <h2>CE / PE open interest</h2>
            <p className="muted small oi-panel__sub">
              Excel updated every {oi?.update_interval_seconds ?? 60}s (see{" "}
              <code className="code-inline">exports/nifty_oi_live.xlsx</code> or{" "}
              <code className="code-inline">OI_EXCEL_PATH</code>). Strikes use your{" "}
              <code className="code-inline">config/analysis.yaml</code> liquidity &amp; ATM/OTM rules.
            </p>
          </div>
          <button type="button" className="btn btn--ghost" onClick={refreshOiNow} disabled={oiLoading || oiBoot}>
            {oiLoading ? "Refreshing…" : "Refresh OI now"}
          </button>
        </div>

        {oiBoot && <p className="muted small oi-panel__boot">Fetching /oi/status…</p>}

        {oi && oi.error && (
            <p className="oi-panel__warn">
              {oi.error}
              {/upstox|access_token|settings invalid|\.env/i.test(oi.error || "") ? (
                <span className="muted small">
                  {" "}
                  — Ensure <code className="code-inline">UPSTOX_ACCESS_TOKEN</code> is set in the project root{" "}
                  <code className="code-inline">.env</code> and restart the API.
                </span>
              ) : null}
            </p>
          )}

        {oi?.excel_export_error && (
          <p className="oi-panel__warn oi-panel__warn--soft">{oi.excel_export_error}</p>
        )}

        {oi && (
          <>
          <div className="oi-meta">
            {oi.spot > 0 && (
              <span className="pill pill--muted">
                Spot {oi.spot.toFixed(2)} · Exp {oi.expiry || "—"}
              </span>
            )}
            {oi.pcr != null && (
              <span className="pill pill--muted">PCR {Number(oi.pcr).toFixed(4)}</span>
            )}
            {oi.india_vix?.ltp != null && (
              <span className="pill pill--muted" title="India VIX from Upstox">
                VIX {Number(oi.india_vix.ltp).toFixed(2)}
                {oi.india_vix.net_change != null
                  ? ` (${Number(oi.india_vix.net_change) >= 0 ? "+" : ""}${Number(oi.india_vix.net_change).toFixed(2)})`
                  : ""}
              </span>
            )}
            {oi.opening_session?.gap?.label && (
              <span
                className="pill pill--muted"
                title="Future session open vs previous close"
              >
                {oi.opening_session.gap.label}
              </span>
            )}
            {oi.total_call_oi != null && (
              <span className="pill pill--muted">Σ CE OI {(oi.total_call_oi / 1e5).toFixed(2)}L</span>
            )}
            {oi.total_put_oi != null && (
              <span className="pill pill--muted">Σ PE OI {(oi.total_put_oi / 1e5).toFixed(2)}L</span>
            )}
            {oi.total_call_volume != null && (
              <span className="pill pill--muted" title="Summed CE volume across strikes (session)">
                Σ CE vol {Number(oi.total_call_volume).toLocaleString("en-IN")}
              </span>
            )}
            {oi.total_put_volume != null && (
              <span className="pill pill--muted" title="Summed PE volume across strikes (session)">
                Σ PE vol {Number(oi.total_put_volume).toLocaleString("en-IN")}
              </span>
            )}
            {oi.market_move_label && (
              <span className="pill pill--ok">Move: {oi.market_move_label}</span>
            )}
            {oi.updated_at && (
              <span className="pill pill--ok">
                Chain {new Date(oi.updated_at).toLocaleTimeString()}
              </span>
            )}
            {oi.excel_path && (
              <span className="pill pill--muted" title={oi.excel_path}>
                Excel: …{oi.excel_path.slice(-40)}
              </span>
            )}
          </div>

          <OiPriceFutureLegend />

          <div className="fut-open-grid">
            {oi.nifty_future && (
              <div className="fut-card">
                <h3 className="fut-card__title">NIFTY index future (live)</h3>
                <p className="muted small fut-card__sub">
                  Nearest-month contract from Upstox; same refresh as the option chain.
                </p>
                <div className="fut-card__main">
                  <div>
                    <span className="fut-card__sym">{oi.nifty_future.symbol || "NIFTY FUT"}</span>
                    <p className="fut-card__ltp">{Number(oi.nifty_future.ltp).toFixed(2)}</p>
                    <p className="muted small">LTP</p>
                  </div>
                  <ul className="fut-card__stats">
                    <li>
                      <span className="fut-card__k">OI</span>
                      <span className="fut-card__v">
                        {oi.nifty_future.oi != null ? Number(oi.nifty_future.oi).toLocaleString() : "—"}
                      </span>
                    </li>
                    <li>
                      <span className="fut-card__k">Volume</span>
                      <span className="fut-card__v">
                        {oi.nifty_future.volume != null
                          ? Number(oi.nifty_future.volume).toLocaleString()
                          : "—"}
                      </span>
                    </li>
                    {oi.nifty_future.net_change != null && (
                      <li>
                        <span className="fut-card__k">Net chg</span>
                        <span
                          className={
                            Number(oi.nifty_future.net_change) >= 0 ? "fut-card__v fut-card__v--up" : "fut-card__v fut-card__v--dn"
                          }
                        >
                          {Number(oi.nifty_future.net_change) >= 0 ? "+" : ""}
                          {Number(oi.nifty_future.net_change).toFixed(2)}
                        </span>
                      </li>
                    )}
                  </ul>
                </div>
                {(oi.nifty_future.ohlc_open != null || oi.nifty_future.ohlc_high != null) && (
                  <p className="muted small fut-card__ohlc">
                    Session OHLC: O {oi.nifty_future.ohlc_open != null ? Number(oi.nifty_future.ohlc_open).toFixed(2) : "—"}{" "}
                    H {oi.nifty_future.ohlc_high != null ? Number(oi.nifty_future.ohlc_high).toFixed(2) : "—"}{" "}
                    L {oi.nifty_future.ohlc_low != null ? Number(oi.nifty_future.ohlc_low).toFixed(2) : "—"}{" "}
                    C {oi.nifty_future.ohlc_close != null ? Number(oi.nifty_future.ohlc_close).toFixed(2) : "—"}
                    {oi.opening_session?.gap?.gap_points != null && (
                      <>
                        {" "}
                        · Gap {Number(oi.opening_session.gap.gap_points) >= 0 ? "+" : ""}
                        {Number(oi.opening_session.gap.gap_points).toFixed(1)} vs prev close
                      </>
                    )}
                  </p>
                )}
              </div>
            )}
          </div>

          <div className="fut-oi-chart-grid">
            <OiFutureChartWithDetails fc={futureChart} />
            <OiFutureTradePlanOnly fc={futureChart} />
          </div>

          <OpeningSessionCards session={oi.opening_session} />

          {oi.live_prediction &&
            Array.isArray(oi.live_prediction.walls) &&
            oi.live_prediction.walls.length > 0 && (
              <div className="live-pred-card live-pred-card--slim">
                <div className="live-pred-card__head">
                  <div>
                    <h3 className="live-pred-card__title">OI walls — break vs hold</h3>
                    <p className="muted small live-pred-card__sub">
                      Live ΔOI at nearest support / resistance (vs prev close). Open bias, gap, OR, and chain totals are
                      in the cards above.
                    </p>
                  </div>
                </div>
                <p className="muted small live-pred-disclaimer">
                  {oi.live_prediction.disclaimer || "Heuristic wall read from option ΔOI — not advice."}
                </p>
                <ul className="live-pred-wall-list">
                  {oi.live_prediction.walls.map((w, i) => (
                    <li key={`${w.strike}-${w.role}-${i}`} className="live-pred-wall-item">
                      <div className="live-pred-wall-item__top">
                        <span className="live-pred-wall-item__role">
                          {w.role === "resistance" ? "Resistance" : "Support"} @ {w.strike}
                        </span>
                        <span className={wallVerdictClass(w.break_verdict)}>{w.verdict_label}</span>
                      </div>
                      <p className="muted small live-pred-wall-item__reason">{w.reason}</p>
                      <p className="live-pred-wall-item__oi muted small">
                        CE OI {Number(w.ce_oi).toLocaleString()} (Δ {Number(w.ce_oi_change) >= 0 ? "+" : ""}
                        {Number(w.ce_oi_change).toLocaleString()}) · PE OI {Number(w.pe_oi).toLocaleString()} (Δ{" "}
                        {Number(w.pe_oi_change) >= 0 ? "+" : ""}
                        {Number(w.pe_oi_change).toLocaleString()})
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            )}

          <div className="oi-legs">
            <div className="oi-leg oi-leg--ce">
              <h3 className="oi-leg__title">Suggested BUY CE</h3>
              {oi.buy_ce ? (
                <>
                  <p className="oi-leg__strike">{Math.round(oi.buy_ce.strike)}</p>
                  <ul className="oi-leg__stats">
                    <li>LTP {Number(oi.buy_ce.ltp).toFixed(2)}</li>
                    <li>OI {oi.buy_ce.open_interest?.toLocaleString?.() ?? oi.buy_ce.open_interest}</li>
                    <li>Vol {oi.buy_ce.volume?.toLocaleString?.() ?? oi.buy_ce.volume}</li>
                  </ul>
                  <p className="oi-leg__note">{oi.buy_ce.execution_note}</p>
                </>
              ) : (
                <p className="muted small">Waiting for first successful chain fetch…</p>
              )}
            </div>
            <div className="oi-leg oi-leg--pe">
              <h3 className="oi-leg__title">Suggested BUY PE</h3>
              {oi.buy_pe ? (
                <>
                  <p className="oi-leg__strike">{Math.round(oi.buy_pe.strike)}</p>
                  <ul className="oi-leg__stats">
                    <li>LTP {Number(oi.buy_pe.ltp).toFixed(2)}</li>
                    <li>OI {oi.buy_pe.open_interest?.toLocaleString?.() ?? oi.buy_pe.open_interest}</li>
                    <li>Vol {oi.buy_pe.volume?.toLocaleString?.() ?? oi.buy_pe.volume}</li>
                  </ul>
                  <p className="oi-leg__note">{oi.buy_pe.execution_note}</p>
                </>
              ) : (
                <p className="muted small">Waiting for first successful chain fetch…</p>
              )}
            </div>
          </div>

          <div className="sr-section">
            <h3 className="sr-section__title">Support &amp; resistance</h3>
            <p className="muted small sr-section__sub">
              <strong>Pivot PP / R1–R2 / S1–S2</strong> use classic formulas on the prior trading session, prior ISO week,
              and prior calendar month from <strong>live NIFTY index daily candles</strong> (refetched on each OI sync).
              <strong> OI walls</strong> use the nearest / weekly / monthly option expiries and rank strikes by PE OI
              (support) and CE OI (resistance).
            </p>
            <SRLevelsPanel bundle={oi.sr_levels} />
          </div>
          </>
        )}
      </section>

      <section className="card hedge-panel">
        <div className="card-head hedge-panel__head">
          <div>
            <h2>Hedging strategies</h2>
            <p className="muted small hedge-panel__sub">
              ₹ amounts = LTP × lot (see chip below) at last chain snapshot; max P/L from European
              intrinsic grid at expiry. Indicative margin ≈ defined-risk loss — broker SPAN can differ.
            </p>
          </div>
          <button type="button" className="btn btn--ghost" onClick={fetchHedging}>
            Refresh hedging
          </button>
        </div>
        {hedgingErr && <p className="oi-panel__warn">{hedgingErr}</p>}
        {hedging?.meta && (
          <div className="hedge-meta">
            <span className="pill pill--muted">Bias {hedging.meta.bias}</span>
            <span className="pill pill--muted">Vol {hedging.meta.volatility}</span>
            {hedging.meta.spot > 0 && (
              <span className="pill pill--muted">Spot {Number(hedging.meta.spot).toFixed(2)}</span>
            )}
            <span className="pill pill--muted">ATM {hedging.meta.atm_strike}</span>
            {hedging.meta.pcr != null && (
              <span className="pill pill--muted">PCR {Number(hedging.meta.pcr).toFixed(4)}</span>
            )}
            <span className="pill pill--ok">
              Regime {Math.round((hedging.meta.regime_confidence ?? 0) * 100)}%
            </span>
            {hedging.meta.nifty_option_lot_size != null && (
              <span className="pill pill--muted">Lot {hedging.meta.nifty_option_lot_size}</span>
            )}
          </div>
        )}
        {hedging?.meta?.signal_context && (
          <p className="muted small hedge-context">{hedging.meta.signal_context}</p>
        )}
        <div className="hedge-grid">
          <HedgingStrategyCard
            horizon="Intraday"
            horizonClass="intraday"
            data={hedging?.intraday}
          />
          <HedgingStrategyCard
            horizon="Weekly"
            horizonClass="weekly"
            data={hedging?.weekly}
          />
          <HedgingStrategyCard
            horizon="Monthly"
            horizonClass="monthly"
            data={hedging?.monthly}
          />
        </div>

        <h3 className="hedge-special__title">Iron condor &amp; diagonal</h3>
        <p className="muted small hedge-special__sub">
          Same <code className="code-inline">/hedging</code> poll as above — strikes, ₹ figures, and diagonal expiry
          weekday/date labels refresh when the option chain sync runs (Upstox contract list).
        </p>
        <div className="hedge-grid hedge-grid--special">
          <HedgingStrategyCard horizon="Iron Condor" horizonClass="ic" data={hedging?.iron_condor} />
          <HedgingStrategyCard horizon="Diagonal" horizonClass="diagonal" data={hedging?.diagonal} />
        </div>
      </section>
    </>
  );
}
