"""Telegram notifications via Bot API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str | None, chat_id: str | None) -> None:
        self._token = bot_token
        self._chat = chat_id
        self._client = httpx.Client(timeout=20.0)

    def close(self) -> None:
        self._client.close()

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat)

    def send(self, text: str) -> bool:
        if not self.enabled:
            logger.debug("Telegram disabled — skipping send")
            return False
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": self._chat,
            "text": text,
            "disable_web_page_preview": True,
        }
        try:
            r = self._client.post(url, json=payload)
            r.raise_for_status()
            body = r.json()
            if not body.get("ok"):
                logger.error("Telegram API error: %s", body)
                return False
            return True
        except Exception as e:
            logger.exception("Telegram send failed: %s", e)
            return False


def format_signal_message(
    action: str,
    buy_strike: float | None,
    reason: str,
    time_hhmm: str,
    *,
    buy_leg: str | None = None,
    buy_ltp: float | None = None,
    pattern_strike: float | None = None,
    pattern_side: str | None = None,
    market_move_label: str | None = None,
    execution_note: str | None = None,
) -> str:
    if buy_strike is None and pattern_strike is None:
        return "\n".join(
            ["NIFTY SIGNAL", f"Action: {action}", f"Reason: {reason}", f"Time: {time_hhmm}"]
        )
    lines = ["NIFTY SIGNAL", f"Action: {action}"]
    if buy_strike is not None and buy_leg:
        ltp = f" @ LTP {buy_ltp:.2f}" if buy_ltp and buy_ltp > 0 else ""
        lines.append(f"Buy: {int(buy_strike)} {buy_leg}{ltp}")
    elif buy_strike is not None:
        lines.append(f"Buy strike: {int(buy_strike)}")
    else:
        lines.append("Buy strike: -")
    if pattern_strike is not None and pattern_side:
        lines.append(f"Pattern ({pattern_side} leg): {int(pattern_strike)}")
    if market_move_label:
        lines.append(f"Market: {market_move_label}")
    if execution_note:
        lines.append(execution_note)
    lines.append(f"Reason: {reason}")
    lines.append(f"Time: {time_hhmm}")
    return "\n".join(lines)
