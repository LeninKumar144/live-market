"""One-off: poll chain 4x (matches signal warmup), print spot/VWAP/OTM CE and any BUY CE signal."""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Project root on path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.signal_engine import SignalEngine, SignalKind, build_snapshot
from config.settings import get_settings, load_analysis_parameters
from data.upstox_client import UpstoxClient
from utils.helpers import atm_strike, format_hhmm, now_ist, resolve_execution_strike


def main() -> int:
    settings = get_settings()
    params = load_analysis_parameters(settings)
    client = UpstoxClient(settings, params)
    engine = SignalEngine(params)
    expiry = client.resolve_expiry(settings.option_expiry_date)
    interval = max(2.0, min(float(params.poll_interval_seconds), 8.0))

    vwap_val, vwap_n = client.fetch_vwap_approx()
    print(f"Expiry: {expiry} | Poll interval for warmup: {interval}s\n")

    for i in range(4):
        rows = client.fetch_option_chain(expiry)
        snap = build_snapshot(rows, now_ist(), expiry)
        engine.push(snap)
        spot = snap.spot
        atm = atm_strike(spot, params.strike_step)
        ce_k, ce_ltp = resolve_execution_strike(
            snap.strikes,
            spot,
            params.strike_step,
            "CE",
            params.min_open_interest,
            params.min_volume,
            params.buy_strike_max_steps_from_atm,
            placement="otm",
            otm_steps=params.otm_strike_steps,
        )
        print(
            f"  [{i + 1}/4] {format_hhmm()} spot={spot:.2f} ATM={int(atm)} "
            f"suggested_OTM_CE={int(ce_k)} LTP={ce_ltp:.2f}"
        )
        if i < 3:
            time.sleep(interval)

    engine._refresh_market_context(vwap_val)
    signals = engine.evaluate(vwap_val)
    client.close()

    print()
    vw = f"{vwap_val:.2f}" if vwap_val else "-"
    print(f"VWAP (approx): {vw} (candles={vwap_n})")
    print(f"Market move (lookback): {engine.last_market_move.get('label', 'n/a')}")
    print(f"Watch: {engine.last_otm_watch_line or '-'}")
    print()

    buy_ce = [s for s in signals if s.kind == SignalKind.BUY_CE]
    if buy_ce:
        s = buy_ce[0]
        print("BUY CE signal NOW (rules fired):")
        print(f"  Buy strike: {int(s.strike)} CE @ LTP {s.meta.get('buy_ltp', 0):.2f}")
        print(f"  Pattern put strike: {s.meta.get('pattern_strike')}")
        print(f"  Reason: {s.reason}")
    else:
        print("No BUY CE *signal* right now (put-writing rules did not all confirm on this window).")
        print(f"Reference OTM CE level from last poll: ~{int(ce_k)} @ LTP {ce_ltp:.2f}")
        if vwap_val and spot <= vwap_val:
            print("Note: spot is at/below VWAP — the engine would block BUY CE when VWAP is available.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
