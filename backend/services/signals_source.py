"""
Load trading signals from (in order of merge priority):

1. `data/signals.json` — dashboard-native list (recommended for writes from your analyzer)
2. `SIGNALS_EXCEL_PATH` env or `data/signals.xlsx` — sheet "Signals" (see README)
3. JSONL logs `logs/signals_*.log` from project root (same format as nifty_options logger)

All sources are merged, de-duplicated by id, sorted newest first.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")

# backend/ directory
BACKEND_ROOT = Path(__file__).resolve().parent.parent
# marketanalyze/ project root (parent of backend/)
PROJECT_ROOT = BACKEND_ROOT.parent
DEFAULT_DATA_DIR = BACKEND_ROOT / "data"
DEFAULT_JSON = DEFAULT_DATA_DIR / "signals.json"
DEFAULT_EXCEL = DEFAULT_DATA_DIR / "signals.xlsx"
LOG_DIR = Path(os.environ.get("SIGNALS_LOG_DIR", str(PROJECT_ROOT / "logs")))


def _hhmm_from_iso(ts: str) -> str:
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=IST)
        else:
            t = t.astimezone(IST)
        return t.strftime("%H:%M")
    except (ValueError, TypeError):
        return ""


def _confidence_from_reason(reason: str, kind: str) -> str:
    r = (reason or "").lower()
    if "smart" in r and "otm" in r:
        return "High"
    if "reversal" in (kind or "").lower():
        return "Medium"
    if "vwap" in r and "not" in r:
        return "Low"
    return "Medium"


def _normalize_record(
    *,
    type_: str,
    strike: float | None,
    reason: str,
    timestamp_iso: str,
    confidence: str | None = None,
    id_: str | None = None,
) -> dict:
    conf = confidence or _confidence_from_reason(reason, type_)
    tid = id_ or str(uuid.uuid4())
    return {
        "id": tid,
        "type": type_,
        "strike": strike,
        "reason": reason or "",
        "time": _hhmm_from_iso(timestamp_iso) if timestamp_iso else "",
        "timestamp_iso": timestamp_iso or "",
        "confidence": conf,
    }


def load_from_json_file(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            continue
        ts = str(row.get("timestamp_iso") or row.get("ts") or "")
        out.append(
            _normalize_record(
                type_=str(row.get("type") or row.get("kind") or "UNKNOWN"),
                strike=_parse_strike(row.get("strike")),
                reason=str(row.get("reason") or ""),
                timestamp_iso=ts,
                confidence=row.get("confidence"),
                id_=str(row.get("id")) if row.get("id") else None,
            )
        )
    return out


def _parse_strike(v: object) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_from_excel(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        xl = pd.ExcelFile(path)
        sheet = "Signals" if "Signals" in xl.sheet_names else xl.sheet_names[0]
        df = pd.read_excel(path, sheet_name=sheet)
    except (OSError, ValueError, KeyError):
        return []

    col_map = {c.lower().strip().replace(" ", "_"): c for c in df.columns.astype(str)}

    def col(*names: str) -> str | None:
        for n in names:
            key = n.lower().replace(" ", "_")
            if key in col_map:
                return col_map[key]
        return None

    c_ts = col("timestamp", "timestamp_iso", "time", "datetime")
    c_type = col("signaltype", "type", "kind", "signal_type")
    c_strike = col("strike", "strike_price")
    c_reason = col("reason", "message")
    c_conf = col("confidence", "conf")

    if not c_type and not c_strike:
        return []

    out: list[dict] = []
    for _, row in df.iterrows():
        ts_val = row.get(c_ts) if c_ts else None
        if pd.isna(ts_val) and c_ts:
            ts_str = ""
        elif isinstance(ts_val, pd.Timestamp):
            ts_str = ts_val.isoformat()
        else:
            ts_str = str(ts_val or "")

        type_val = str(row.get(c_type) or "UNKNOWN") if c_type else "UNKNOWN"
        strike = _parse_strike(row.get(c_strike)) if c_strike else None
        reason = str(row.get(c_reason) or "") if c_reason else ""
        conf = str(row.get(c_conf) or "") if c_conf and not pd.isna(row.get(c_conf)) else None

        if not ts_str and c_ts is None:
            ts_str = datetime.now(IST).isoformat()

        out.append(
            _normalize_record(
                type_=type_val,
                strike=strike,
                reason=reason,
                timestamp_iso=ts_str,
                confidence=conf,
            )
        )
    return out


def load_from_jsonl_logs(log_dir: Path) -> list[dict]:
    if not log_dir.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(log_dir.glob("signals_*.log")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            sig = row.get("signal") or {}
            ts = str(row.get("ts") or "")
            kind = str(sig.get("kind") or "UNKNOWN")
            strike = _parse_strike(sig.get("strike"))
            reason = str(sig.get("reason") or "")
            meta = sig.get("meta") or {}
            conf = meta.get("confidence") if isinstance(meta, dict) else None
            oid = f"log-{hash(line) % 10**12}"
            out.append(
                _normalize_record(
                    type_=kind,
                    strike=strike,
                    reason=reason,
                    timestamp_iso=ts,
                    confidence=str(conf) if conf else None,
                    id_=oid,
                )
            )
    return out


def merge_signals(sources: list[tuple[str, list[dict]]]) -> tuple[list[dict], str]:
    seen: set[str] = set()
    merged: list[dict] = []
    labels: list[str] = []

    for label, rows in sources:
        if not rows:
            continue
        labels.append(label)
        for r in rows:
            key = f"{r.get('timestamp_iso')}|{r.get('type')}|{r.get('strike')}|{r.get('reason', '')[:80]}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(r)

    def sort_key(x: dict) -> str:
        return x.get("timestamp_iso") or ""

    merged.sort(key=sort_key, reverse=True)
    return merged, "+".join(labels) if labels else "none"


def load_all_signals() -> tuple[list[dict], str]:
    excel_path = Path(os.environ.get("SIGNALS_EXCEL_PATH", str(DEFAULT_EXCEL)))

    chunks: list[tuple[str, list[dict]]] = [
        ("json", load_from_json_file(DEFAULT_JSON)),
        ("excel", load_from_excel(excel_path)),
        ("log", load_from_jsonl_logs(LOG_DIR)),
    ]
    return merge_signals(chunks)
