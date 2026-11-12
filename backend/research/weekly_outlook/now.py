import polars as pl, numpy as np, sys
SP=sys.argv[1]
pl.Config.set_tbl_rows(40); pl.Config.set_tbl_cols(20); pl.Config.set_tbl_width_chars(200)
f=pl.read_parquet(f"{SP}/feats.parquet")
print(f.columns[:5], f["date"].max())
e=f.filter(pl.col("eligible")&~pl.col("market_halt"))
g=e.group_by("date").agg(
  n=pl.len(),
  above50=(pl.col("sma_50_dist")>0).mean(), above200=(pl.col("sma_200_dist")>0).mean(),
  up=(pl.col("ret_1")>0).mean(), ret_ew=pl.col("ret_1").median(),
  newhigh=(pl.col("dist_high_52w")>=-0.001).mean(),
  limit_up=(pl.col("queue_state")=="buy_queue").mean(), sellq=(pl.col("queue_state")=="sell_queue").mean(),
  flow=pl.col("mkt_ind_net_flow_ratio").first(), flowz=pl.col("mkt_ind_net_flow_z").first(),
  ibp=pl.col("ind_buy_power").median(),
  rsi=pl.col("rsi_14").median(), ret20=pl.col("ret_20").median(),
).sort("date")
print(g.tail(15))
print("last-year percentiles of today's value:")
t=g.tail(1).to_dicts()[0]; y=g.tail(245)
for c in ["above50","above200","newhigh","limit_up","sellq","flow","ibp","rsi","ret20"]:
    print(c, round(t[c],4), "pctile in last yr", round((y[c]<=t[c]).mean(),2), "all-time", round((g.drop_nulls(c)[c]<=t[c]).mean(),2))
