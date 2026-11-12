# Weekly outlook research (2026-11-13)

One-off research scripts behind `docs/reports/weekly-outlook-2026-11.md`. Not part of the engine:
no production code imports them. Run from `backend/` with
`TMON_DATABASE_URL=sqlite:///D:/Data/Tmon/data/tmon-live.sqlite3` and
`TMON_OBJECT_STORE=file TMON_OBJECT_STORE_DIR=data/objects`; every script takes a scratch directory
as its first argument (`SP`), where `cache.py` writes `feats.parquet`/`adj.parquet`.

Order: `cache.py` -> `wf.py` (panel.parquet) -> `wf2.py` (walk-forward LightGBM) -> `net.py`
(net of cost), `leak.py`, `shift.py`, `imp.py` (leak and ablation checks) -> `regime.py`, `ext.py`,
`br.py`, `now.py` (market state) -> `rng.py` (per-symbol range calibration) -> `fc.py`, `final.py`
(today's outlook, saved as `outlook-2026-11-11.json`).
