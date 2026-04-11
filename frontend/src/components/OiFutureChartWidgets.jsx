import { useEffect, useRef } from "react";
import { ColorType, CrosshairMode, createChart } from "lightweight-charts";

function fmtTs(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });
  } catch {
    return iso;
  }
}

function fmtInt(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString("en-IN");
}

function fmtSignedInt(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  return `${n >= 0 ? "+" : ""}${n.toLocaleString("en-IN")}`;
}

/** Σ CE vs Σ PE: live OI, volume, session ΔOI (same chain snapshot as chart). */
function ChainCePeSnapshot({ p }) {
  return (
    <div className="fut-plan-cepe-grid" aria-label="Call versus put chain totals">
      <div className="fut-plan-cepe fut-plan-cepe--ce">
        <h4 className="fut-plan-cepe__title">Σ CE (call side)</h4>
        <dl className="fut-plan-cepe__dl">
          <div>
            <dt>Open interest</dt>
            <dd className="mono">{fmtInt(p.total_call_oi)}</dd>
          </div>
          <div>
            <dt>Volume (chain)</dt>
            <dd className="mono">{fmtInt(p.total_call_volume)}</dd>
          </div>
          <div>
            <dt>Δ volume (vs last refresh)</dt>
            <dd className="mono" title="Σ CE volume now minus Σ CE volume on prior successful chain poll">
              {p.total_ce_volume_change_since_last_poll == null
                ? "— (first poll)"
                : fmtSignedInt(p.total_ce_volume_change_since_last_poll)}
            </dd>
          </div>
          <div>
            <dt>ΔOI vs prev OI</dt>
            <dd className="mono">{fmtSignedInt(p.total_ce_oi_change)}</dd>
          </div>
        </dl>
      </div>
      <div className="fut-plan-cepe fut-plan-cepe--pe">
        <h4 className="fut-plan-cepe__title">Σ PE (put side)</h4>
        <dl className="fut-plan-cepe__dl">
          <div>
            <dt>Open interest</dt>
            <dd className="mono">{fmtInt(p.total_put_oi)}</dd>
          </div>
          <div>
            <dt>Volume (chain)</dt>
            <dd className="mono">{fmtInt(p.total_put_volume)}</dd>
          </div>
          <div>
            <dt>Δ volume (vs last refresh)</dt>
            <dd className="mono" title="Σ PE volume now minus Σ PE volume on prior successful chain poll">
              {p.total_pe_volume_change_since_last_poll == null
                ? "— (first poll)"
                : fmtSignedInt(p.total_pe_volume_change_since_last_poll)}
            </dd>
          </div>
          <div>
            <dt>ΔOI vs prev OI</dt>
            <dd className="mono">{fmtSignedInt(p.total_pe_oi_change)}</dd>
          </div>
        </dl>
      </div>
    </div>
  );
}

/** Shared copy: Σ CE/PE, PCR, ΔOI + entry/exit block (used in two dashboard widgets). */
export function OiFutureTradePlanBody({ fc }) {
  if (!fc) {
    return <p className="muted small">Loading synthesis…</p>;
  }
  if (!fc.ok && fc.error) {
    return <p className="oi-panel__warn">{fc.error}</p>;
  }
  const p = fc.trade_plan || {};
  const side = String(p.side || "flat");
  const sideClass =
    side === "long" ? "fut-plan-side fut-plan-side--long" : side === "short" ? "fut-plan-side fut-plan-side--short" : "fut-plan-side fut-plan-side--flat";

  return (
    <div className="fut-plan-body">
      <div className="fut-plan-meta">
        <span className="pill pill--muted">{fc.symbol || "NIFTY FUT"}</span>
        {fc.session_day_ist ? (
          <span className="pill pill--muted">Session {fc.session_day_ist} (IST date)</span>
        ) : null}
        {fc.ltp != null ? <span className="pill pill--muted">LTP {Number(fc.ltp).toFixed(2)}</span> : null}
        {fc.chain_refreshed_at ? (
          <span className="pill pill--ok" title="Option chain snapshot used for OI/PCR">
            Chain {new Date(fc.chain_refreshed_at).toLocaleTimeString()}
          </span>
        ) : null}
        {fc.candles_fetched_at ? (
          <span className="pill pill--muted" title="When 1m candles were last pulled">
            Candles {new Date(fc.candles_fetched_at).toLocaleTimeString()}
          </span>
        ) : null}
      </div>

      {fc.ok && fc.chart_warning ? (
        <p className="fut-chart-warn muted small" role="status">
          {fc.chart_warning}
        </p>
      ) : null}

      <p className="fut-plan-trend">{p.trend_summary || "—"}</p>

      <div className="fut-plan-pattern">
        <span className="fut-plan-pattern__k">Candle pattern</span>
        <span className="fut-plan-pattern__v">{String(p.pattern_name || "").replace(/_/g, " ") || "—"}</span>
        {p.pattern_detail ? <p className="muted small fut-plan-pattern__d">{p.pattern_detail}</p> : null}
      </div>

      <ChainCePeSnapshot p={p} />

      <ul className="fut-plan-oi-lines">
        {(p.oi_metric_lines || []).map((line, i) => (
          <li key={i}>{line}</li>
        ))}
      </ul>

      <div className="fut-plan-exec">
        <h4 className="fut-plan-exec__title">Entry / exit (candles + OI + live volume)</h4>
        <p className="fut-plan-exec__side">
          <span className={sideClass}>{side === "long" ? "Long bias" : side === "short" ? "Short bias" : "Neutral / stand aside"}</span>
        </p>
        <dl className="fut-plan-dl">
          <div>
            <dt>Entry price (anchor)</dt>
            <dd className="mono">{p.entry_price != null ? Number(p.entry_price).toFixed(2) : "—"}</dd>
          </div>
          <div>
            <dt>Entry bar (IST)</dt>
            <dd className="mono">{fmtTs(p.entry_time_iso_ist)}</dd>
          </div>
          <div>
            <dt>Exit target (price)</dt>
            <dd className="mono">{p.exit_price != null ? Number(p.exit_price).toFixed(2) : "—"}</dd>
          </div>
          <div>
            <dt>Stop loss</dt>
            <dd className="mono">{p.stop_loss != null ? Number(p.stop_loss).toFixed(2) : "—"}</dd>
          </div>
        </dl>
        {p.entry_trigger ? <p className="fut-plan-trigger">{p.entry_trigger}</p> : null}
        {p.exit_label ? <p className="muted small">{p.exit_label}</p> : null}
        {p.chart_narrative ? <p className="fut-plan-narr muted small">{p.chart_narrative}</p> : null}
        {p.disclaimer ? <p className="fut-plan-disc muted small">{p.disclaimer}</p> : null}
      </div>
    </div>
  );
}

