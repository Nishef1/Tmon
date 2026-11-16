import math, numpy as np, polars as pl
from tmon.core.engine_config import get_engine_config
from tmon.backtest.signal_decay import adjusted_close, build_panel
from tmon.core.db import session_scope
from tmon.features.builder import build_features
from tmon.features.store import load_inputs
from tmon.domain.rules import RuleBook
cfg=get_engine_config(); H=(5,20,60); COST=0.0175
with session_scope() as s:
    prices,clients,sectors=load_inputs(s); rules=RuleBook.from_session(s)
feats=build_features(prices,clients,rules,sectors=sectors); adj=adjusted_close(prices)
panel=build_panel(feats,adj,cfg,horizons=H)
mv=feats.select("instrument_id","date","median_value_20")
p=panel.join(mv,on=["instrument_id","date"],how="left").filter(pl.col("median_value_20").is_not_null())
p=p.with_columns(pl.col("median_value_20").rank("ordinal",descending=True).over("date").alias("liq_rank"))
def sub(d,top=None,noq=False):
    if top: d=d.filter(pl.col("liq_rank")<=top)
    if noq: d=d.filter(pl.col("queue_state")!="buy_queue")
    n=pl.col("composite").count().over("date")
    return d.with_columns(((pl.col("composite").rank("average").over("date")-0.5)/n).alias("rr"))
rng=np.random.default_rng(7)
def boot(x,h,B=2000):
    n=len(x); L=max(2*h,20); m=x.mean(); out=np.empty(B)
    nb=math.ceil(n/L)
    for b in range(B):
        st=rng.integers(0,n,nb); idx=(st[:,None]+np.arange(L)[None,:]).ravel()%n
        out[b]=x[idx[:n]].mean()
    se=out.std(); return m/se if se>0 else float("nan")
def run(name,d):
    for h in H:
        f=f"fwd_{h}"; x=d.filter(pl.col(f).is_finite()&pl.col(f).is_not_null())
        per=(x.group_by("date").agg(pl.len().alias("n"),pl.col(f).median().alias("med"),pl.col(f).mean().alias("avg"),
             pl.col(f).filter(pl.col("rr")>0.9).mean().alias("top"),pl.col(f).filter(pl.col("rr")<=0.1).mean().alias("bot"))
             .filter(pl.col("n")>=30).sort("date"))
        if per.height<100: print(name,h,"too few"); continue
        t=per["top"].to_numpy(); med=per["med"].to_numpy(); av=per["avg"].to_numpy(); bt=per["bot"].to_numpy()
        ex_med=t-med; ex_avg=t-av
        half=per.height//2
        print(f"{name:26s} h={h:2d} days={per.height} n/day={per['n'].mean():.0f} top-med={ex_med.mean()*100:5.2f}% top-avg={ex_avg.mean()*100:5.2f}% bot-avg={(bt-av).mean()*100:5.2f}% "
              f"net(avg)={(ex_avg.mean()-COST)*100:5.2f}% bootT(avg)={boot(ex_avg,h):5.2f} halves={ex_avg[:half].mean()*100:5.2f}/{ex_avg[half:].mean()*100:5.2f} netpos_share={np.mean(ex_avg>COST):.2f}")
run("A all eligible",sub(p))
run("B top100 liquid",sub(p,100))
run("C top100 no-buy-queue",sub(p,100,True))
run("D top300 no-buy-queue",sub(p,300,True))
