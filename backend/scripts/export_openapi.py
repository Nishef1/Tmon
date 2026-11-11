"""Write the API's OpenAPI schema to ``frontend/openapi.json``.

The frontend generates its TypeScript types from this file (``pnpm gen:api``), so the API
contract has a single source of truth: the Pydantic models in ``tmon.api.schemas``.
CI regenerates both files and fails if they differ from the committed ones.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tmon.api.main import app

OUT = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    target.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
