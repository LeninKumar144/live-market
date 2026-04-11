"""
Print the Upstox OAuth authorization URL (step 1 of token exchange).

Usage:
  set UPSTOX_CLIENT_ID=...
  set UPSTOX_REDIRECT_URI=...
  python scripts/print_upstox_auth_url.py

After login, Upstox redirects with ?code=... — exchange that code via POST
https://api.upstox.com/v2/login/authorization/token (see README).
"""

from __future__ import annotations

import os
import urllib.parse


def main() -> None:
    cid = os.environ.get("UPSTOX_CLIENT_ID", "").strip()
    redir = os.environ.get("UPSTOX_REDIRECT_URI", "").strip()
    if not cid or not redir:
        raise SystemExit("Set UPSTOX_CLIENT_ID and UPSTOX_REDIRECT_URI in the environment.")
    q = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": cid,
            "redirect_uri": redir,
            "state": "nifty-options-analyzer",
        }
    )
    print(f"https://api.upstox.com/v2/login/authorization/dialog?{q}")


if __name__ == "__main__":
    main()
