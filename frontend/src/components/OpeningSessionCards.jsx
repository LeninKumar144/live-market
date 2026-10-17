/**
 * Three-phase open bias: pre-open / 0–15m / post-09:30.
 * Each card keeps phase-unique fields; OR / future trend / ΔOI are not repeated across cards.
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
  const forming = phase === "forming_or";
  const post = phase === "post_or" || phase === "after_hours";

  return (
    <section className="osess" aria-label="Opening session trend cards">
      <div className="osess__head">
        <div>
          <h3 className="osess__title">Opening session bias</h3>
          <p className="muted small osess__sub">
            Unique open clocks only: overnight map → forming OR → confirmed post-09:30. Gap / VIX live here (not in
            header pills).
          </p>
        </div>
        <span className={biasClass(session.bias_key)} title={session.phase_label}>
          {session.headline || session.phase_label || "—"}
        </span>
      </div>
      {session.disclaimer && <p className="muted small osess__disclaimer">{session.disclaimer}</p>}

      <div className="openwin-legend muted small osess-legend" aria-label="OI vs price future mapping">
        <span>
          <strong>OI↑</strong> price↑ → Long buildup
        </span>
        <span>
          <strong>OI↑</strong> price↓ → Short buildup
        </span>
        <span>
          <strong>OI↓</strong> price↓ → Profit booking
        </span>
        <span>
          <strong>OI↓</strong> price↑ → Short covering
        </span>
      </div>

      <div className="osess-grid">
        <article className={`osess-card${phaseActive(phase, "pre") ? " osess-card--active" : ""}`}>
          <header className="osess-card__head">
            <span className="osess-card__phase">1 · Pre-open / 9:15</span>
            {phaseActive(phase, "pre") && <span className="osess-card__live">Live phase</span>}
          </header>
          <p className="osess-card__blurb">Overnight map + gap (not session ΔOI).</p>
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
            {showGift ? (
              <li>
                <span>GIFT Nifty</span>
                <strong className="muted">{gift.available ? "—" : gift.note || "Not wired"}</strong>
              </li>
            ) : null}
          </ul>
        </article>

        <article className={`osess-card${phaseActive(phase, "form") ? " osess-card--active" : ""}`}>
          <header className="osess-card__head">
            <span className="osess-card__phase">2 · 0–15 min</span>
            {phaseActive(phase, "form") && <span className="osess-card__live">Provisional</span>}
          </header>
          <p className="osess-card__blurb">Forming window only — OR + live vs 09:15.</p>
          {forming ? (
            <>
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
                  <strong>{doi.label || "Awaiting 09:15 chain anchor"}</strong>
                </li>
                {doi.available && (
                  <li>
                    <span>CE / PE ΔOI</span>
                    <strong>
                      {doi.ce_doi != null
                        ? `${doi.ce_doi >= 0 ? "+" : ""}${Number(doi.ce_doi).toLocaleString("en-IN")}`
                        : "—"}
                      {" / "}
                      {doi.pe_doi != null
                        ? `${doi.pe_doi >= 0 ? "+" : ""}${Number(doi.pe_doi).toLocaleString("en-IN")}`
                        : "—"}
                    </strong>
                  </li>
                )}
              </ul>
              <OrBlock title="5m OR" orBlock={session.opening_range_5m} vsOr={session.price_vs_or_5m} />
              <OrBlock title="15m OR (forming)" orBlock={session.opening_range_15m} vsOr={session.price_vs_or_15m} />
            </>
          ) : (
            <p className="muted small">
              {phase === "pre_open"
                ? "Activates at 09:15 when the opening range starts forming."
                : "Window closed — see card 3 for the confirmed 09:15–09:30 read."}
            </p>
          )}
        </article>

        <article className={`osess-card${phaseActive(phase, "post") ? " osess-card--active" : ""}`}>
          <header className="osess-card__head">
            <span className="osess-card__phase">3 · After 09:30</span>
            {phaseActive(phase, "post") && <span className="osess-card__live">Confirmed</span>}
          </header>
          <p className="osess-card__blurb">Locked OR + future 2×2 after 09:30.</p>
          {post ? (
            <>
              <ul className="osess-stats">
                <li>
                  <span>09:15–09:30 future</span>
                  <strong>{ft.ready ? ft.trend_label || "—" : "Not locked until 09:30 anchor"}</strong>
                </li>
                <li>
                  <span>Session ΔOI vs 09:15</span>
                  <strong>{doi.available ? doi.label : "Needs 09:15 chain snapshot (keep API running)"}</strong>
                </li>
              </ul>
              <OrBlock title="15m opening range" orBlock={session.opening_range_15m} vsOr={session.price_vs_or_15m} />
            </>
          ) : (
            <p className="muted small">Confirms after 09:30 when the late future anchor is captured.</p>
          )}
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
