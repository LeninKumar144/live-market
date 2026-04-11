#!/usr/bin/env python3
"""
Print NIFTY spot + NIFTY index future quote snapshot (LTP / OHLC / net change)
and option-chain OI: totals plus strike-wise CE vs PE (for chosen expiry).

Usage (from project root):
  python scripts/nifty_close_oi_report.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config.settings import get_settings, load_analysis_parameters
from data.upstox_client import UpstoxAPIError, UpstoxClient


def _quote_key_map(data: dict) -> dict[str, dict]:
    """Map canonical `SEG|Token` -> quote row (Upstox uses `SEG:Token` in response keys)."""
    out: dict[str, dict] = {}
    for k, v in data.items():
        if not isinstance(v, dict):
            continue
        canon = k.replace(":", "|", 1)
        out[canon] = v
        out[k] = v
        tok = v.get("instrument_token")
        if isinstance(tok, str) and tok:
            out[tok] = v
    return out


def _print_instrument(title: str, key: str, q: dict | None) -> None:
    print(f"\n=== {title} ({key}) ===")
    if not q:
        print("  (no quote returned)")
        return
    o = q.get("ohlc") or {}
    print(f"  last_price: {q.get('last_price')}")
    print(
        f"  ohlc: open={o.get('open')} high={o.get('high')} low={o.get('low')} close={o.get('close')}"
    )
    print(
        "  (Upstox: `close` in ohlc is session reference close; `net_change` vs prev close.)"
    )
    print(f"  net_change: {q.get('net_change')}")
    print(f"  volume: {q.get('volume')}  oi: {q.get('oi')}")
    print(f"  symbol: {q.get('symbol')}")


def main() -> int:
    settings = get_settings()
    params = load_analysis_parameters(settings)
    client = UpstoxClient(settings, params)
    idx_key = settings.nifty_instrument_key

    try:
        fut_key, fut_sym = client.find_nifty_index_future("current_month")
    except UpstoxAPIError:
        fut_key, fut_sym = client.find_nifty_index_future("near_month")

    expiry = client.resolve_expiry(settings.option_expiry_date)
    rows = client.fetch_option_chain(expiry)

    quotes_raw = client.fetch_market_quotes([idx_key, fut_key])
    qmap = _quote_key_map(quotes_raw)
    if not qmap.get(fut_key):
        qmap.update(_quote_key_map(client.fetch_market_quotes([fut_key])))

    spot_from_chain = rows[0].underlying_spot_price if rows else 0.0

    print("NIFTY - closing / snapshot status (live API; not official exchange EOD file)")
    print(f"Option chain expiry used: {expiry}")
    print(f"Underlying spot from chain: {spot_from_chain:.2f}")
    _print_instrument("NIFTY 50 INDEX", idx_key, qmap.get(idx_key))
    _print_instrument(f"NIFTY FUTURE ({fut_sym})", fut_key, qmap.get(fut_key))

    total_ce_oi = sum(r.call.oi for r in rows)
    total_pe_oi = sum(r.put.oi for r in rows)
    total_ce_vol = sum(r.call.volume for r in rows)
    total_pe_vol = sum(r.put.volume for r in rows)
    pcr = (total_pe_oi / total_ce_oi) if total_ce_oi else 0.0

    print("\n=== OPTION OI SUMMARY (all strikes in chain) ===")
    print(f"  Total Call OI: {total_ce_oi:,}")
    print(f"  Total Put  OI: {total_pe_oi:,}")
    print(f"  Put/Call OI ratio: {pcr:.4f}")
    print(f"  Total Call volume: {total_ce_vol:,}")
    print(f"  Total Put  volume: {total_pe_vol:,}")

    print("\n=== STRIKE-WISE OI (Call vs Put) ===")
    print(f"{'Strike':>10}  {'CE_OI':>12}  {'PE_OI':>12}  {'CE_dOI':>12}  {'PE_dOI':>12}")
    print("  dOI = oi - prev_oi from chain (exchange prior snapshot)")
    for r in rows:
        dce = r.call.oi - r.call.prev_oi
        dpe = r.put.oi - r.put.prev_oi
        print(
            f"{int(r.strike_price):>10}  {r.call.oi:>12,}  {r.put.oi:>12,}  {dce:>12,}  {dpe:>12,}"
        )

    client.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except UpstoxAPIError as e:
        print(f"API error: {e}", file=sys.stderr)
        raise SystemExit(1)
