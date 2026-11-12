import polars as pl, numpy as np, sys
SP=sys.argv[1]
p=pl.read_parquet(f"{SP}/panel.parquet").filter(pl.col("date")>=pl.date(2020,1,1))
f=pl.read_parquet(f"{SP}/feats.parquet").select("instrument_id","date","ret_1")
f=f.sort("instrument_id","date").with_columns(sd60=pl.col("ret_1").rolling_std(60).over("instrument_id"))
d=p.select("instrument_id","date","fwd_5","mkt_ret_ew_20d").join(f.select("instrument_id","date","sd60"),on=["instrument_id","date"]).drop_nulls(["fwd_5","sd60"]).filter(pl.col("sd60")>0)
d=d.with_columns(z=pl.col("fwd_5")/(pl.col("sd60")*np.sqrt(5)))
qs=[.05,.1,.25,.5,.75,.9,.95]
tr=d.filter(pl.col("date")<pl.date(2024,6,1)); te=d.filter(pl.col("date")>=pl.date(2024,6,15))
zq={q:float(tr["z"].quantile(q)) for q in qs}
print("pooled z quantiles (train)",{q:round(v,2) for q,v in zq.items()})
print("OOS coverage (should equal nominal):")
for q in qs: print(q, round(float((te["z"]<=zq[q]).mean()),3))
# by regime in test: strong ew20 
for name,cond in [("ew20>3%",pl.col("mkt_ret_ew_20d")>0.03),("ew20<=3%",pl.col("mkt_ret_ew_20d")<=0.03)]:
    s=te.filter(cond); print(name,len(s),[round(float((s["z"]<=zq[q]).mean()),3) for q in qs])
print("train z mean",tr["z"].mean(),"te z mean",te["z"].mean())
np.save(f"{SP}/zq.npy",np.array([zq[q] for q in qs]))
print("--- rolling recalibration: quantiles from the previous 500 days, tested month by month 2024-07..")
import pandas as pd
dd=d.to_pandas(); dd["date"]=pd.to_datetime(dd["date"])
hits={q:[] for q in qs}
for a in pd.date_range("2024-07-01","2026-10-01",freq="MS"):
    b=a+pd.offsets.MonthBegin(1)
    t=dd[(dd.date<a-pd.Timedelta(days=10))&(dd.date>=a-pd.Timedelta(days=730))]
    s=dd[(dd.date>=a)&(dd.date<b)]
    if len(s)==0: continue
    for q in qs: hits[q].append((s.z<=t.z.quantile(q)).values)
for q in qs: print(q, round(float(np.concatenate(hits[q]).mean()),3))
