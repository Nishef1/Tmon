import polars as pl, numpy as np
from tmon.core.db import session_scope
from tmon.features.store import load_benchmark_inputs
with session_scope() as s:
    idx, rf = load_benchmark_inputs(s)
CODES={"tedpix":"32097828799138957","ew":"67130298613737946"}
def regime_frame(code):
    d=idx.filter(pl.col("index_code")==code).select("date","close").sort("date")
    d=d.with_columns(
        sma50=pl.col("close").rolling_mean(50), sma200=pl.col("close").rolling_mean(200),
        r60=pl.col("close")/pl.col("close").shift(60)-1,
        r20=pl.col("close")/pl.col("close").shift(20)-1,
        dd=pl.col("close")/pl.col("close").rolling_max(252)-1,
        vol20=(pl.col("close")/pl.col("close").shift(1)-1).rolling_std(20)*np.sqrt(245),
        f5=pl.col("close").shift(-5)/pl.col("close")-1,
        f20=pl.col("close").shift(-20)/pl.col("close")-1,
    )
    bull=(pl.col("close")>pl.col("sma200"))&(pl.col("sma50")>pl.col("sma200"))&(pl.col("r60")>0)
    bear=(pl.col("close")<pl.col("sma200"))&(pl.col("sma50")<pl.col("sma200"))
    return d.with_columns(regime=pl.when(bull).then(pl.lit("bull")).when(bear).then(pl.lit("bear")).otherwise(pl.lit("range")))
for name,code in CODES.items():
    d=regime_frame(code).drop_nulls(["sma200","r60"])
    print("\n==",name,d["date"].min(),d["date"].max(),len(d))
    ann=lambda x: (1+x)**(245/5)-1
    g=d.drop_nulls(["f5","f20"]).group_by("regime").agg(
        n=pl.len(), share=pl.len()/len(d.drop_nulls(["f5","f20"])),
        f5=pl.col("f5").mean(), f5_pos=(pl.col("f5")>0).mean(), f5_sd=pl.col("f5").std(),
        f20=pl.col("f20").mean(), f20_pos=(pl.col("f20")>0).mean(), f20_sd=pl.col("f20").std()).sort("regime")
    print(g)
    allr=d.drop_nulls(["f5","f20"])
    print("all f5 mean",allr["f5"].mean(),"pos",(allr["f5"]>0).mean(),"f20",allr["f20"].mean())
    # persistence of regime: probability tomorrow same
    r=d["regime"].to_list(); print("regime switches", sum(a!=b for a,b in zip(r,r[1:])), "in", len(r))
    # per year share
    y=d.with_columns(y=pl.col("date").dt.year()).group_by("y","regime").agg(pl.len()).pivot(on="regime",index="y",values="len").sort("y").fill_null(0)
    print(y)
    print(d.tail(6).select("date","close","sma50","sma200","r20","r60","dd","vol20","regime"))
