"""Send only what changed from the PC database to the server's (stdlib only: it runs on both).

``fingerprint`` summarises a database in small numbers: for the big day-keyed tables one line per
day (row count, plus sums of a few columns for the days that can still be revised), for every
other table one hash of its content. ``delta`` compares the PC's fingerprint with the server's and
writes a small database holding only the days / tables that differ. ``apply`` swaps exactly those
days / tables into the server database in one transaction and re-checks the result.

Comparing content (not clocks) means a day revised on the PC, a row deleted on the PC and a server
that fell behind all show up the same way: as a differing day. ``delta`` answers ``full`` (and says
why) when a delta would not be safe or smaller: the server has no database, the table layout
differs, or too much differs. The caller then ships the whole database instead.

    python syncdb.py fingerprint DB [--deep-from JSON] [--deep]
    python syncdb.py delta PC_DB SERVER_FINGERPRINT.json OUT_DB
    python syncdb.py apply SERVER_DB DELTA_DB
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from typing import Any

# table -> (key expression, sums that fingerprint a day's content, sums-always-deep?)
# Old days of the two huge tables are compared by row count only (an index scan); their last
# DEEP_KEYS days, where late corrections happen, and all days of the small tables use the sums.
PARTITIONED: dict[str, tuple[str, str, bool]] = {
    "prices_daily": (
        "date",
        "round(sum(close),2), round(sum(volume),2), round(sum(high),2)",
        False,
    ),
    "client_types_daily": (
        "date",
        "round(sum(buy_volume_i),2), round(sum(sell_volume_n),2), sum(buy_count_i)",
        False,
    ),
    "features": ("date", 'sum(length("values"))', True),
    "price_adjustments": ("date", "sum(cast(round(adj_factor * 1000000) as integer))", True),
    "order_book_daily": ("date", "sum(cast(round(close_imbalance * 1000000) as integer)), sum(n_events)", True),
    "market_index_daily": ("date", "sum(cast(round(close * 10000) as integer))", True),
    "fund_nav": ("date", "round(sum(net_asset),2)", True),
    "share_changes": ("date", "sum(shares_new)", True),
    "trading_calendar": ("date", "sum(is_open)", True),
    "raw_payloads": ("substr(fetched_at,1,10)", "sum(size_bytes)", True),
}
FEATURE_KEYS = 60  # the site reads only the newest feature rows; the server keeps this many days
DEEP_KEYS = 30
MAX_DELTA_ROWS = 600_000  # beyond this a delta is no smaller than the full copy
FULL_IF_SHIPPED_ABOVE = 0.35  # share of prices_daily rows a delta may carry before a full copy wins
PROVENANCE = {
    "fetched_at",
    "source_url",
}  # not content: refreshed on every fetch, ignored by hashes
MAX_URL = 300  # source_url longer than this (the batch history URLs) keeps only its endpoint

TRIM_SQL = (
    """update "{t}" set source_url = substr(source_url, 1, instr(source_url, '&a=') + 2)"""
    """ || '...' """
    """where length(source_url) > {n} and instr(source_url, '&a=') > 0"""
)


def _tables(db: sqlite3.Connection) -> list[str]:
    return [
        r[0]
        for r in db.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%' "
            "order by name"
        )
    ]


def _columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in db.execute(f'pragma table_info("{table}")')]


def _keys(db: sqlite3.Connection, table: str) -> list[str]:
    expr = PARTITIONED[table][0]
    return [str(r[0]) for r in db.execute(f'select distinct {expr} from "{table}" order by 1')]


def deep_from(db: sqlite3.Connection) -> dict[str, str]:
    """Per table, the oldest key that gets the content sums (the newest DEEP_KEYS keys)."""
    out: dict[str, str] = {}
    for t, (_expr, _sums, always) in PARTITIONED.items():
        if t in _tables(db) and not always:
            keys = _keys(db, t)
            if keys:
                out[t] = keys[-DEEP_KEYS:][0]
    return out


def _hash_table(db: sqlite3.Connection, table: str) -> tuple[int, str]:
    cols = [c for c in _columns(db, table) if c not in PROVENANCE]
    order = ", ".join(f'"{c}"' for c in cols)
    h = hashlib.sha256()
    n = 0
    for row in db.execute(f'select {order} from "{table}" order by {order}'):
        h.update(repr(row).encode())
        n += 1
    return n, h.hexdigest()


def fingerprint(
    db: sqlite3.Connection,
    deep_cut: dict[str, str] | None = None,
    deep: bool = False,
    window: bool = False,
) -> dict[str, Any]:
    """``deep_cut`` is the PC's own cut (table -> oldest deep key) so both sides sum the same days.
    ``window`` (the PC side) limits features to the days the server keeps; the server's own
    fingerprint lists all its days, so older ones show up as days to drop."""
    cut = deep_cut if deep_cut is not None else deep_from(db)
    tables: dict[str, Any] = {}
    names = _tables(db)
    for t in names:
        cols = _columns(db, t)
        if t not in PARTITIONED:
            n, h = _hash_table(db, t)
            tables[t] = {"cols": cols, "kind": "whole", "n": n, "hash": h}
            continue
        expr, sums, always = PARTITIONED[t]
        parts: dict[str, list[Any]] = {}
        first = None
        if t == "features" and window:
            keys = _keys(db, t)
            first = keys[-FEATURE_KEYS:][0] if keys else None
        counts = db.execute(f'select {expr}, count(*) from "{t}" group by 1')
        for k, n in counts:
            if first is None or str(k) >= first:
                parts[str(k)] = [n]
        if parts:
            lo = None if (always or deep) else cut.get(t, "")
            q = f'select {expr}, {sums} from "{t}" where {expr} >= ? group by 1'
            floor = min(parts) if lo is None else max(lo, min(parts))
            for row in db.execute(q, (floor,)):
                if str(row[0]) in parts:
                    parts[str(row[0])] = [parts[str(row[0])][0], *row[1:]]
        tables[t] = {"cols": cols, "kind": "part", "parts": parts, "deep_cut": cut.get(t)}
    return {"tables": tables, "deep_cut": cut}


def _plan(pc: dict[str, Any], srv: dict[str, Any] | None) -> dict[str, Any]:
    """What differs. ``full`` is set (with ``reason``) when a delta is not the right tool."""
    if not srv or "tables" not in srv:
        return {"full": True, "reason": "the server has no readable database"}
    parts: dict[str, list[str]] = {}
    drop: dict[str, list[str]] = {}
    whole: list[str] = []
    for t, info in pc["tables"].items():
        other = srv["tables"].get(t)
        if other is None or other["cols"] != info["cols"] or other["kind"] != info["kind"]:
            return {"full": True, "reason": f"table layout differs: {t}"}
        if info["kind"] == "whole":
            if other["hash"] != info["hash"]:
                whole.append(t)
            continue
        changed = [k for k, v in info["parts"].items() if _differs(v, other["parts"].get(k))]
        gone = [k for k in other["parts"] if k not in info["parts"]]
        if changed:
            parts[t] = sorted(changed)
        if gone:
            drop[t] = sorted(gone)
    return {"full": False, "parts": parts, "drop": drop, "whole": whole}


def _differs(a: list[Any], b: list[Any] | None) -> bool:
    if b is None:
        return True
    if len(a) != len(b):  # one side summed this day deeper than the other: compare what both have
        return a[0] != b[0]
    return a != b


def delta(pc_path: str, srv_fp: dict[str, Any] | None, out_path: str) -> dict[str, Any]:
    pc_db = sqlite3.connect(f"file:{pc_path}?mode=ro", uri=True)
    cut = (srv_fp or {}).get("deep_cut")
    pc = fingerprint(pc_db, cut, window=True)
    plan = _plan(pc, srv_fp)
    if plan["full"]:
        return plan
    rows = {t: len(k) for t, k in plan["parts"].items()}
    total = pc_db.execute("select count(*) from prices_daily").fetchone()[0] or 1
    pr = _count_rows(pc_db, "prices_daily", plan["parts"].get("prices_daily", []))
    if pr / total > FULL_IF_SHIPPED_ABOVE:
        return {"full": True, "reason": f"{pr} of {total} price rows differ"}
    est = sum(_count_rows(pc_db, t, k) for t, k in plan["parts"].items())
    if est > MAX_DELTA_ROWS:
        return {"full": True, "reason": f"{est} rows differ (more than {MAX_DELTA_ROWS})"}
    import os

    if os.path.exists(out_path):
        os.remove(out_path)
    out = sqlite3.connect(out_path)
    out.execute("attach database ? as pc", (pc_path,))
    shipped = 0
    for t, keys in plan["parts"].items():
        expr = PARTITIONED[t][0]
        out.execute(f'create table "{t}" as select * from pc."{t}" where 0')
        for i in range(0, len(keys), 500):
            chunk = keys[i : i + 500]
            marks = ",".join("?" * len(chunk))
            out.execute(
                f'insert into "{t}" select * from pc."{t}" where {expr} in ({marks})', chunk
            )
        shipped += out.execute(f'select count(*) from "{t}"').fetchone()[0]
    for t in plan["whole"]:
        out.execute(f'create table "{t}" as select * from pc."{t}"')
        shipped += out.execute(f'select count(*) from "{t}"').fetchone()[0]
    out.commit()
    out.execute("detach database pc")
    _trim_urls(out)
    out.execute("create table _plan (doc text)")
    expect = {t: pc["tables"][t] for t in [*plan["parts"], *plan["drop"], *plan["whole"]]}
    out.execute(
        "insert into _plan values (?)",
        (json.dumps({"plan": plan, "expect": expect, "deep_cut": pc["deep_cut"]}),),
    )
    out.commit()
    out.execute("vacuum")
    out.close()
    return {**plan, "full": False, "rows": shipped, "days": rows}


def _count_rows(db: sqlite3.Connection, table: str, keys: list[str]) -> int:
    expr = PARTITIONED[table][0]
    n = 0
    for i in range(0, len(keys), 500):
        chunk = keys[i : i + 500]
        n += db.execute(
            f'select count(*) from "{table}" where {expr} in ({",".join("?" * len(chunk))})', chunk
        ).fetchone()[0]
    return n


def _trim_urls(db: sqlite3.Connection) -> None:
    for t in _tables(db):
        if t.startswith("_"):
            continue
        if "source_url" in _columns(db, t):
            db.execute(TRIM_SQL.format(t=t, n=MAX_URL))
    db.commit()


def apply(server_path: str, delta_path: str) -> dict[str, Any]:
    db = sqlite3.connect(server_path, timeout=120, isolation_level=None)
    db.execute("attach database ? as d", (delta_path,))
    doc = json.loads(db.execute("select doc from d._plan").fetchone()[0])
    plan, expect = doc["plan"], doc["expect"]
    db.execute("begin immediate")
    try:
        for t, keys in {**plan["drop"], **plan["parts"]}.items():
            expr = PARTITIONED[t][0]
            for i in range(0, len(keys), 500):
                chunk = keys[i : i + 500]
                db.execute(
                    f'delete from main."{t}" where {expr} in ({",".join("?" * len(chunk))})', chunk
                )
        for t in plan["parts"]:
            cols = ", ".join(f'"{c}"' for c in _columns(db, t))
            db.execute(f'insert into main."{t}" ({cols}) select {cols} from d."{t}"')
        for t in plan["whole"]:
            cols = ", ".join(f'"{c}"' for c in _columns(db, t))
            db.execute(f'delete from main."{t}"')
            db.execute(f'insert into main."{t}" ({cols}) select {cols} from d."{t}"')
        db.execute("commit")
    except Exception:
        db.execute("rollback")
        raise
    db.execute("detach database d")
    bad = verify(db, expect, doc["deep_cut"])
    return {"applied": True, "mismatch": bad}


def verify(db: sqlite3.Connection, expect: dict[str, Any], deep_cut: dict[str, str]) -> list[str]:
    """Tables the delta touched must now look exactly like the PC's."""
    now = fingerprint(db, deep_cut)
    bad: list[str] = []
    for t, info in expect.items():
        got = now["tables"][t]
        if info["kind"] == "whole":
            if (got["n"], got["hash"]) != (info["n"], info["hash"]):
                bad.append(t)
            continue
        pc_parts = info["parts"]
        if set(got["parts"]) != set(pc_parts) or any(
            _differs(v, got["parts"].get(k)) for k, v in pc_parts.items()
        ):
            bad.append(t)
    return bad


def main(argv: list[str]) -> int:
    cmd = argv[1]
    if cmd == "fingerprint":
        db = sqlite3.connect(f"file:{argv[2]}?mode=ro", uri=True)
        cut = None
        if "--deep-from" in argv:
            cut = json.loads(argv[argv.index("--deep-from") + 1])
        print(json.dumps(fingerprint(db, cut, "--deep" in argv)))
        return 0
    if cmd == "deep-from":
        print(json.dumps(deep_from(sqlite3.connect(f"file:{argv[2]}?mode=ro", uri=True))))
        return 0
    if cmd == "delta":
        srv = None
        if argv[3] != "-":
            with open(argv[3], encoding="utf-8") as f:
                srv = json.load(f)
        res = delta(argv[2], srv, argv[4])
        print(json.dumps(res))
        return 0
    if cmd == "apply":
        res = apply(argv[2], argv[3])
        print(json.dumps(res))
        return 3 if res["mismatch"] else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
