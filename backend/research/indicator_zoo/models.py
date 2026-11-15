"""Do the zoo indicators help when combined? Walk-forward LightGBM by calendar year on the panel
of study.py (same scratch dir, argv[1]): the four live signals alone, the four plus every zoo
indicator, the four plus only those that passed the 'adds' test, and the plain equal-weight
composite of the four. Each test year is predicted by a model trained only on rows whose outcome
was known 90 days before the year began. Judged per day by rank IC and the top-decile excess.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

SP = Path(sys.argv[1])
C = pl.col
BASE = ["b_power", "b_rv20", "b_dist52", "b_mom121"]
H = (5, 20, 60)


def main() -> None:
    d = pl.read_parquet(SP / "zoo_panel.parquet")
    info = json.loads((SP / "zoo_panel.json").read_text())["info"]
    sc = json.loads((SP / "zoo_scores.json").read_text())["signals"]
    zoo = list(info)
    adds = {hh: [k for k in zoo if sc[k]["verdict"].get(str(hh), {}).get("adds")] for hh in H}
    feats = zoo + BASE
    d = d.with_columns(*[((C(f).rank() - 0.5) / C(f).count()).over("date").alias(f) for f in feats])
    tested = d.filter(C("year") >= 2010)["date"].sort()
    split = tested[tested.len() // 2]  # halves of the out-of-sample years
    out: dict = {"split": str(split), "adds": adds, "h": {}}
    for hh in H:
        y = f"x{hh}"
        dh = d.filter(C(y).is_not_null()).with_columns(
            ((C(y).rank() - 0.5) / C(y).count()).over("date").alias("ry"),
            eq=pl.mean_horizontal([C(b) for b in BASE]),
        )
        sets = {"base4": BASE, "base4+zoo": feats, "base4+adds": BASE + adds[hh]}
        preds = {k: [] for k in sets}
        eq = []
        for yr in range(2010, int(dh["year"].max()) + 1):
            cut = dt.date(yr, 1, 1) - dt.timedelta(days=90)
            tr = dh.filter(C("date") < cut)
            te = dh.filter(C("year") == yr)
            if tr.height < 20000 or te.height == 0:
                continue
            eq.append(te.select("date", y, s=C("eq")))
            for name, cols in sets.items():
                if not cols:
                    continue
                m = lgb.LGBMRegressor(
                    n_estimators=300, learning_rate=0.03, num_leaves=31, min_child_samples=300,
                    subsample=0.7, subsample_freq=1, colsample_bytree=0.7, verbose=-1,
                )  # fmt: skip
                m.fit(tr.select(cols).to_numpy(), tr["ry"].to_numpy())
                preds[name].append(
                    te.select("date", y).with_columns(
                        s=pl.Series(m.predict(te.select(cols).to_numpy()))
                    )
                )
            print(f"h={hh} year {yr} done", flush=True)
        res = {}
        for name, parts in {"equal4": eq, **preds}.items():
            if not parts:
                continue
            p = pl.concat(parts)
            g = (
                p.group_by("date")
                .agg(
                    ic=pl.corr("s", y, method="spearman"),
                    top=C(y).filter(C("s") >= C("s").quantile(0.9)).mean(),
                )
                .drop_nulls()
                .sort("date")
            )
            a, b = g.filter(C("date") < split), g.filter(C("date") >= split)
            ov = max(1.0, hh / 5)
            res[name] = {
                "ic": float(g["ic"].mean()),
                "t": float(g["ic"].mean() / g["ic"].std() * np.sqrt(g.height / ov)),
                "ic_a": float(a["ic"].mean()) if a.height else None,
                "ic_b": float(b["ic"].mean()),
                "top": float(g["top"].mean()),
                "top_a": float(a["top"].mean()) if a.height else None,
                "top_b": float(b["top"].mean()),
                "days": g.height,
            }
        out["h"][hh] = res
        print(json.dumps({hh: res}, indent=1))
    (SP / "zoo_models.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
