"""
NIFTY intraday option-chain analyzer (Upstox) — analysis + alerts only, no orders.

Run from project root:

    python main.py
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING
import json
import logging
import time
from pathlib import Path

from analysis.signal_engine import Signal, SignalEngine, SignalKind, build_snapshot
from alerts.telegram import TelegramNotifier, format_signal_message
from config.settings import get_settings, load_analysis_parameters, project_root
from data.upstox_client import UpstoxAPIError, UpstoxClient
from utils.helpers import format_hhmm, now_ist

if TYPE_CHECKING:
    from data.models import StrikeSnapshot

LOG = logging.getLogger("nifty_options")


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


class SignalLogger:
    """Append JSON lines with timestamp + snapshot for each emitted signal."""

    def __init__(self, log_dir: Path) -> None:
        self._dir = log_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def log(self, signal: Signal, snapshot: dict) -> None:
        day = now_ist().strftime("%Y-%m-%d")
        path = self._dir / f"signals_{day}.log"
        record = {
            "ts": now_ist().isoformat(),
            "signal": {"kind": signal.kind.value, "strike": signal.strike, "reason": signal.reason, "meta": signal.meta},
            "snapshot": snapshot,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


class CooldownBook:
    def __init__(self, seconds: float) -> None:
        self._seconds = seconds
        self._last: dict[str, float] = {}

    def allow(self, key: str, now: float) -> bool:
        prev = self._last.get(key)
        if prev is None or now - prev >= self._seconds:
            self._last[key] = now
            return True
        return False


def _signal_key(s: Signal) -> str:
    if s.kind == SignalKind.REVERSAL:
        return "REVERSAL"
    return f"{s.kind.value}:{s.strike}"


def print_dashboard(
    *,
    spot: float,
    vwap: float | None,
    vwap_n: int,
    expiry: str,
    history_len: int,
    last_error: str | None,
    otm_watch: str = "",
) -> None:
    vw = f"{vwap:.2f}" if vwap is not None else "-"
    err = last_error or "-"
    watch = f" | {otm_watch}" if otm_watch else ""
    print(
        f"\r[{format_hhmm()}] spot={spot:.2f} vwap={vw} (n={vwap_n}) "
        f"expiry={expiry} hist={history_len} | last_err={err}{watch}",
        end="",
        flush=True,
    )


def run_loop(dry_run: bool = False) -> int:
    settings = get_settings()
    params = load_analysis_parameters(settings)
    setup_logging(project_root() / settings.log_dir)

    client = UpstoxClient(settings, params)
    engine = SignalEngine(params)
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    sig_log = SignalLogger(project_root() / settings.log_dir)
    cooldown = CooldownBook(params.signal_cooldown_seconds)

    expiry = client.resolve_expiry(settings.option_expiry_date)
    LOG.info("Using expiry %s", expiry)

    last_err: str | None = None
    vwap_cache: tuple[float | None, int, float] = (None, 0, 0.0)  # value, n, monotonic_ts

    try:
        while True:
            loop_started = time.monotonic()
            spot = 0.0
            try:
                rows = client.fetch_option_chain(expiry)
                snap = build_snapshot(rows, now_ist(), expiry)
                spot = snap.spot

                # Refresh VWAP periodically (expensive); every ~60s
                now_m = time.monotonic()
                vwap_val, vwap_n = vwap_cache[0], vwap_cache[1]
                if vwap_val is None or now_m - vwap_cache[2] > 60.0:
                    vwap_val, vwap_n = client.fetch_vwap_approx()
                    vwap_cache = (vwap_val, vwap_n, now_m)

                engine.push(snap)
                signals = engine.evaluate(vwap_val)

                print_dashboard(
                    spot=spot,
                    vwap=vwap_val,
                    vwap_n=vwap_n,
                    expiry=expiry,
                    history_len=engine.history_len,
                    last_error=None,
                    otm_watch=engine.last_otm_watch_line,
                )
                last_err = None

                now_ts = time.time()
                for s in signals:
                    key = _signal_key(s)
                    if not cooldown.allow(key, now_ts):
                        continue

                    snap_payload = {
                        "spot": spot,
                        "vwap": vwap_val,
                        "expiry": expiry,
                        "strikes_sample": _sample_strikes(snap, limit=6),
                    }

                    mv_obj = s.meta.get("market_move")
                    mv_label = mv_obj.get("label") if isinstance(mv_obj, dict) else None
                    msg = format_signal_message(
                        action=s.kind.value,
                        buy_strike=s.strike,
                        reason=s.reason,
                        time_hhmm=format_hhmm(),
                        buy_leg=s.meta.get("buy_leg"),
                        buy_ltp=s.meta.get("buy_ltp"),
                        pattern_strike=s.meta.get("pattern_strike"),
                        pattern_side=s.meta.get("pattern_side"),
                        market_move_label=mv_label,
                        execution_note=s.meta.get("execution_note"),
                    )
                    LOG.info("SIGNAL %s", msg.replace("\n", " | "))
                    sig_log.log(s, snap_payload)

                    if not dry_run and notifier.enabled:
                        notifier.send(msg)
                    elif not notifier.enabled:
                        LOG.warning("Telegram not configured — printed only:\n%s", msg)

            except UpstoxAPIError as e:
                last_err = str(e)
                LOG.error("Upstox API error: %s", e)
                print_dashboard(
                    spot=spot,
                    vwap=vwap_cache[0],
                    vwap_n=vwap_cache[1],
                    expiry=expiry,
                    history_len=engine.history_len,
                    last_error=last_err,
                    otm_watch=engine.last_otm_watch_line,
                )
            except Exception as e:
                last_err = repr(e)
                LOG.exception("Loop error: %s", e)

            elapsed = time.monotonic() - loop_started
            sleep_for = max(0.1, params.poll_interval_seconds - elapsed)
            time.sleep(sleep_for)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    finally:
        client.close()
        notifier.close()


def _sample_strikes(snap: StrikeSnapshot, limit: int) -> list[dict]:
    out: list[dict] = []
    for i, (k, row) in enumerate(sorted(snap.strikes.items())):
        if i >= limit:
            break
        out.append(
            {
                "strike": k,
                "call_ltp": row.call.ltp,
                "call_vol": row.call.volume,
                "call_oi": row.call.oi,
                "put_ltp": row.put.ltp,
                "put_vol": row.put.volume,
                "put_oi": row.put.oi,
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="NIFTY intraday option analysis (Upstox + Telegram)")
    p.add_argument("--dry-run", action="store_true", help="Do not send Telegram messages")
    args = p.parse_args(argv)
    return run_loop(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
