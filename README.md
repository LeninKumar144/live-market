# NIFTY intraday options analyzer (Upstox)

Production-style **analysis + alerts** loop for NIFTY: pulls live option chain data from the Upstox v2 API, applies OI / volume / price rules, applies VWAP and liquidity filters, optionally notifies **Telegram**, and appends structured logs under `logs/`.

**No trading or order placement** is implemented.

## Features

- Option chain (calls/puts per strike) with session volume and OI
- Bullish (**BUY CE**) / bearish (**BUY PE**) patterns from put/call “writing” style conditions
- **Possible reversal** when combined OI near ATM falls while spot rises
- **VWAP** from 1-minute index candles (when historical API returns data)
- **Volume spike** check vs the prior two poll intervals
- **Liquidity** thresholds via `config/analysis.yaml`
- **Retries** on transient HTTP failures (timeouts, 5xx, 429)
- **Cooldown** per signal key to reduce alert spam

## Setup

### 1. Python

Use Python 3.11+ (3.10+ should work).

```bash
cd marketanalyze
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Upstox access token

Upstox uses **OAuth 2.0**. For a personal utility, the fastest path is:

1. Create an app at [Upstox Developer](https://account.upstox.com/developer/apps).
2. Open the app → **Generate** access token (manual), and paste it into `.env` as `UPSTOX_ACCESS_TOKEN`.

Alternatively, run the auth dialog and exchange the `code`:

1. Set `UPSTOX_CLIENT_ID` and `UPSTOX_REDIRECT_URI` (must match the app).
2. Run:

   ```bash
   python scripts/print_upstox_auth_url.py
   ```

3. Open the printed URL, log in, copy `code` from the redirect URL.
4. `POST` to `https://api.upstox.com/v2/login/authorization/token` with `client_id`, `client_secret`, `redirect_uri`, `grant_type=authorization_code`, and `code` (see [Upstox authentication docs](https://upstox.com/developer/api-documentation/authentication)).

### 3. Environment file

```bash
copy .env.example .env
```

Edit `.env` and set at least `UPSTOX_ACCESS_TOKEN`. For Telegram, set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

### 4. Tuning

Edit `config/analysis.yaml` for thresholds (poll interval, liquidity, volume spike multiplier, strike window, etc.). You can still override poll/cooldown with `POLL_INTERVAL_SECONDS` / `SIGNAL_COOLDOWN_SECONDS` in `.env`.

## Run

From the project root (`marketanalyze`):

```bash
python main.py
```

Dry run (log only, no Telegram HTTP):

```bash
python main.py --dry-run
```

## Project layout

- `config/settings.py` — env-loaded settings + `AnalysisParameters` from YAML
- `config/analysis.yaml` — tunable thresholds
- `data/upstox_client.py` — REST client (chain, contracts, VWAP candles)
- `data/models.py` — chain row / snapshot types
- `analysis/signal_engine.py` — rules + rolling history
- `alerts/telegram.py` — Telegram Bot API
- `main.py` — poll loop, logging, CLI status line

## Logs

Signals are appended as JSON lines to `logs/signals_YYYY-MM-DD.log` with timestamp and a small strike sample.

## Notes

- Exchange-reported **volume** is **session cumulative**; the engine compares **differences between consecutive polls** (and requires several snapshots before signals fire).
- **VWAP** depends on the historical candle API for `NSE_INDEX|Nifty 50`. If it is unavailable, the VWAP filter is skipped (reason string indicates that) so you still get signals — tighten ops by monitoring logs.
- Adjust `min_open_interest` / `min_volume` for your risk and data quality.

## Disclaimer

This software is for **informational analysis only**. It is not investment advice. Options carry significant risk; verify all data with your broker before acting.
