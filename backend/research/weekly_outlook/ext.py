import polars as pl, numpy as np
from tmon.core.db import session_scope
from tmon.features.store import load_benchmark_inputs
with session_scope() as s:
    idx, rf = load_benchmark_inputs(s)
pl.Config.set_tbl_rows(40); pl.Config.set_tbl_cols(20)
def frame(code):
    d=idx.filter(pl.col("index_code")==code).select("date","close").sort("date")
    c=d["close"].to_numpy()
    n=len(c); mdd=np.full(n,np.nan)
    for i in range(n-20):
        w=c[i+1:i+21]/c[i]-1; mdd[i]=w.min()
    return d.with_columns(
        sma200=pl.col("close").rolling_mean(200), r60=pl.col("close")/pl.col("close").shift(60)-1,
        r20=pl.col("close")/pl.col("close").shift(20)-1,
        f5=pl.col("close").shift(-5)/pl.col("close")-1, f20=pl.col("close").shift(-20)/pl.col("close")-1,
        f60=pl.col("close").shift(-60)/pl.col("close")-1, mdd20=pl.Series(mdd),
        dd=pl.col("close")/pl.col("close").rolling_max(252)-1).with_columns(ext=pl.col("close")/pl.col("sma200")-1).drop_nulls(["sma200","r60"])
for name,code in {"tedpix":"32097828799138957","ew":"67130298613737946"}.items():
    d=frame(code); v=d.drop_nulls(["f5","f20","mdd20"])
    print("\n=====",name, len(v))
    now=d.tail(1).to_dicts()[0]; print("NOW", {k:now[k] for k in ("date","r20","r60","ext","dd")})
    qs=[0,.25,.5,.75,.9,1.0]
    for col in ("r60","ext","r20"):
        edges=[float(v[col].quantile(q)) for q in qs]
        print(f"-- bucket by {col}; now={now[col]:.3f}; edges", [round(e,3) for e in edges])
        rows=[]
        for lo,hi in zip(edges[:-1],edges[1:]):
            b=v.filter((pl.col(col)>=lo)&(pl.col(col)<=hi))
            rows.append((f"{lo:.2f}..{hi:.2f}",len(b),b["f5"].mean(),(b["f5"]>0).mean(),b["f5"].quantile(.1),b["f20"].mean(),b["f20"].quantile(.1),b["mdd20"].mean(),(b["mdd20"]<-0.10).mean()))
        print("bucket n | f5 mean, up, p10 | f20 mean, p10 | mdd20 mean, P(dd>10%)")
        for r in rows: print(f"{r[0]:>12} {r[1]:5d} | {r[2]*100:5.2f}% {r[3]*100:4.0f}% {r[4]*100:6.2f}% | {r[5]*100:5.1f}% {r[6]*100:6.1f}% | {r[7]*100:6.1f}% {r[8]*100:4.0f}%")
    # comparable: r60>0.30 episodes
    e=v.filter(pl.col("r60")>0.30)
    print("r60>0.30:",len(e),"f5 mean",e["f5"].mean(),"up",(e["f5"]>0).mean(),"f20",e["f20"].mean(),"p10",e["f20"].quantile(.1),"P(dd>10% in 20d)",(e["mdd20"]<-0.10).mean())
    # episodes clusters
    dates=e["date"].to_list(); eps=[]; start=prev=None
    for dt in dates:
        if prev is None or (dt-prev).days>30:
            if start: eps.append((start,prev))
            start=dt
        prev=dt
    eps.append((start,prev))
    for a,b in eps:
        s_=e.filter((pl.col("date")>=a)&(pl.col("date")<=b))
        print(a,b,len(s_),"f5 %.3f f20 %.3f f60 %.3f mdd20 %.3f"%(s_["f5"].mean(),s_["f20"].mean(),s_["f60"].drop_nulls().mean() if s_["f60"].drop_nulls().len() else float('nan'),s_["mdd20"].mean()))
