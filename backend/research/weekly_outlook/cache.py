import polars as pl, time
from tmon.core.db import session_scope
from tmon.features.store import load_benchmark_inputs, load_inputs
from tmon.features.builder import build_features
from tmon.domain.rules import RuleBook
from tmon.backtest.signal_decay import adjusted_close
t=time.time()
with session_scope() as s:
    prices, clients, sectors = load_inputs(s)
    rules = RuleBook.from_session(s)
feats = build_features(prices, clients, rules, sectors=sectors)
adj = adjusted_close(prices)
import sys
SP=sys.argv[1]
feats.write_parquet(SP+"/feats.parquet"); adj.write_parquet(SP+"/adj.parquet")
print(feats.shape, adj.shape, time.time()-t)
print(feats.columns)
