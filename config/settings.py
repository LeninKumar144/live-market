"""Application settings from environment variables and `config/analysis.yaml` tuning."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True, slots=True)
class AnalysisParameters:
    """Tunable analysis thresholds (from YAML, with optional env overrides)."""

    poll_interval_seconds: float
    signal_cooldown_seconds: float
    strike_radius: int
    min_open_interest: int
    min_volume: int
    volume_spike_multiplier: float
    min_volume_delta: int
    strike_step: int
    buy_strike_max_steps_from_atm: int
    buy_strike_mode: str
    otm_strike_steps: int
    market_move_lookback_snapshots: int
    market_move_flat_threshold_points: float
    reversal_oi_strikes_radius: int
    http_timeout_seconds: float
    max_http_retries: int
    retry_backoff_base_seconds: float
    stock_option_min_open_interest: int
    stock_option_min_volume: int
    stock_option_buy_strike_max_steps_from_atm: int
    stock_market_move_flat_threshold_points: float


_ENV_FILE = project_root() / ".env"


class Settings(BaseSettings):
    """Secrets and paths from `.env` next to project root (not dependent on CWD)."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    upstox_access_token: str = Field(..., alias="UPSTOX_ACCESS_TOKEN", min_length=1)
    upstox_api_base: str = Field("https://api.upstox.com/v2", alias="UPSTOX_API_BASE")

    upstox_client_id: str | None = Field(None, alias="UPSTOX_CLIENT_ID")
    upstox_client_secret: str | None = Field(None, alias="UPSTOX_CLIENT_SECRET")
    upstox_redirect_uri: str | None = Field(None, alias="UPSTOX_REDIRECT_URI")

    nifty_instrument_key: str = Field("NSE_INDEX|Nifty 50", alias="NIFTY_INSTRUMENT_KEY")
    option_expiry_date: str | None = Field(None, alias="OPTION_EXPIRY_DATE")

    telegram_bot_token: str | None = Field(None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str | None = Field(None, alias="TELEGRAM_CHAT_ID")

    log_dir: str = Field("logs", alias="LOG_DIR")
    analysis_config_path: str = Field("config/analysis.yaml", alias="ANALYSIS_CONFIG_PATH")

    # Env can override YAML for these two without editing the file
    poll_interval_seconds: float | None = Field(None, alias="POLL_INTERVAL_SECONDS")
    signal_cooldown_seconds: float | None = Field(None, alias="SIGNAL_COOLDOWN_SECONDS")

    @field_validator("upstox_access_token", mode="before")
    @classmethod
    def _normalize_access_token(cls, v: object) -> str:
        """Strip whitespace, BOM, and wrapping quotes so HTTP headers stay valid."""
        if v is None:
            return ""
        s = str(v).strip()
        if s.startswith("\ufeff"):
            s = s.lstrip("\ufeff")
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            s = s[1:-1].strip()
        return s


def load_analysis_parameters(settings: Settings) -> AnalysisParameters:
    path = project_root() / settings.analysis_config_path
    y = _load_yaml(path)

    def num(key: str, default: float | int) -> float | int:
        v = y.get(key, default)
        return default if v is None else v

    def txt(key: str, default: str) -> str:
        v = y.get(key, default)
        if v is None:
            return default
        return str(v).strip().lower()

    poll = float(settings.poll_interval_seconds) if settings.poll_interval_seconds is not None else float(num("poll_interval_seconds", 7))
    cool = (
        float(settings.signal_cooldown_seconds)
        if settings.signal_cooldown_seconds is not None
        else float(num("signal_cooldown_seconds", 180))
    )

    return AnalysisParameters(
        poll_interval_seconds=poll,
        signal_cooldown_seconds=cool,
        strike_radius=int(num("strike_radius", 8)),
        min_open_interest=int(num("min_open_interest", 3000)),
        min_volume=int(num("min_volume", 500)),
        volume_spike_multiplier=float(num("volume_spike_multiplier", 1.35)),
        min_volume_delta=int(num("min_volume_delta", 10)),
        strike_step=int(num("strike_step", 50)),
        buy_strike_max_steps_from_atm=int(num("buy_strike_max_steps_from_atm", 4)),
        buy_strike_mode=txt("buy_strike_mode", "otm"),
        otm_strike_steps=int(num("otm_strike_steps", 1)),
        market_move_lookback_snapshots=int(num("market_move_lookback_snapshots", 10)),
        market_move_flat_threshold_points=float(num("market_move_flat_threshold_points", 3.0)),
        reversal_oi_strikes_radius=int(num("reversal_oi_strikes_radius", 2)),
        http_timeout_seconds=float(num("http_timeout_seconds", 25)),
        max_http_retries=int(num("max_http_retries", 4)),
        retry_backoff_base_seconds=float(num("retry_backoff_base_seconds", 1.5)),
        stock_option_min_open_interest=int(num("stock_option_min_open_interest", 500)),
        stock_option_min_volume=int(num("stock_option_min_volume", 50)),
        stock_option_buy_strike_max_steps_from_atm=int(num("stock_option_buy_strike_max_steps_from_atm", 8)),
        stock_market_move_flat_threshold_points=float(num("stock_market_move_flat_threshold_points", 5.0)),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
