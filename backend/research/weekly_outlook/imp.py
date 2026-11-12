import sys, numpy as np, polars as pl, pandas as pd, lightgbm as lgb
from scipy.stats import spearmanr
SP=sys.argv[1]
p=pl.read_parquet(f"{SP}/panel.parquet").filter(pl.col("date")>=pl.date(2019,6,1)).drop_nulls(["y_rk","fwd_5"]).to_pandas()
p["date"]=pd.to_datetime(p["date"])
X=[c for c in p.columns if c.startswith("x_")]
tr=p[p.date<"2024-12-20"]; te=p[(p.date>="2025-01-01")&(p.date<"2026-01-01")]
# single-feature mean daily IC on test
res={}
for c in X:
    ics=[spearmanr(g[c],g.fwd_5,nan_policy="omit")[0] for _,g in te.groupby("date") if len(g)>40]
    res[c]=np.nanmean(ics)
s=pd.Series(res).sort_values(); print("single IC lowest/highest"); print(pd.concat([s.head(8),s.tail(12)]).round(3).to_string())
params=dict(objective="regression",learning_rate=0.03,num_leaves=15,min_data_in_leaf=500,feature_fraction=0.6,bagging_fraction=0.7,bagging_freq=1,lambda_l2=50,verbose=-1,num_threads=8,seed=7)
def run(cols,label):
    m=lgb.train(params,lgb.Dataset(tr[cols].values.astype("float32"),tr.y_rk.values),250)
    t=te.copy(); t["s"]=m.predict(te[cols].values.astype("float32"))
    ics=[spearmanr(g.s,g.fwd_5)[0] for _,g in t.groupby("date") if len(g)>40]
    print(label,"IC",round(np.mean(ics),4)); return m
m=run(X,"all")
imp=pd.Series(m.feature_importance("gain"),index=X).sort_values(ascending=False); print((imp/imp.sum()).head(15).round(3).to_string())
tech=[c for c in X if c not in ("x_ind_buy_power","x_ind_net_flow_ratio","x_ind_net_flow_z","x_inst_to_ind","x_smart_money_flag","x_queue_code","x_days_in_queue","x_rel_volume","x_vol_to_base","x_last_close_gap","x_intraday_range_pos","x_ret_1_norm","x_vwap_gap")]
run(tech,"technical only")
run([c for c in X if c not in ("x_queue_code","x_days_in_queue","x_last_close_gap","x_intraday_range_pos","x_ret_1_norm","x_vwap_gap","x_rel_volume","x_vol_to_base")],"no board/volume")
