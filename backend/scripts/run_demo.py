"""One command to see Tmon locally, without Docker, on SYNTHETIC data.

    backend/.venv/Scripts/python.exe backend/scripts/run_demo.py [--rebuild] [--no-browser]

First run: builds the demo database and the frontend (a few minutes). Later runs start at once.
--rebuild redoes both. Ctrl+C stops everything. Nothing here is real market data.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND, FRONTEND = ROOT / "backend", ROOT / "frontend"
DB = ROOT / "demo" / "tmon-demo.sqlite3"
NEXT = FRONTEND / "node_modules" / "next" / "dist" / "bin" / "next"
API_URL, WEB_URL = "http://127.0.0.1:8000/health", "http://127.0.0.1:3000"


def run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def wait_for(url: str, name: str, timeout: float = 90) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:
            time.sleep(0.5)
    raise SystemExit(f"{name} did not come up at {url}")


def main() -> None:
    rebuild = "--rebuild" in sys.argv
    node = shutil.which("node")
    if not node:
        raise SystemExit("node is required (Node.js 20+).")
    if not NEXT.exists():
        raise SystemExit("Run `pnpm install` in frontend/ first.")

    if rebuild or not DB.exists():
        print("→ building the synthetic demo database (about a minute)…")
        run([sys.executable, "scripts/demo_db.py", str(DB)], BACKEND)
    if rebuild or not (FRONTEND / ".next" / "BUILD_ID").exists():
        print("→ building the frontend…")
        run([node, str(NEXT), "build"], FRONTEND)

    procs = [
        subprocess.Popen([sys.executable, "scripts/serve_demo.py", str(DB)], cwd=BACKEND),
        subprocess.Popen([node, str(NEXT), "start", "-p", "3000"], cwd=FRONTEND),
    ]
    try:
        wait_for(API_URL, "API")
        wait_for(WEB_URL, "web")
        print(
            f"\n✔ Tmon (synthetic demo data) → {WEB_URL}   |   API docs → http://127.0.0.1:8000/docs"
        )
        print("  Ctrl+C to stop.\n")
        if "--no-browser" not in sys.argv:
            webbrowser.open(WEB_URL)
        while all(p.poll() is None for p in procs):
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
