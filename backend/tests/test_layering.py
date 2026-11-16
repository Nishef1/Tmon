"""Import ratchet between ``tmon`` packages.

``ALLOWED`` is the package graph as it stood when this test was written. A new edge (package A
starts importing package B) fails here: either it is a mistake, or it is a deliberate design
change and the edge is added below in the same commit, with a reason. Removing an edge from the
code also fails until it is removed below, so the frozen graph only ever shrinks by intent.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "tmon"

# package -> packages it may import (besides itself). Keep sorted.
ALLOWED: dict[str, set[str]] = {
    "api": {
        "backtest",
        "core",
        "domain",
        "engine",
        "features",
        "ingest",
        "portfolio",
        "storage",
        "tools",
    },
    "backtest": {"core", "domain", "engine", "features", "labeling", "models", "storage"},
    "core": set(),
    "devtools": {"backtest"},
    "domain": {"storage"},
    "engine": {"backtest", "core", "domain", "features", "labeling", "models", "storage"},
    "features": {"core", "domain", "ingest", "storage"},
    "ingest": {"core", "domain", "features", "storage"},
    "labeling": {"core", "domain", "features"},
    "models": {"backtest", "core", "domain", "engine", "features", "labeling"},
    "portfolio": {"api", "core", "domain", "ingest", "storage", "tasks", "tools"},
    "storage": {"core", "domain"},
    "tasks": {"core", "domain", "engine", "features", "ingest", "storage", "tools"},
    "tools": {"backtest", "core", "domain", "engine", "features", "ingest", "storage"},
}


def actual_edges() -> dict[str, set[str]]:
    edges: dict[str, set[str]] = {}
    for f in SRC.rglob("*.py"):
        rel = f.relative_to(SRC).parts
        if len(rel) < 2:
            continue
        pkg = rel[0]
        deps = edges.setdefault(pkg, set())
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for n in names:
                parts = n.split(".")
                if (
                    parts[0] == "tmon"
                    and len(parts) > 1
                    and parts[1] != pkg
                    and (SRC / parts[1]).is_dir()
                ):
                    deps.add(parts[1])
    return edges


def test_no_new_package_edges() -> None:
    actual = actual_edges()
    new = sorted(f"{a} -> {b}" for a, deps in actual.items() for b in deps - ALLOWED.get(a, set()))
    assert not new, (
        "new import edges between packages (fix the import, or add the edge to ALLOWED "
        "with a reason):\n" + "\n".join(new)
    )


def test_allowed_graph_has_no_dead_edges() -> None:
    actual = actual_edges()
    dead = sorted(f"{a} -> {b}" for a, deps in ALLOWED.items() for b in deps - actual.get(a, set()))
    assert not dead, "edges no longer used; remove them from ALLOWED:\n" + "\n".join(dead)
