import polars as pl, numpy as np, sys
from tmon.core.db import session_scope
from tmon.features.store import load_benchmark_inputs
SP=sys.argv[1]
with session_scope() as s: idx,_=load_benchmark_inputs(s)
ew=idx.filter(pl.col("index_code")=="67130298613737946").select("date","close").sort("date")
c=ew["close"].to_numpy(); n=len(c); mdd=np.full(n,np.nan)
for i in range(n-20): mdd[i]=(c[i+1:i+21]/c[i]-1).min()
ew=ew.with_columns(f5=pl.col("close").shift(-5)/pl.col("close")-1,f20=pl.col("close").shift(-20)/pl.col("close")-1,mdd=pl.Series(mdd))
f=pl.read_parquet(f"{SP}/feats.parquet").filter(pl.col("eligible")&~pl.col("market_halt"))
b=f.group_by("date").agg(a200=(pl.col("sma_200_dist")>0).mean(),a50=(pl.col("sma_50_dist")>0).mean(),n=pl.len()).filter(pl.col("n")>300)
d=b.join(ew,on="date").drop_nulls(["f5","f20","mdd"]).sort("date")
print(len(d),d["date"].min())
for name,cond in [("all",pl.lit(True)),("a200>=0.95",pl.col("a200")>=0.95),("a200>=0.9",pl.col("a200")>=0.9),("a200<0.5",pl.col("a200")<0.5),("a50>=0.85",pl.col("a50")>=0.85),("a50>=0.85&a200>=.95",(pl.col("a50")>=0.85)&(pl.col("a200")>=0.95))]:
    s=d.filter(cond)
    if len(s)==0: print(name,0); continue
    print(f"{name:22s} n={len(s):4d} f5 {s['f5'].mean()*100:5.2f}% up {((s['f5']>0).mean())*100:3.0f}% p10 {s['f5'].quantile(.1)*100:6.2f}% | f20 {s['f20'].mean()*100:5.1f}% | P(dd>10%/20d) {(s['mdd']<-0.1).mean()*100:3.0f}%  P(dd>5%) {(s['mdd']<-0.05).mean()*100:3.0f}%")
