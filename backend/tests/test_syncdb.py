"""deploy/syncdb.py: ship only the days that differ, refuse a delta when it is not safe."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "syncdb", Path(__file__).resolve().parents[2] / "deploy" / "syncdb.py"
)
assert _spec and _spec.loader
sd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sd)

SCHEMA = """
create table prices_daily (instrument_id int, date date, close real, volume real, high real,
  source_url text, fetched_at text, primary key (instrument_id, date));
create table features (instrument_id int, date date, feature_set_version text, "values" text,
  primary key (instrument_id, date, feature_set_version));
create table instruments (id int primary key, symbol text, fetched_at text);
create table alembic_version (version_num text);
"""


def _make(path: Path, days: int, symbols: str = "ab") -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    db.execute("insert into alembic_version values ('x')")
    for i, s in enumerate(symbols):
        db.execute("insert into instruments values (?,?,?)", (i, s, "t0"))
    for d in range(days):
        day = f"2026-10-{d + 1:02d}"
        for i in range(2):
            db.execute(
                "insert into prices_daily values (?,?,?,?,?,?,?)",
                (i, day, 100.0 + d, 10.0, 101.0, "u", "t0"),
            )
            db.execute("insert into features values (?,?,?,?)", (i, day, "v1", "{}"))
    db.commit()
    return db


def _run(pc: Path, srv: Path, out: Path) -> dict:
    cut = sd.deep_from(sqlite3.connect(pc))
    srv_fp = sd.fingerprint(sqlite3.connect(srv), cut)
    return sd.delta(str(pc), json.loads(json.dumps(srv_fp)), str(out))


def test_a_new_day_and_a_revised_day_are_shipped_and_nothing_else(tmp_path: Path) -> None:
    _make(tmp_path / "pc.db", 40)
    _make(tmp_path / "srv.db", 40)
    pc_db = sqlite3.connect(tmp_path / "pc.db")
    pc_db.execute("insert into prices_daily values (0,'2026-11-01',150,10,151,'u','t1')")
    pc_db.execute("insert into prices_daily values (1,'2026-11-01',150,10,151,'u','t1')")
    pc_db.execute(
        "update prices_daily set close = 999 where date = '2026-10-40'"
    ) if False else None
    pc_db.execute("update prices_daily set close = 999 where date = '2026-10-39'")
    pc_db.commit()
    res = _run(tmp_path / "pc.db", tmp_path / "srv.db", tmp_path / "delta.db")
    assert res["full"] is False
    assert res["parts"]["prices_daily"] == ["2026-10-39", "2026-11-01"]
    assert "features" not in res["parts"] and res["whole"] == []
    assert res["rows"] == 4
    out = sd.apply(str(tmp_path / "srv.db"), str(tmp_path / "delta.db"))
    assert out["mismatch"] == []
    got = sqlite3.connect(tmp_path / "srv.db")
    assert got.execute("select count(*) from prices_daily").fetchone()[0] == 82
    assert (
        got.execute("select close from prices_daily where date='2026-10-39'").fetchone()[0] == 999
    )


def test_a_day_the_pc_no_longer_has_is_removed_from_the_server(tmp_path: Path) -> None:
    _make(tmp_path / "pc.db", 10)
    _make(tmp_path / "srv.db", 10)
    sqlite3.connect(tmp_path / "srv.db").execute(
        "insert into prices_daily values (0,'2026-12-01',1,1,1,'u','t')"
    ).connection.commit()
    res = _run(tmp_path / "pc.db", tmp_path / "srv.db", tmp_path / "delta.db")
    assert res["drop"] == {"prices_daily": ["2026-12-01"]}
    assert sd.apply(str(tmp_path / "srv.db"), str(tmp_path / "delta.db"))["mismatch"] == []
    assert (
        sqlite3.connect(tmp_path / "srv.db")
        .execute("select count(*) from prices_daily where date='2026-12-01'")
        .fetchone()[0]
        == 0
    )


def test_server_features_older_than_the_window_are_pruned(tmp_path: Path) -> None:
    _make(tmp_path / "pc.db", 5)
    srv = _make(tmp_path / "srv.db", 5)
    for d in range(70):  # the PC keeps 5 days, the server also holds 70 older ones
        srv.execute(
            "insert into features values (0,?,'v1','{}')",
            (f"2026-07-{d + 1:02d}" if d < 31 else f"2026-08-{d - 30:02d}",),
        )
    srv.commit()
    res = _run(tmp_path / "pc.db", tmp_path / "srv.db", tmp_path / "delta.db")
    assert not res["full"]
    sd.apply(str(tmp_path / "srv.db"), str(tmp_path / "delta.db"))
    assert (
        sqlite3.connect(tmp_path / "srv.db")
        .execute("select count(distinct date) from features")
        .fetchone()[0]
        == 5
    )


def test_whole_tables_compare_content_not_fetch_times(tmp_path: Path) -> None:
    pc = _make(tmp_path / "pc.db", 3)
    _make(tmp_path / "srv.db", 3)
    pc.execute("update instruments set fetched_at = 'later'")  # only provenance moved
    pc.commit()
    assert _run(tmp_path / "pc.db", tmp_path / "srv.db", tmp_path / "d1.db")["whole"] == []
    pc.execute("update instruments set symbol = 'z' where id = 0")
    pc.commit()
    res = _run(tmp_path / "pc.db", tmp_path / "srv.db", tmp_path / "d2.db")
    assert res["whole"] == ["instruments"]
    assert sd.apply(str(tmp_path / "srv.db"), str(tmp_path / "d2.db"))["mismatch"] == []
    assert (
        sqlite3.connect(tmp_path / "srv.db")
        .execute("select symbol from instruments where id=0")
        .fetchone()[0]
        == "z"
    )


@pytest.mark.parametrize("case", ["no_server", "other_layout", "too_much"])
def test_full_copy_is_chosen_when_a_delta_is_not_safe(tmp_path: Path, case: str) -> None:
    _make(tmp_path / "pc.db", 10)
    out = tmp_path / "delta.db"
    if case == "no_server":
        assert sd.delta(str(tmp_path / "pc.db"), None, str(out))["full"] is True
        return
    srv = _make(tmp_path / "srv.db", 10 if case == "other_layout" else 1)
    if case == "other_layout":
        srv.execute("alter table instruments add column extra text")
        srv.commit()
    res = _run(tmp_path / "pc.db", tmp_path / "srv.db", out)
    assert res["full"] is True and res["reason"]


def test_urls_are_dropped_from_day_tables_and_shortened_elsewhere(tmp_path: Path) -> None:
    pc = _make(tmp_path / "pc.db", 10)
    _make(tmp_path / "srv.db", 10)
    long = "https://x/y?t=ClosingPrices&a=" + "1," * 400
    pc.execute("insert into prices_daily values (0,'2026-11-01',1,1,1,?,'t')", (long,))
    pc.execute("create table macro_series (k int primary key, source_url text)")
    pc.execute("insert into macro_series values (1, ?)", (long,))
    pc.commit()
    sd.slim(pc)
    assert pc.execute("select count(source_url) from prices_daily").fetchone()[0] == 0
    url = pc.execute("select source_url from macro_series").fetchone()[0]
    assert url.endswith("&a=...") and len(url) < 60


def test_pc_only_tables_are_emptied_and_never_compared(tmp_path: Path) -> None:
    pc = _make(tmp_path / "pc.db", 5)
    srv = _make(tmp_path / "srv.db", 5)
    for db in (pc, srv):
        db.execute("create table financial_statements (id int primary key, body text)")
    pc.execute("insert into financial_statements values (1, 'big')")
    pc.commit()
    srv.commit()
    res = _run(tmp_path / "pc.db", tmp_path / "srv.db", tmp_path / "delta.db")
    assert not res["full"] and res["whole"] == [] and res["parts"] == {}
    sd.slim(pc)
    assert pc.execute("select count(*) from financial_statements").fetchone()[0] == 0


def test_fund_navs_keep_sixty_days_below_each_funds_newest(tmp_path: Path) -> None:
    pc = _make(tmp_path / "pc.db", 3)
    srv = _make(tmp_path / "srv.db", 3)
    for db in (pc, srv):
        db.execute(
            "create table fund_nav_history (reg_no text, date date, instrument_id int,"
            " cancel_nav real, units real, source_url text, fetched_at text,"
            " primary key (reg_no, date))"
        )
    days = ["2026-01-01", "2026-08-05", "2026-09-15", "2026-10-01"]
    for d in days:  # fund a is current; fund b stopped in August
        pc.execute("insert into fund_nav_history values ('a',?,1,100,5,'u','t')", (d,))
    pc.execute("insert into fund_nav_history values ('b','2026-07-01',2,9,9,'u','t')")
    pc.execute("insert into fund_nav_history values ('b','2026-04-01',2,9,9,'u','t')")
    pc.commit()
    srv.commit()
    res = _run(tmp_path / "pc.db", tmp_path / "srv.db", tmp_path / "delta.db")
    assert res["parts"]["fund_nav_history"] == [
        "2026-07-01",
        "2026-08-05",
        "2026-09-15",
        "2026-10-01",
    ]
    assert sd.apply(str(tmp_path / "srv.db"), str(tmp_path / "delta.db"))["mismatch"] == []
    got = srv.execute("select reg_no, date from fund_nav_history order by 1, 2").fetchall()
    assert got == [
        ("a", "2026-08-05"),
        ("a", "2026-09-15"),
        ("a", "2026-10-01"),
        ("b", "2026-07-01"),
    ]
    sd.slim(pc)  # the full copy keeps the same rows
    assert pc.execute("select reg_no, date from fund_nav_history order by 1, 2").fetchall() == got


def _with_state(path: Path, alerts: int, trades: list[tuple[int, str]]) -> sqlite3.Connection:
    db = _make(path, 3)
    db.executescript(
        """create table portfolio_alerts (id integer primary key, text text);
           create table intraday_snapshots (id integer primary key, ts text);
           create table portfolio_trades (id integer primary key, note text, fetched_at text);"""
    )
    for i in range(alerts):
        db.execute("insert into portfolio_alerts values (?, 'a')", (i,))
        db.execute("insert into intraday_snapshots values (?, 't')", (i,))
    for i, note in trades:
        db.execute("insert into portfolio_trades values (?, ?, 't0')", (i, note))
    db.commit()
    return db


def test_server_owned_tables_are_invisible_to_the_comparison(tmp_path: Path) -> None:
    _with_state(tmp_path / "pc.db", 0, [])
    _with_state(tmp_path / "srv.db", 500, [])  # the monitor wrote these on the server
    res = _run(tmp_path / "pc.db", tmp_path / "srv.db", tmp_path / "delta.db")
    assert res["full"] is False and res["whole"] == [] and res["parts"] == {}
    sd.apply(str(tmp_path / "srv.db"), str(tmp_path / "delta.db"))
    got = sqlite3.connect(tmp_path / "srv.db")
    assert got.execute("select count(*) from portfolio_alerts").fetchone()[0] == 500
    assert got.execute("select count(*) from intraday_snapshots").fetchone()[0] == 500


def test_pc_portfolio_edit_reaches_the_server_until_the_server_edits_it_too(
    tmp_path: Path,
) -> None:
    _with_state(tmp_path / "pc.db", 0, [(1, "buy")])
    _with_state(tmp_path / "srv.db", 0, [])
    # first sync (no record yet): the PC copy replaces, as it always has
    res = _run(tmp_path / "pc.db", tmp_path / "srv.db", tmp_path / "d1.db")
    assert res["whole"] == ["portfolio_trades"]
    out = sd.apply(str(tmp_path / "srv.db"), str(tmp_path / "d1.db"))
    assert out["mismatch"] == [] and out["kept_server_edits"] == []
    srv = sqlite3.connect(tmp_path / "srv.db")
    assert srv.execute("select count(*) from portfolio_trades").fetchone()[0] == 1
    # the owner adds a trade on the server; meanwhile the PC changed its own copy
    srv.execute("insert into portfolio_trades values (2, 'server', 't')")
    srv.commit()
    pc = sqlite3.connect(tmp_path / "pc.db")
    pc.execute("insert into portfolio_trades values (3, 'pc', 't')")
    pc.commit()
    res = _run(tmp_path / "pc.db", tmp_path / "srv.db", tmp_path / "d2.db")
    out = sd.apply(str(tmp_path / "srv.db"), str(tmp_path / "d2.db"))
    assert out["kept_server_edits"] == ["portfolio_trades"] and out["mismatch"] == []
    notes = [r[0] for r in srv.execute("select note from portfolio_trades order by id")]
    assert notes == ["buy", "server"]  # the server's edit survived


def test_full_copy_carries_server_owned_rows_and_server_edits(tmp_path: Path) -> None:
    _with_state(tmp_path / "pc.db", 0, [(1, "buy")])
    _with_state(tmp_path / "srv.db", 40, [])
    sd.apply(
        str(tmp_path / "srv.db"),
        _delta_path(tmp_path, tmp_path / "pc.db", tmp_path / "srv.db"),
    )
    srv = sqlite3.connect(tmp_path / "srv.db")
    srv.execute("insert into portfolio_trades values (2, 'server', 't')")
    srv.commit()
    res = sd.preserve(str(tmp_path / "srv.db"), str(tmp_path / "pc.db"))
    assert res["kept_server_edits"] == ["portfolio_trades"]
    new = sqlite3.connect(tmp_path / "pc.db")
    assert new.execute("select count(*) from portfolio_alerts").fetchone()[0] == 40
    assert [r[0] for r in new.execute("select note from portfolio_trades order by id")] == [
        "buy",
        "server",
    ]


def _delta_path(tmp: Path, pc: Path, srv: Path) -> str:
    _run(pc, srv, tmp / "seed.db")
    return str(tmp / "seed.db")


def test_the_time_of_day_slices_travel_by_day_and_a_refetched_day_is_noticed(
    tmp_path: Path,
) -> None:
    ddl = (
        "create table intraday_profile_daily (instrument_id int, date date, window int, mid real,"
        " ask_min real, bid_max real, secs real, source_url text, fetched_at text,"
        " primary key (instrument_id, date, window));"
    )
    for name in ("pc", "srv"):
        db = _make(tmp_path / f"{name}.db", 3)
        db.executescript(ddl)
        for d in ("2026-10-01", "2026-10-02"):
            for w in range(3):
                db.execute(
                    "insert into intraday_profile_daily values (0,?,?,100,101,99,60,'u','t0')",
                    (d, w),
                )
        db.commit()
    pc = sqlite3.connect(tmp_path / "pc.db")
    # same date and same row count, different prices: only the sums can tell
    pc.execute("update intraday_profile_daily set ask_min = 105 where date = '2026-10-02'")
    pc.execute(
        "insert into intraday_profile_daily values (0,'2026-10-03',0,100,101,99,60,'u','t1')"
    )
    pc.commit()
    res = _run(tmp_path / "pc.db", tmp_path / "srv.db", tmp_path / "delta.db")
    assert res["full"] is False
    assert res["parts"]["intraday_profile_daily"] == ["2026-10-02", "2026-10-03"]
    out = sd.apply(str(tmp_path / "srv.db"), str(tmp_path / "delta.db"))
    assert out["mismatch"] == []
    got = sqlite3.connect(tmp_path / "srv.db")
    assert got.execute("select count(*) from intraday_profile_daily").fetchone()[0] == 7
