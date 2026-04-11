"""Upstox REST client: option chain, contracts, intraday candles (VWAP)."""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from config.settings import AnalysisParameters, Settings
from data.models import LegMarket, StrikeRow

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")


def _retryable_http_error(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 502, 503, 504)
    return False


class UpstoxAPIError(RuntimeError):
    """Raised when Upstox returns an error payload or unexpected status."""


def _encode_key(instrument_key: str) -> str:
    return instrument_key.replace("|", "%7C").replace(" ", "%20")


class UpstoxClient:
    """Thin v2 API wrapper with retries."""

    def __init__(self, settings: Settings, params: AnalysisParameters) -> None:
        self._token = settings.upstox_access_token
        self._base = settings.upstox_api_base.rstrip("/")
        self._underlying = settings.nifty_instrument_key
        self._params = params
        self._client = httpx.Client(timeout=params.http_timeout_seconds)

    def close(self) -> None:
        self._client.close()

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._token}",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        last_err: BaseException | None = None
        attempts = max(1, int(self._params.max_http_retries))
        for i in range(attempts):
            try:
                url = f"{self._base}{path}"
                resp = self._client.get(url, headers=self._headers(), params=params or {})
                if resp.status_code >= 400:
                    resp.raise_for_status()
                data = resp.json()
                if data.get("status") != "success":
                    raise UpstoxAPIError(data.get("errors") or data.get("message") or str(data))
                return data
            except Exception as e:
                last_err = e
                retryable = _retryable_http_error(e)
                if not retryable or i == attempts - 1:
                    raise
                delay = min(20.0, float(self._params.retry_backoff_base_seconds) ** i)
                logger.warning("Upstox GET retry %s/%s after %s (sleep %.1fs)", i + 1, attempts, e, delay)
                time.sleep(delay)
        raise RuntimeError("unreachable") from last_err

    def _post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any]:
        last_err: BaseException | None = None
        attempts = max(1, int(self._params.max_http_retries))
        for i in range(attempts):
            try:
                url = f"{self._base}{path}"
                resp = self._client.post(url, headers=self._headers(), json=json_body)
                if resp.status_code >= 400:
                    resp.raise_for_status()
                data = resp.json()
                if data.get("status") != "success":
                    raise UpstoxAPIError(data.get("errors") or data.get("message") or str(data))
                return data
            except Exception as e:
                last_err = e
                retryable = _retryable_http_error(e)
                if not retryable or i == attempts - 1:
                    raise
                delay = min(20.0, float(self._params.retry_backoff_base_seconds) ** i)
                logger.warning("Upstox POST retry %s/%s after %s (sleep %.1fs)", i + 1, attempts, e, delay)
                time.sleep(delay)
        raise RuntimeError("unreachable") from last_err

    def fetch_option_lot_size(self, underlying_instrument_key: str, expiry_date: str) -> int | None:
        """
        Lot size for options on this underlying + expiry (from /option/contract).

        Same lot_size is typically shared across strikes for that expiry.
        """
        raw = self._get(
            "/option/contract",
            params={"instrument_key": underlying_instrument_key, "expiry_date": expiry_date},
        )
        rows = raw.get("data") or []
        for row in rows:
            ls = row.get("lot_size")
            if ls is None:
                continue
            try:
                n = int(ls)
                if n > 0:
                    return n
            except (TypeError, ValueError):
                continue
        return None

    def post_charges_margin(self, instruments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        POST /charges/margin — returns `data.margins` rows in request order (max 20 legs).

        Each row may include total_margin, net_buy_premium, span_margin, etc.
        """
        if not instruments:
            return []
        raw = self._post("/charges/margin", {"instruments": instruments})
        margins = (raw.get("data") or {}).get("margins")
        return list(margins) if isinstance(margins, list) else []

    def list_option_expiries(self, underlying_instrument_key: str | None = None) -> list[date]:
        """Option expiries on or after today (IST) for the given underlying (EQ/index key)."""
        ik = underlying_instrument_key or self._underlying
        raw = self._get("/option/contract", params={"instrument_key": ik})
        rows = raw.get("data") or []
        today = datetime.now(IST).date()
        out: set[date] = set()
        for row in rows:
            exp = row.get("expiry")
            if not exp:
                continue
            try:
                d = date.fromisoformat(str(exp)[:10])
            except ValueError:
                continue
            if d >= today:
                out.add(d)
        return sorted(out)

    def list_future_expiries(self) -> list[date]:
        """Unique NIFTY option expiries on or after today (IST)."""
        return self.list_option_expiries(None)

    def resolve_expiry(
        self, fixed_expiry: str | None, underlying_instrument_key: str | None = None
    ) -> str:
        """Return YYYY-MM-DD expiry to query."""
        if fixed_expiry:
            return fixed_expiry
        expiries = self.list_option_expiries(underlying_instrument_key)
        if not expiries:
            raise UpstoxAPIError("No future expiries returned for underlying.")
        return expiries[0].isoformat()

    def resolve_nse_equity_instrument_key(self, symbol: str) -> str | None:
        """
        Locate cash equity instrument_key for an NSE ticker (for stock option-chain underlying).

        Returns None if no unambiguous EQ match.
        """
        sym_u = str(symbol or "").strip().upper()
        if not sym_u:
            return None
        # API caps `records` at 30; EQ segment narrows to cash equity.
        rows = self.search_instruments(
            query=sym_u,
            exchanges="NSE",
            segments="EQ",
            page_number=1,
            records=30,
        )
        for row in rows:
            ts = str(row.get("trading_symbol") or "").strip().upper()
            if ts != sym_u:
                continue
            seg = str(row.get("segment") or "").upper()
            it = str(row.get("instrument_type") or "").upper()
            if "EQ" in seg or it == "EQ":
                ik = str(row.get("instrument_key") or "").strip()
                if ik:
                    return ik
        return None

    def search_instruments(self, **query: Any) -> list[dict[str, Any]]:
        """GET /instruments/search — pass query=, segments=, expiry=, etc."""
        raw = self._get("/instruments/search", params=query)
        return list(raw.get("data") or [])

    def fetch_market_quotes(self, instrument_keys: list[str]) -> dict[str, Any]:
        """GET /market-quote/quotes for one or more `NSE_*|...` keys (max 500)."""
        if not instrument_keys:
            return {}
        joined = ",".join(instrument_keys)
        raw = self._get("/market-quote/quotes", params={"instrument_key": joined})
        return raw.get("data") or {}

    def find_nifty_index_future(self, expiry: str = "current_month") -> tuple[str, str]:
        """
        Locate NIFTY 50 **index** future on NSE_FO (excludes NIFTY BANK / single-stock NIFTY*).

        Returns (instrument_key, trading_symbol). Raises if none found.
        """
        rows = self.search_instruments(
            query="NIFTY",
            exchanges="NSE",
            segments="FO",
            expiry=expiry,
            page_number=1,
            records=30,
        )
        candidates: list[tuple[str, str]] = []
        for row in rows:
            if str(row.get("segment") or "") != "NSE_FO":
                continue
            sym = str(row.get("trading_symbol") or "")
            su = sym.upper()
            it = str(row.get("instrument_type") or "").upper()
            if it != "FUT" and "FUT" not in su:
                continue
            if "BANK" in su:
                continue
            if not su.startswith("NIFTY "):
                continue
            second = su.split()[1] if len(su.split()) > 1 else ""
            if second.isalpha() and len(second) > 3:
                continue
            ik = str(row.get("instrument_key") or "")
            if ik:
                candidates.append((ik, sym))

        if not candidates:
            raise UpstoxAPIError("No NIFTY index future in instrument search; try expiry=near_month.")

        candidates.sort(key=lambda x: x[1])
        return candidates[0]

    def fetch_option_chain(
        self, expiry_date: str, underlying_instrument_key: str | None = None
    ) -> list[StrikeRow]:
        ik = underlying_instrument_key or self._underlying
        raw = self._get(
            "/option/chain",
            params={"instrument_key": ik, "expiry_date": expiry_date},
        )
        data = raw.get("data") or []
        rows: list[StrikeRow] = []
        for item in data:
            try:
                strike = float(item["strike_price"])
            except (KeyError, TypeError, ValueError):
                continue
            spot = float(item.get("underlying_spot_price") or 0.0)
            call = item.get("call_options") or {}
            put = item.get("put_options") or {}
            c_md = call.get("market_data") or {}
            p_md = put.get("market_data") or {}

            def leg(md: dict[str, Any], ik: str) -> LegMarket:
                return LegMarket(
                    instrument_key=str(ik or md.get("instrument_key") or ""),
                    ltp=float(md.get("ltp") or 0.0),
                    volume=int(md.get("volume") or 0),
                    oi=int(md.get("oi") or 0),
                    prev_oi=int(md.get("prev_oi") or 0),
                )

            c_ik = str(call.get("instrument_key") or "")
            p_ik = str(put.get("instrument_key") or "")
            rows.append(
                StrikeRow(
                    strike_price=strike,
                    underlying_spot_price=spot,
                    call=leg(c_md, c_ik),
                    put=leg(p_md, p_ik),
                    raw=item,
                )
            )
        rows.sort(key=lambda r: r.strike_price)
        return rows

    def fetch_daily_candles(
        self, from_date: date, to_date: date
    ) -> list[tuple[date, float, float, float, float]]:
        """
        Daily OHLC for the index (NIFTY 50) from historical-candle API.

        Returns sorted rows: (session_date, open, high, low, close). Used for pivot (prior day / week / month).
        """
        if from_date > to_date:
            from_date, to_date = to_date, from_date
        path = f"/historical-candle/{_encode_key(self._underlying)}/day/{to_date.isoformat()}/{from_date.isoformat()}"
        try:
            raw = self._get(path)
        except Exception as e:
            logger.warning("Daily candles unavailable: %s", e)
            return []
        candles = (raw.get("data") or {}).get("candles") or []
        out: list[tuple[date, float, float, float, float]] = []
        for c in candles:
            if not c or len(c) < 5:
                continue
            ts = str(c[0])
            try:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=IST)
                else:
                    t = t.astimezone(IST)
                d = t.date()
            except ValueError:
                continue
            o, h, low, cl = float(c[1]), float(c[2]), float(c[3]), float(c[4])
            out.append((d, o, h, low, cl))
        merged: dict[date, list[float]] = {}
        for d, o, h, low, cl in out:
            if d not in merged:
                merged[d] = [o, h, low, cl]
            else:
                m = merged[d]
                m[1] = max(m[1], h)
                m[2] = min(m[2], low)
                m[3] = cl
        return [(d, merged[d][0], merged[d][1], merged[d][2], merged[d][3]) for d in sorted(merged.keys())]

    def fetch_vwap_approx(self, for_day: date | None = None) -> tuple[float | None, int]:
        """
        Session VWAP from 1-minute candles (typical price × volume).

        Returns (vwap, candle_count_used). None if no volume in window.
        """
        day = for_day or datetime.now(IST).date()
        to_s = day.isoformat()
        from_s = (day - timedelta(days=1)).isoformat()
        path = f"/historical-candle/{_encode_key(self._underlying)}/1minute/{to_s}/{from_s}"
        try:
            raw = self._get(path)
        except Exception as e:
            logger.warning("VWAP candles unavailable: %s", e)
            return None, 0
        candles = (raw.get("data") or {}).get("candles") or []
        num = 0
        pv = 0.0
        vol = 0
        for c in candles:
            if not c or len(c) < 6:
                continue
            ts = str(c[0])
            try:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=IST)
                else:
                    t = t.astimezone(IST)
            except ValueError:
                continue
            if t.date() != day:
                continue
            o, h, low, cl, v = float(c[1]), float(c[2]), float(c[3]), float(c[4]), int(c[5] or 0)
            if v <= 0:
                continue
            typical = (h + low + cl) / 3.0
            pv += typical * v
            vol += v
            num += 1
        if vol <= 0:
            return None, 0
        return pv / vol, num

    def fetch_1minute_candles(
        self,
        instrument_key: str,
        for_day: date | None = None,
    ) -> list[tuple[datetime, float, float, float, float, int]]:
        """
        Intraday 1-minute OHLCV for any instrument (e.g. NIFTY index future).

        Returns rows sorted by time (IST-aware datetimes). `for_day` defaults to today IST.
        """
        day = for_day or datetime.now(IST).date()
        if day > datetime.now(IST).date():
            day = datetime.now(IST).date()
        to_s = day.isoformat()
        from_s = (day - timedelta(days=1)).isoformat()
        path = f"/historical-candle/{_encode_key(instrument_key)}/1minute/{to_s}/{from_s}"
        try:
            raw = self._get(path)
        except Exception as e:
            logger.warning("1-minute candles unavailable for %s: %s", instrument_key, e)
            return []
        candles = (raw.get("data") or {}).get("candles") or []
        out: list[tuple[datetime, float, float, float, float, int]] = []
        for c in candles:
            if not c or len(c) < 6:
                continue
            ts = str(c[0])
            try:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=IST)
                else:
                    t = t.astimezone(IST)
            except ValueError:
                continue
            if t.date() != day:
                continue
            o, h, low, cl, v = float(c[1]), float(c[2]), float(c[3]), float(c[4]), int(c[5] or 0)
            out.append((t, o, h, low, cl, v))
        out.sort(key=lambda x: x[0])
        return out
