import polars as pl, numpy as np, lightgbm as lgb, time, sys
from tmon.backtest.signal_decay import forward_returns, SIGNALS
from tmon.features.builder import TECHNICAL_COLUMNS, BOARD_COLUMNS, MARKET_COLUMNS, KEYS
from tmon.core.engine_config import get_engine_config
import sys
SP=sys.argv[1]
cfg=get_engine_config()
feats=pl.read_parquet(SP+"/feats.parquet"); adj=pl.read_parquet(SP+"/adj.parquet")
H=5
fw=forward_returns(adj,(H,)).select(*KEYS,"mom_12_1",f"fwd_{H}")
d=feats.filter((~pl.col("market_halt"))&pl.col("eligible")&~pl.col("queue_state").is_in(cfg.universe.exclude_queue_states)).join(fw,on=list(KEYS),how="left")
d=d.with_columns(pl.col("median_value_20").rank("ordinal",descending=True).over("date").alias("liq_rank")).filter(pl.col("liq_rank")<=250)
FEATS=[c for c in TECHNICAL_COLUMNS+BOARD_COLUMNS if c in d.columns]+["mom_12_1"]
MKT=["breadth","mkt_ret_ew_5d","mkt_ret_ew_20d","mkt_ind_net_flow_z"]
# cross-sectional percentile of each feature per day
d=d.with_columns([((pl.col(c).rank("average").over("date")-0.5)/pl.col(c).count().over("date")).alias("x_"+c) for c in FEATS])
d=d.with_columns(
    (pl.col(f"fwd_{H}")-pl.col(f"fwd_{H}").median().over("date")).alias("y_ex"),
    ((pl.col(f"fwd_{H}").rank("average").over("date")-0.5)/pl.col(f"fwd_{H}").count().over("date")).alias("y_rk"))
# v2 composite for comparison
d=d.with_columns(*[((pl.col("x_"+s) if sg>0 else 1-pl.col("x_"+s))).alias("c_"+s) for s,sg in SIGNALS.items() if "x_"+s in d.columns])
d=d.with_columns(pl.mean_horizontal([c for c in d.columns if c.startswith("c_")]).alias("p_v2"))
print("universe rows",d.shape, d["date"].min(), d["date"].max())
print(d.group_by(pl.col("date").dt.year()).agg(pl.len(), pl.col("y_ex").count().alias("lab"), pl.col("x_ind_buy_power").count().alias("bp")).sort("date").tail(20))
d.write_parquet(SP+"/panel.parquet")
