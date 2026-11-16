"""Docs cannot point at files that no longer exist.

Two checks: every relative markdown link in ``docs/`` and ``AGENTS.md`` resolves, and every
``docs/...`` path named in source code, config and deploy scripts exists. Deleting or renaming a
doc without fixing its references fails here, not months later in a reader's head.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"\]\(([^)\s]+)\)")
CODE_REF = re.compile(r"docs/[\w./-]+\.(?:md|json|csv)")
SOURCE_DIRS = (
    "backend/src",
    "backend/config",
    "backend/scripts",
    "frontend/app",
    "frontend/components",
    "frontend/lib",
    "frontend/tests",
    "deploy",
    ".claude",
)
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".yaml", ".yml", ".sh", ".ps1", ".md"}


def _markdown_files() -> list[Path]:
    files = sorted((ROOT / "docs").rglob("*.md"))
    files += [p for p in (ROOT / "AGENTS.md", ROOT / "CLAUDE.md") if p.exists()]
    files += sorted((ROOT / ".claude").rglob("*.md")) if (ROOT / ".claude").exists() else []
    return files


def _broken_links(md: Path) -> list[str]:
    out = []
    text = re.sub(r"```.*?```", "", md.read_text(encoding="utf-8"), flags=re.DOTALL)
    for target in LINK.findall(text):
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            continue
        path = target.split("#", 1)[0]
        if path and not (md.parent / path).exists():
            out.append(f"{md.relative_to(ROOT)} -> {target}")
    return out


def test_markdown_links_resolve() -> None:
    broken = [b for md in _markdown_files() for b in _broken_links(md)]
    assert not broken, "broken links:\n" + "\n".join(broken)


def test_code_references_to_docs_exist() -> None:
    missing = []
    for d in SOURCE_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for f in base.rglob("*"):
            if f.suffix not in SOURCE_SUFFIXES or "node_modules" in f.parts or not f.is_file():
                continue
            for ref in CODE_REF.findall(f.read_text(encoding="utf-8", errors="ignore")):
                ref = ref.rstrip(".")
                if not (ROOT / ref).exists():
                    missing.append(f"{f.relative_to(ROOT)}: {ref}")
    assert not missing, "references to missing docs:\n" + "\n".join(sorted(set(missing)))
