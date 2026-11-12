import sys, json, numpy as np, polars as pl, pandas as pd
from tmon.core.db import session_scope
from tmon.features.store import load_benchmark_inputs
from tmon.storage.models import Instrument
from sqlalchemy import select
SP=sys.argv[1]
with session_scope() as s:
    idx,_=load_benchmark_inputs(s); names={i.id:(i.symbol_fa,i.name_fa) for i in s.scalars(select(Instrument))}
ew=idx.filter(pl.col("index_code")=="67130298613737946").select("date","close").sort("date")
ew=ew.with_columns(f5=pl.col("close").shift(-5)/pl.col("close")-1)
f=pl.read_parquet(f"{SP}/feats.parquet").filter(pl.col("eligible")&~pl.col("market_halt"))
b=f.group_by("date").agg(a200=(pl.col("sma_200_dist")>0).mean(),a50=(pl.col("sma_50_dist")>0).mean(),n=pl.len()).filter(pl.col("n")>300)
d=b.join(ew,on="date").drop_nulls("f5")
for name,cond in [("all",pl.lit(True)),("breadth-confirmed (a50>=.85,a200>=.95)",(pl.col("a50")>=0.85)&(pl.col("a200")>=0.95))]:
    s=d.filter(cond)["f5"]
    print(name,len(s),"quantiles 5/25/50/75/95:",[round(float(s.quantile(q))*100,2) for q in (.05,.25,.5,.75,.95)],"P(>0)",round(float((s>0).mean()),2),"P(<-5%)",round(float((s<-0.05).mean()),3),"P(<-3%)",round(float((s<-0.03).mean()),3))
# per symbol
t=pd.read_parquet(f"{SP}/today.parquet")
adj=pl.read_parquet(f"{SP}/adj.parquet").filter(pl.col("date")==pl.date(2026,11,11)).select("instrument_id","adj_close").to_pandas()
t=t.merge(adj,on="instrument_id",how="left")
# z quantiles from last 500 days pooled
p=pl.read_parquet(f"{SP}/panel.parquet").filter(pl.col("date")>=pl.date(2024,11,1)).select("instrument_id","date","fwd_5")
ff=pl.read_parquet(f"{SP}/feats.parquet").select("instrument_id","date","ret_1").sort("instrument_id","date").with_columns(sd60=pl.col("ret_1").rolling_std(60).over("instrument_id"))
z=p.join(ff.select("instrument_id","date","sd60"),on=["instrument_id","date"]).drop_nulls().filter(pl.col("sd60")>0).with_columns(z=pl.col("fwd_5")/(pl.col("sd60")*np.sqrt(5)))
qs=[.1,.5,.9]; zq=[float(z["z"].quantile(q)) for q in qs]; print("zq (10/50/90)",[round(x,2) for x in zq])
rows=[]
for r in t.sort_values("score",ascending=False).itertuples():
    sy,nm=names.get(r.instrument_id,("?","?"))
    w=r.sd60*np.sqrt(5)
    rows.append(dict(id=int(r.instrument_id),symbol=sy,name=nm,score=round(float(r.score),3),lgb=round(float(r.r_p_lgb),3),v2=round(float(r.r_p_v2),3),sd_week=round(float(w),4),lo=round(zq[0]*w,4),mid=round(zq[1]*w,4),hi=round(zq[2]*w,4),median_value=float(r.median_value_20)))
json.dump(rows,open(f"{SP}/outlook.json","w"),ensure_ascii=False)
pd.set_option("display.width",200)
df=pd.DataFrame(rows)
print(df.head(12)[["symbol","score","lgb","v2","lo","mid","hi"]].to_string())
print(df.tail(8)[["symbol","score","lgb","v2","lo","mid","hi"]].to_string())
print("median weekly sd across symbols",df.sd_week.median())
