import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import "./StockOptionsLiquidity.css";

const TIERS = [
  { key: "all", label: "All" },
  { key: "1", label: "Tier 1" },
  { key: "2", label: "Tier 2" },
  { key: "3", label: "Tier 3" },
];

/** Live option chains + OI; aligned with server cache TTL (~55s). */
const LIVE_POLL_MS = 60_000;
const LIVE_REQUEST_TIMEOUT_MS = 120_000;

function tierPillClass(tier) {
  if (tier === 1) return "sol-tier sol-tier--1";
  if (tier === 2) return "sol-tier sol-tier--2";
  return "sol-tier sol-tier--3";
}

function fmtOi(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return Number(n).toLocaleString();
}

function fmtDelta(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const v = Number(n);
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toLocaleString()}`;
}

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "—";
  }
}

const inrFmt = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

function fmtInr(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return inrFmt.format(Number(n));
}

function marginCaption(source) {
  if (source === "upstox") return "Upstox margin API";
  if (source === "premium_estimate") return "≈ LTP × lot (estimate)";
  return "";
}

function StockLivePanel({ lv }) {
  if (!lv) {
    return (
      <div className="sol-live sol-live--pending">
        <p className="muted small">Waiting for live data…</p>
      </div>
    );
  }

  if (!lv.ok) {
    return (
      <div className="sol-live sol-live--err">
        <p className="sol-live__err">{lv.error || "Chain unavailable"}</p>
      </div>
    );
  }

  const t = lv.totals || {};
  const ce = lv.buy_ce;
  const pe = lv.buy_pe;
  const mv = lv.market_move || {};
  const lot = lv.option_lot_size;
  const anyMarginEst =
    ce?.margin_source === "premium_estimate" || pe?.margin_source === "premium_estimate";

  return (
    <div className="sol-live">
      <div className="sol-live__meta">
        <span className="sol-live__pill">Spot {Number(lv.spot).toFixed(2)}</span>
        <span className="sol-live__pill">Exp {lv.expiry || "—"}</span>
        <span className="sol-live__pill">Grid {lv.strike_step}</span>
        {lot != null && lot > 0 ? (
          <span className="sol-live__pill sol-live__pill--lot" title="Shares per 1 option lot (contract)">
            Lot {lot}
          </span>
        ) : null}
        {mv.label ? (
          <span className="sol-live__pill sol-live__pill--mv" title="Spot change over recent chain polls">
            {mv.label}
          </span>
        ) : null}
      </div>

      <div className="sol-live__oi">
        <h4 className="sol-live__oi-title">Overall OI (this expiry)</h4>
        <div className="sol-live__oi-grid">
          <div>
            <span className="sol-live__k">Σ CE OI</span>
            <span className="sol-live__v">{fmtOi(t.total_call_oi)}</span>
            <span className="sol-live__d muted small">
              vs prev close Δ {fmtDelta(t.call_oi_change_vs_prev_close)}
            </span>
            <span className="sol-live__d muted small">
              vs last refresh Δ {t.call_oi_change_since_last_poll == null ? "— (first poll)" : fmtDelta(t.call_oi_change_since_last_poll)}
            </span>
          </div>
          <div>
            <span className="sol-live__k">Σ PE OI</span>
            <span className="sol-live__v">{fmtOi(t.total_put_oi)}</span>
            <span className="sol-live__d muted small">
              vs prev close Δ {fmtDelta(t.put_oi_change_vs_prev_close)}
            </span>
            <span className="sol-live__d muted small">
              vs last refresh Δ {t.put_oi_change_since_last_poll == null ? "— (first poll)" : fmtDelta(t.put_oi_change_since_last_poll)}
            </span>
          </div>
          <div>
            <span className="sol-live__k">PCR</span>
            <span className="sol-live__v">{t.pcr != null ? Number(t.pcr).toFixed(4) : "—"}</span>
          </div>
        </div>
      </div>

      <div className="sol-live__legs">
        <div className="sol-live__leg sol-live__leg--ce">
          <h4 className="sol-live__leg-title">Suggested BUY CE</h4>
          {ce ? (
            <>
              <p className="sol-live__strike">{Math.round(ce.strike)}</p>
              <ul className="sol-live__stats">
                <li>LTP {Number(ce.ltp).toFixed(2)}</li>
                <li>OI {fmtOi(ce.open_interest)}</li>
                <li>Vol {fmtOi(ce.volume)}</li>
                <li>OI Δ close {fmtDelta(ce.oi_change_vs_prev_close)}</li>
                <li>
                  OI Δ last refresh{" "}
                  {ce.oi_change_since_last_poll == null ? "—" : fmtDelta(ce.oi_change_since_last_poll)}
                </li>
                <li className="sol-live__margin-line">
                  <strong>1-lot margin (BUY)</strong> {fmtInr(ce.required_margin_inr)}
                  {ce.margin_source ? (
                    <span className="muted small"> · {marginCaption(ce.margin_source)}</span>
                  ) : null}
                </li>
              </ul>
              <p className="muted small sol-live__note">{ce.execution_note}</p>
            </>
          ) : (
            <p className="muted small">—</p>
          )}
        </div>
        <div className="sol-live__leg sol-live__leg--pe">
          <h4 className="sol-live__leg-title">Suggested BUY PE</h4>
          {pe ? (
            <>
              <p className="sol-live__strike">{Math.round(pe.strike)}</p>
              <ul className="sol-live__stats">
                <li>LTP {Number(pe.ltp).toFixed(2)}</li>
                <li>OI {fmtOi(pe.open_interest)}</li>
                <li>Vol {fmtOi(pe.volume)}</li>
                <li>OI Δ close {fmtDelta(pe.oi_change_vs_prev_close)}</li>
                <li>
                  OI Δ last refresh{" "}
                  {pe.oi_change_since_last_poll == null ? "—" : fmtDelta(pe.oi_change_since_last_poll)}
                </li>
                <li className="sol-live__margin-line">
                  <strong>1-lot margin (BUY)</strong> {fmtInr(pe.required_margin_inr)}
                  {pe.margin_source ? (
                    <span className="muted small"> · {marginCaption(pe.margin_source)}</span>
                  ) : null}
                </li>
              </ul>
              <p className="muted small sol-live__note">{pe.execution_note}</p>
            </>
          ) : (
            <p className="muted small">—</p>
          )}
        </div>
      </div>
      {anyMarginEst ? (
        <p className="muted small sol-live__margin-foot">
          Where margin shows “estimate”, SPAN was not returned — figure ≈ premium × lot; confirm in your broker terminal.
        </p>
      ) : null}
    </div>
  );
}

export default function StockOptionsLiquidity() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [tierFilter, setTierFilter] = useState("all");
  const [q, setQ] = useState("");
  const [live, setLive] = useState(null);
  const [liveErr, setLiveErr] = useState("");
  const [liveLoading, setLiveLoading] = useState(true);

  const fetchLiquidity = useCallback(async () => {
    setErr("");
    try {
      const { data: d } = await api.get("/stock-options/liquidity");
      setData(d);
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Failed to load");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchLiquidity();
  }, [fetchLiquidity]);

  const fetchLive = useCallback(async (force = false) => {
    setLiveErr("");
    try {
      const { data: d } = await api.get("/stock-options/live", {
        params: force ? { force: true } : {},
        timeout: LIVE_REQUEST_TIMEOUT_MS,
      });
      setLive(d);
    } catch (e) {
      setLiveErr(e?.response?.data?.detail || e?.message || "Live chain failed");
      setLive(null);
    } finally {
      setLiveLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const run = (force) => {
      if (cancelled) return;
      fetchLive(force);
    };
    run(false);
    const id = setInterval(() => run(false), LIVE_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [fetchLive]);

  const liveBySymbol = useMemo(() => {
    const m = {};
    for (const row of live?.stocks || []) {
      m[row.symbol] = row;
    }
    return m;
  }, [live]);

  const filtered = useMemo(() => {
    if (!data?.stocks) return [];
    let rows = data.stocks;
    if (tierFilter !== "all") {
      const t = Number(tierFilter);
      rows = rows.filter((s) => s.tier === t);
    }
    const needle = q.trim().toLowerCase();
    if (needle) {
      rows = rows.filter(
        (s) =>
          s.symbol.toLowerCase().includes(needle) ||
          (s.name && s.name.toLowerCase().includes(needle)) ||
          (s.sector && s.sector.toLowerCase().includes(needle)),
      );
    }
    return rows;
  }, [data, tierFilter, q]);

  return (
    <>
      <header className="dash-header">
        <div>
          <h1 className="title">Stock options — liquidity screen</h1>
          <p className="subtitle">
            Live CE/PE strikes &amp; OI (Upstox, ~1 min refresh) · static liquidity notes below each name
          </p>
        </div>
        <div className="header-meta">
          {loading && <span className="pill pill--load">Loading…</span>}
          {!loading && data && <span className="pill pill--ok">{data.stocks?.length ?? 0} names</span>}
          {liveLoading && <span className="pill pill--load">Live chains…</span>}
          {!liveLoading && live?.refreshed_at && (
            <span className="pill pill--ok" title="Server snapshot time (IST)">
              Live {fmtTime(live.refreshed_at)}
            </span>
          )}
          {err && <span className="pill pill--err">API error</span>}
          {liveErr && <span className="pill pill--err">Live error</span>}
        </div>
      </header>

      {err && <p className="sol-error">{err}</p>}
      {liveErr && <p className="sol-error">{liveErr}</p>}

      {data && (
        <>
          <section className="card sol-intro">
            <p className="sol-disclaimer">{data.disclaimer}</p>
            <p className="muted small sol-market">
              <strong>Market:</strong> {data.market}
            </p>
            {data.how_to_use?.length > 0 && (
              <div className="sol-how">
                <h2 className="sol-how__title">How to use this screen</h2>
                <ul className="sol-how__list">
                  {data.how_to_use.map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              </div>
            )}
            {live?.disclaimer && <p className="sol-disclaimer sol-disclaimer--live">{live.disclaimer}</p>}
          </section>

          <div className="sol-toolbar">
            <button
              type="button"
              className="sol-refresh-live"
              onClick={() => {
                setLiveLoading(true);
                fetchLive(true);
              }}
              disabled={liveLoading}
            >
              {liveLoading ? "Refreshing live…" : "Refresh live now"}
            </button>
            <div className="sol-filters" role="group" aria-label="Liquidity tier">
              {TIERS.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  className={tierFilter === t.key ? "sol-filter sol-filter--on" : "sol-filter"}
                  onClick={() => setTierFilter(t.key)}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <label className="sol-search">
              <span className="visually-hidden">Search symbol or sector</span>
              <input
                type="search"
                placeholder="Search symbol, name, sector…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                autoComplete="off"
              />
            </label>
          </div>

          <ul className="sol-grid">
            {filtered.map((s) => (
              <li key={s.symbol} className="sol-card card">
                <div className="sol-card__top">
                  <div>
                    <span className="sol-card__sym">{s.symbol}</span>
                    <h3 className="sol-card__name">{s.name}</h3>
                    <p className="muted small sol-card__sector">{s.sector}</p>
                  </div>
                  <div className="sol-card__badges">
                    <span className={tierPillClass(s.tier)} title="Heuristic liquidity tier">
                      Tier {s.tier}
                    </span>
                    <span className="sol-score" title="Heuristic score for sorting">
                      Score {s.liquidity_score}
                    </span>
                  </div>
                </div>
                <p className="sol-card__exp muted small">
                  <strong>Expiries:</strong> {s.expiries_note}
                </p>

                <StockLivePanel lv={liveBySymbol[s.symbol]} />

                {s.highlights?.length > 0 && (
                  <div className="sol-block">
                    <h4 className="sol-block__label">Why it&apos;s liquid</h4>
                    <ul className="sol-block__ul">
                      {s.highlights.map((h, i) => (
                        <li key={i}>{h}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {s.option_tips?.length > 0 && (
                  <div className="sol-block">
                    <h4 className="sol-block__label">Options trading notes</h4>
                    <ul className="sol-block__ul sol-block__ul--tips">
                      {s.option_tips.map((h, i) => (
                        <li key={i}>{h}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {s.watchouts?.length > 0 && (
                  <div className="sol-block">
                    <h4 className="sol-block__label">Watchouts</h4>
                    <ul className="sol-block__ul sol-block__ul--watch">
                      {s.watchouts.map((h, i) => (
                        <li key={i}>{h}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </li>
            ))}
          </ul>

          {!loading && filtered.length === 0 && (
            <p className="muted small sol-empty">No stocks match your filters.</p>
          )}
        </>
      )}
    </>
  );
}
