function oiLakh(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return `${(Number(n) / 1e5).toFixed(2)}L`;
}

function fmtPx(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toFixed(2);
}

function SRHorizonCard({ title, horizon }) {
  if (!horizon) return null;
  const supports = horizon.supports ?? [];
  const resistances = horizon.resistances ?? [];
  const pl = horizon.pivot_levels;
  const hasPivot = pl != null && pl.pivot != null && !Number.isNaN(Number(pl.pivot));

  return (
    <article className="sr-card">
      <div className="sr-card__head">
        <h3 className="sr-card__title">{title}</h3>
        <span className="sr-card__expiry muted small">{horizon.expiry_display || horizon.expiry_iso || "—"}</span>
      </div>
      {horizon.chain_caption ? <p className="sr-card__caption muted small">{horizon.chain_caption}</p> : null}
      <p className="sr-card__spot">
        Spot <span className="mono">{Number(horizon.spot || 0).toFixed(2)}</span>
      </p>

      {hasPivot ? (
        <div className="sr-pivot">
          <h4 className="sr-pivot__title">Pivot (live daily OHLC)</h4>
          {pl.basis_label ? <p className="sr-pivot__basis muted small">{pl.basis_label}</p> : null}
          <div className="sr-pivot__levels">
            <div className="sr-pivot__cell">
              <span className="sr-pivot__k">S2</span>
              <span className="sr-pivot__v mono">{fmtPx(pl.s2)}</span>
            </div>
            <div className="sr-pivot__cell">
              <span className="sr-pivot__k">S1</span>
              <span className="sr-pivot__v mono">{fmtPx(pl.s1)}</span>
            </div>
            <div className="sr-pivot__cell sr-pivot__cell--pp">
              <span className="sr-pivot__k">PP</span>
              <span className="sr-pivot__v mono">{fmtPx(pl.pivot)}</span>
            </div>
            <div className="sr-pivot__cell">
              <span className="sr-pivot__k">R1</span>
              <span className="sr-pivot__v mono">{fmtPx(pl.r1)}</span>
            </div>
            <div className="sr-pivot__cell">
              <span className="sr-pivot__k">R2</span>
              <span className="sr-pivot__v mono">{fmtPx(pl.r2)}</span>
            </div>
          </div>
          <p className="sr-pivot__hlc muted small">
            Basis H {fmtPx(pl.basis_high)} · L {fmtPx(pl.basis_low)} · C {fmtPx(pl.basis_close)}
          </p>
        </div>
      ) : pl?.unavailable_reason ? (
        <p className="sr-pivot__warn muted small">{pl.unavailable_reason}</p>
      ) : null}

      <h4 className="sr-oi__title">OI walls (live chain)</h4>
      <div className="sr-card__cols">
        <div className="sr-col sr-col--sup">
          <h4 className="sr-col__label">Support</h4>
          <p className="sr-col__hint muted small">PE OI wall below spot</p>
          <ul className="sr-col__list">
            {supports.length === 0 ? (
              <li className="muted small">—</li>
            ) : (
              supports.map((s) => (
                <li key={`s-${s.strike}`}>
                  <span className="sr-strike mono">{s.strike}</span>
                  <span className="sr-oi">PE {oiLakh(s.pe_oi)}</span>
                </li>
              ))
            )}
          </ul>
        </div>
        <div className="sr-col sr-col--res">
          <h4 className="sr-col__label">Resistance</h4>
          <p className="sr-col__hint muted small">CE OI wall above spot</p>
          <ul className="sr-col__list">
            {resistances.length === 0 ? (
              <li className="muted small">—</li>
            ) : (
              resistances.map((s) => (
                <li key={`r-${s.strike}`}>
                  <span className="sr-strike mono">{s.strike}</span>
                  <span className="sr-oi">CE {oiLakh(s.ce_oi)}</span>
                </li>
              ))
            )}
          </ul>
        </div>
      </div>
      {horizon.note ? <p className="sr-card__note muted small">{horizon.note}</p> : null}
    </article>
  );
}

export default function SRLevelsPanel({ bundle }) {
  if (!bundle) {
    return (
      <p className="muted small sr-panel__empty">Levels appear after a successful option-chain sync (same refresh as OI above).</p>
    );
  }

  return (
    <div className="sr-grid">
      <SRHorizonCard title="Intraday" horizon={bundle.intraday} />
      <SRHorizonCard title="Weekly" horizon={bundle.weekly} />
      <SRHorizonCard title="Monthly" horizon={bundle.monthly} />
    </div>
  );
}
