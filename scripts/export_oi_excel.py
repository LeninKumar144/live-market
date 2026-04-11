#!/usr/bin/env python3
"""
Export NIFTY option chain OI (strike-wise + summary) to an Excel workbook.

Example:
  python scripts/export_oi_excel.py
  python scripts/export_oi_excel.py --expiry 2026-03-30 --output exports/nifty_oi.xlsx
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config.settings import get_settings, load_analysis_parameters, project_root
from data.upstox_client import UpstoxClient


def main() -> int:
    p = argparse.ArgumentParser(description="Export NIFTY option OI to Excel")
    p.add_argument("--expiry", default="2026-03-30", help="Option chain expiry YYYY-MM-DD")
    p.add_argument(
        "--output",
        default="",
        help="Output .xlsx path (default: exports/nifty_oi_<expiry>_<timestamp>.xlsx)",
    )
    args = p.parse_args()

    expiry = args.expiry.strip()
    settings = get_settings()
    params = load_analysis_parameters(settings)
    client = UpstoxClient(settings, params)
    rows = client.fetch_option_chain(expiry)
    client.close()

    if not rows:
        print("No option chain rows returned.", file=sys.stderr)
        return 1

    spot = rows[0].underlying_spot_price if rows else 0.0

    records = []
    for r in rows:
        records.append(
            {
                "Strike": int(r.strike_price),
                "Call_OI": r.call.oi,
                "Put_OI": r.put.oi,
                "Call_Volume": r.call.volume,
                "Put_Volume": r.put.volume,
                "Call_Prev_OI": r.call.prev_oi,
                "Put_Prev_OI": r.put.prev_oi,
                "Call_OI_Change": r.call.oi - r.call.prev_oi,
                "Put_OI_Change": r.put.oi - r.put.prev_oi,
                "Call_LTP": r.call.ltp,
                "Put_LTP": r.put.ltp,
            }
        )

    df = pd.DataFrame(records)
    total_ce = int(df["Call_OI"].sum())
    total_pe = int(df["Put_OI"].sum())
    total_ce_vol = int(df["Call_Volume"].sum())
    total_pe_vol = int(df["Put_Volume"].sum())
    pcr = (total_pe / total_ce) if total_ce else 0.0

    summary = pd.DataFrame(
        [
            {"Field": "Underlying (spot from chain)", "Value": spot},
            {"Field": "Chain expiry", "Value": expiry},
            {"Field": "Total Call OI", "Value": total_ce},
            {"Field": "Total Put OI", "Value": total_pe},
            {"Field": "Put/Call OI ratio", "Value": round(pcr, 6)},
            {"Field": "Total Call volume", "Value": total_ce_vol},
            {"Field": "Total Put volume", "Value": total_pe_vol},
            {"Field": "Exported at (IST)", "Value": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
        ]
    )

    out = args.output.strip()
    if not out:
        safe_exp = expiry.replace("-", "")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = project_root() / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = str(out_dir / f"nifty_oi_{safe_exp}_{ts}.xlsx")
    else:
        outp = Path(out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        out = str(outp)

    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        df.to_excel(writer, sheet_name="Strikewise_OI", index=False)

    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
