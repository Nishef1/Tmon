import sys, numpy as np, polars as pl, pandas as pd
from scipy.stats import spearmanr
SP=sys.argv[1]
a=pl.read_parquet(f"{SP}/adj.parquet"); print(a.columns)
col=[c for c in a.columns if "adj" in c][0]
a=a.sort("instrument_id","date").with_columns(
  e1=pl.col(col).shift(-1).over("instrument_id"), e2=pl.col(col).shift(-2).over("instrument_id"), e3=pl.col(col).shift(-3).over("instrument_id"),
  x6=pl.col(col).shift(-6).over("instrument_id"), x7=pl.col(col).shift(-7).over("instrument_id"), x8=pl.col(col).shift(-8).over("instrument_id"), x11=pl.col(col).shift(-11).over("instrument_id"))
a=a.with_columns(r_e1=pl.col("x6")/pl.col("e1")-1, r_e2=pl.col("x7")/pl.col("e2")-1, r_e3=pl.col("x8")/pl.col("e3")-1, r_e1_10=pl.col("x11")/pl.col("e1")-1, r_0_1=pl.col("e1")/pl.col(col)-1)
a=a.select("instrument_id","date","r_e1","r_e2","r_e3","r_0_1").to_pandas(); a["date"]=pd.to_datetime(a["date"])
r=pd.read_parquet(f"{SP}/wf_out.parquet"); r["date"]=pd.to_datetime(r["date"]); r=r.merge(a,on=["instrument_id","date"])
for lab in ["r_0_1","r_e1","r_e2","r_e3"]:
    for col in ["p_v2","p_lgb"]:
        ics=[spearmanr(g[col],g[lab],nan_policy="omit")[0] for _,g in r.groupby("date") if len(g)>40]
        print(lab,col,round(np.nanmean(ics),4))
