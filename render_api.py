"""
ASGI entry for Render (and any host) when the process cwd is the **repo root**.

`uvicorn main:app` would import the repo-root `main.py` (CLI), which has no `app`.
This module forces the backend FastAPI instance to load instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(_backend))

import main as _backend_main  # noqa: E402  — resolves to backend/main.py

app = _backend_main.app
