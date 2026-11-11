"""Serve the API against the local SYNTHETIC demo database (see demo_db.py). No Docker needed."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn

db = Path(sys.argv[1] if len(sys.argv) > 1 else "demo/tmon-demo.sqlite3").resolve()
if not db.exists():
    sys.exit(f"{db} not found; run scripts/demo_db.py first")
os.environ["TMON_DATABASE_URL"] = f"sqlite:///{db.as_posix()}"

if __name__ == "__main__":
    uvicorn.run("tmon.api.main:app", host="127.0.0.1", port=8000)
