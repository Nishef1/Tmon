"""One command for the REAL thing, without Docker: live TSETMC data -> features -> model ->
signals -> API + web UI, with intraday snapshots running in the background.

    backend/.venv/Scripts/python.exe backend/scripts/run_live.py [options]

Run it from a network that can reach tsetmc.com (the probe tells you at once if it cannot).
State lives in ./data (SQLite + local object store). First run backfills history (long: roughly
one polite request per instrument per endpoint); later runs only refresh the last days.

  --backfill        redo the full history even if a previous run finished
  --since YYYY-MM-DD  first day to load (default: five years back)
  --limit N         only the first N instruments (a quick smoke run)
  --skip-probe      do not stop when the probe fails
  --no-browser
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from datetime import date, timedelta

import run_demo as demo

DATA = demo.ROOT / "data"
DB = DATA / "tmon-live.sqlite3"
MARK = DATA / ".backfilled"


def py(*args: str, check: bool = True) -> int:
    return subprocess.run([sys.executable, *args], cwd=demo.BACKEND, check=check).returncode


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument(
        "--since", type=date.fromisoformat, default=date.today() - timedelta(days=5 * 366)
    )
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--skip-probe", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    DATA.mkdir(exist_ok=True)
    os.environ["TMON_DATABASE_URL"] = f"sqlite:///{DB.as_posix()}"
    os.environ["TMON_OBJECT_STORE"] = "file"
    os.environ["TMON_OBJECT_STORE_DIR"] = str(DATA / "objects")
    os.environ["TMON_CORS_ORIGINS"] = '["http://localhost:3000","http://127.0.0.1:3000"]'
    node = shutil.which("node")
    if not node or not demo.NEXT.exists():
        raise SystemExit("Node.js 20+ and `pnpm install` in frontend/ are required.")

    py(
        "-c",
        "from sqlalchemy import create_engine as c;import os;"
        "from tmon.storage.models import Base;"
        "Base.metadata.create_all(c(os.environ['TMON_DATABASE_URL']))",
    )

    print("→ probing TSETMC (reachability, parsers, column mappings)…")
    if py("-m", "tmon.ingest.tsetmc.cli", "probe", check=False) != 0 and not args.skip_probe:
        raise SystemExit(
            "\nProbe failed, so no live data can be loaded from this network. Fix the network (or "
            "set TMON_HTTP_PROXY) and run again, or pass --skip-probe to continue anyway."
        )

    if args.backfill or not MARK.exists():
        print(f"→ backfilling history since {args.since} (this takes a long time)…")
        cmd = ["-m", "tmon.ingest.tsetmc.cli", "backfill", "--since", args.since.isoformat()]
        py(*cmd, *(["--limit", str(args.limit)] if args.limit else []))
        MARK.write_text(date.today().isoformat())
    else:
        print("→ refreshing the last days…")
        py("-m", "tmon.ingest.tsetmc.cli", "eod")

    print("→ computing features and publishing today's signals…")
    py(
        "-c",
        "from tmon.core.db import session_scope;"
        "from tmon.features.store import refresh_features;"
        "from tmon.engine.service import train_and_publish;"
        "from tmon.storage.objectstore import get_object_store;"
        "s=session_scope().__enter__();"
        "print('feature rows', refresh_features(s,'D1'));s.commit();"
        "r=train_and_publish(s,get_object_store());s.commit();"
        "print(r.as_of, 'recommended', r.n_recommended, '-', r.message)",
    )

    if not (demo.FRONTEND / ".next" / "BUILD_ID").exists():
        print("→ building the frontend…")
        demo.run([node, str(demo.NEXT), "build"], demo.FRONTEND)

    procs = [
        subprocess.Popen([sys.executable, "scripts/serve_demo.py", str(DB)], cwd=demo.BACKEND),
        subprocess.Popen([node, str(demo.NEXT), "start", "-p", "3000"], cwd=demo.FRONTEND),
        subprocess.Popen(
            [sys.executable, "-m", "tmon.ingest.tsetmc.cli", "intraday", "--follow"],
            cwd=demo.BACKEND,
        ),
    ]
    try:
        demo.wait_for(demo.API_URL, "API")
        demo.wait_for(demo.WEB_URL, "web")
        print(f"\n✔ Tmon (live TSETMC data) → {demo.WEB_URL}\n  Ctrl+C to stop.\n")
        if not args.no_browser:
            webbrowser.open(demo.WEB_URL)
        while all(p.poll() is None for p in procs[:2]):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
