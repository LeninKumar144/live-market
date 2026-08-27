/**
 * Three-phase open bias: pre-open / 0–15m / post-09:30.
 * Data from /oi/status → opening_session.
 */
function fmtPts(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  return `${n >= 0 ? "+" : ""}${n.toFixed(1)}`;
}

function fmtNum(v, digits = 2) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toFixed(digits);
}

function biasClass(key) {
  const k = String(key || "");
  if (k.includes("up") || k === "gap_up_bias" || k === "bounce_watch") return "osess-pill osess-pill--up";
  if (k.includes("down") || k === "gap_down_bias" || k === "fade_watch") return "osess-pill osess-pill--dn";
  if (k.includes("range") || k === "wait_or") return "osess-pill osess-pill--range";
  return "osess-pill osess-pill--mixed";
}

function phaseActive(phase, card) {
  if (card === "pre") return phase === "pre_open";
  if (card === "form") return phase === "forming_or";
  if (card === "post") return phase === "post_or" || phase === "after_hours";
  return false;
}

function OrBlock({ title, orBlock, vsOr }) {
  if (!orBlock) return null;
  const ready = Boolean(orBlock.ready);
  return (
    <div className="osess-or">
      <h5 className="osess-or__title">{title}</h5>
      {!ready ? (
        <p className="muted small">Awaiting 1m bars…</p>
      ) : (
        <ul className="osess-stats">
          <li>
            <span>High / Low</span>
            <strong>
              {fmtNum(orBlock.high, 0)} / {fmtNum(orBlock.low, 0)}
            </strong>
          </li>
          <li>
            <span>Range</span>
            <strong>{fmtNum(orBlock.range_points, 1)} pts</strong>
          </li>
          <li>
            <span>Vs price</span>
            <strong>{vsOr?.label || "—"}</strong>
          </li>
          {orBlock.close_position && orBlock.close_position !== "unknown" && (
            <li>
              <span>Close pos</span>
              <strong>{String(orBlock.close_position).replace(/_/g, " ")}</strong>
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

export default function OpeningSessionCards({ session, showGift = true }) {
  if (!session) return null;
  const phase = session.phase || "";
  const gap = session.gap || {};
  const walls = session.overnight_walls || {};
  const vix = session.india_vix;
  const doi = session.session_doi_vs_915 || {};
  const ft = session.future_trend || {};
  const gift = session.gift_nifty || {};

  return (
    <section className="osess" aria-label="Opening session trend cards">
      <div className="osess__head">
        <div>
          <h3 className="osess__title">Opening session bias</h3>
          <p className="muted small osess__sub">
            Three clocks: overnight map at the bell → provisional 0–15m → confirmed after 09:30 (OR + ΔOI vs
            09:15). Heuristic only.
          </p>
        </div>
        <span className={biasClass(session.bias_key)} title={session.phase_label}>
          {session.headline || session.phase_label || "—"}
        </span>
      </div>
      {session.disclaimer && <p className="muted small osess__disclaimer">{session.disclaimer}</p>}

      <div className="osess-grid">
        {/* Card 1 — Pre-open */}
        <article className={`osess-card${phaseActive(phase, "pre") ? " osess-card--active" : ""}`}>
          <header className="osess-card__head">
            <span className="osess-card__phase">1 · Pre-open / 9:15</span>
            {phaseActive(phase, "pre") && <span className="osess-card__live">Live phase</span>}
          </header>
          <p className="osess-card__blurb">Overnight OI map + gap — not today’s session trend.</p>
          <ul className="osess-stats">
            <li>
              <span>Gap</span>
              <strong className={gap.direction === "gap_up" ? "up" : gap.direction === "gap_down" ? "dn" : ""}>
                {gap.label || "—"}
              </strong>
            </li>
            <li>
              <span>Open / Prev close</span>
              <strong>
                {fmtNum(gap.open)} / {fmtNum(gap.prev_close)}
              </strong>
            </li>
            <li>
              <span>Vs OI walls</span>
              <strong>{walls.label || "—"}</strong>
            </li>
            <li>
              <span>PE / CE wall</span>
              <strong>
                {walls.support_strike ?? "—"} / {walls.resistance_strike ?? "—"}
              </strong>
            </li>
            <li>
              <span>Overnight PCR</span>
              <strong>{walls.pcr != null ? Number(walls.pcr).toFixed(2) : "—"}</strong>
            </li>
            <li>
              <span>India VIX</span>
              <strong>
                {vix?.ltp != null ? (
                  <>
                    {fmtNum(vix.ltp)}
                    {vix.net_change != null && (
                      <span className={Number(vix.net_change) >= 0 ? "up" : "dn"}> {fmtPts(vix.net_change)}</span>
                    )}
                  </>
                ) : (
                  "—"
                )}
              </strong>
            </li>
            <li>
              <span>GIFT Nifty</span>
              <strong className="muted">
                {!showGift
                  ? "—"
                  : gift.available
                    ? "—"
                    : gift.note || "Not wired"}
              </strong>
            </li>
          </ul>
        </article>

        {/* Card 2 — Forming OR */}
        <article className={`osess-card${phaseActive(phase, "form") ? " osess-card--active" : ""}`}>
          <header className="osess-card__head">
            <span className="osess-card__phase">2 · 0–15 min</span>
            {phaseActive(phase, "form") && <span className="osess-card__live">Provisional</span>}
          </header>
          <p className="osess-card__blurb">Live vs 09:15 future + forming opening range.</p>
          <ul className="osess-stats">
            <li>
              <span>Future trend</span>
              <strong>
                {ft.trend_label || "Needs ticks in 09:15–09:30"}
                {ft.is_provisional ? " · provisional" : ""}
              </strong>
            </li>
            <li>
              <span>ΔOI vs 09:15</span>
              <strong>{doi.available ? doi.label : doi.label || "Awaiting 09:15 chain anchor"}</strong>
            </li>
            {doi.available && (
              <li>
                <span>CE / PE ΔOI</span>
                <strong>
                  {doi.ce_doi != null ? `${doi.ce_doi >= 0 ? "+" : ""}${Number(doi.ce_doi).toLocaleString("en-IN")}` : "—"}
                  {" / "}
                  {doi.pe_doi != null ? `${doi.pe_doi >= 0 ? "+" : ""}${Number(doi.pe_doi).toLocaleString("en-IN")}` : "—"}
                </strong>
              </li>
            )}
          </ul>
          <OrBlock title="5m OR" orBlock={session.opening_range_5m} vsOr={session.price_vs_or_5m} />
          <OrBlock title="15m OR (forming)" orBlock={session.opening_range_15m} vsOr={session.price_vs_or_15m} />
        </article>

        {/* Card 3 — Post 9:30 */}
        <article className={`osess-card${phaseActive(phase, "post") ? " osess-card--active" : ""}`}>
          <header className="osess-card__head">
            <span className="osess-card__phase">3 · After 09:30</span>
            {phaseActive(phase, "post") && <span className="osess-card__live">Confirmed</span>}
          </header>
          <p className="osess-card__blurb">OR acceptance + session ΔOI vs 09:15 + future 2×2.</p>
          <ul className="osess-stats">
            <li>
              <span>09:15–09:30 future</span>
              <strong>{ft.ready ? ft.trend_label || "—" : "Not locked until 09:30 anchor"}</strong>
            </li>
            <li>
              <span>Session ΔOI</span>
              <strong>{doi.available ? doi.label : "Needs 09:15 chain snapshot (keep API running)"}</strong>
            </li>
            <li>
              <span>Price vs 15m OR</span>
              <strong>{session.price_vs_or_15m?.label || "—"}</strong>
            </li>
          </ul>
          <OrBlock title="15m opening range" orBlock={session.opening_range_15m} vsOr={session.price_vs_or_15m} />
        </article>
      </div>

      {Array.isArray(session.detail_lines) && session.detail_lines.length > 0 && (
        <ul className="osess-narrative">
          {session.detail_lines.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