function FutureCandleChart({ fc }) {
  const ref = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!fc || !el || !fc.ok || !Array.isArray(fc.candles) || fc.candles.length === 0) {
      return undefined;
    }

    const chart = createChart(el, {
      width: el.clientWidth,
      height: 360,
      layout: {
        background: { type: ColorType.Solid, color: "#0b0e14" },
        textColor: "#c8cedd",
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.06)" },
        horzLines: { color: "rgba(255,255,255,0.06)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: "rgba(255,255,255,0.12)" },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.12)" },
    });

    chartRef.current = chart;
    const series = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    const data = fc.candles.map((c) => ({
      time: c.time_unix,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
    series.setData(data);

    const plan = fc.trade_plan || {};
    const priceLines = [];
    const addLine = (price, opts) => {
      if (price == null || Number.isNaN(Number(price))) return;
      priceLines.push(
        series.createPriceLine({
          price: Number(price),
          lineWidth: 1,
          axisLabelVisible: true,
          ...opts,
        }),
      );
    };

    if (plan.side === "long" || plan.side === "short") {
      addLine(plan.entry_price, {
        color: plan.side === "long" ? "#22c55e" : "#ef4444",
        lineStyle: 2,
        title: "Entry",
      });
      addLine(plan.exit_price, { color: "#60a5fa", lineStyle: 0, title: "Exit tgt" });
      addLine(plan.stop_loss, { color: "#a855f7", lineStyle: 3, title: "Stop" });
    } else if (plan.entry_price != null) {
      addLine(plan.entry_price, { color: "#94a3b8", lineStyle: 2, title: "Ref close" });
    }

    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      if (ref.current && chartRef.current) {
        chartRef.current.applyOptions({ width: ref.current.clientWidth });
      }
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      priceLines.forEach((ln) => {
        try {
          ln.remove();
        } catch {
          /* ignore */
        }
      });
      chart.remove();
      chartRef.current = null;
    };
  }, [fc]);

  if (!fc) {
    return <p className="muted small fut-chart-empty">Loading chart…</p>;
  }
  if (!fc.ok && fc.error) {
    return <p className="muted small fut-chart-empty">{fc.error}</p>;
  }
  if (!fc.candles?.length) {
    return <p className="muted small fut-chart-empty">No 1-minute future candles for this session yet.</p>;
  }

  return <div className="fut-chart-canvas" ref={ref} role="img" aria-label="NIFTY future one-minute candles" />;
}

/** Widget A: live future candlesticks + full synthesis details. */
export function OiFutureChartWithDetails({ fc }) {
  return (
    <article className="fut-chart-widget">
      <header className="fut-chart-widget__head">
        <div>
          <h3 className="fut-chart-widget__title">Live future — candles + Σ CE / Σ PE / PCR / ΔOI</h3>
          <p className="muted small fut-chart-widget__sub">
            1-minute NIFTY index future from Upstox; Σ CE/PE OI, live Σ CE/PE volume, PCR, and session ΔOI from the same
            option-chain snapshot as the rest of this page. Entry/exit levels are rule-based anchors from the last bar and
            swing/pivot context — not guaranteed fills.
          </p>
        </div>
      </header>
      <FutureCandleChart fc={fc} />
      <div className="fut-chart-widget__details">
        <OiFutureTradePlanBody fc={fc} />
      </div>
    </article>
  );
}

/** Widget B: identical synthesis text only (for a second screen or glance view). */
export function OiFutureTradePlanOnly({ fc }) {
  return (
    <article className="fut-chart-widget fut-chart-widget--textonly">
      <header className="fut-chart-widget__head">
        <div>
          <h3 className="fut-chart-widget__title">Entry / exit read — same details (no chart)</h3>
          <p className="muted small fut-chart-widget__sub">Mirrors the panel above; updates on the same poll.</p>
        </div>
      </header>
      <OiFutureTradePlanBody fc={fc} />
    </article>
  );
}
