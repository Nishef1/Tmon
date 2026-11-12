import sys, numpy as np, polars as pl, lightgbm as lgb
from scipy.stats import spearmanr
SP=sys.argv[1]
d=pl.read_parquet(f"{SP}/panel.parquet").filter(pl.col("date")>=pl.date(2019,6,1)).drop_nulls(["y_rk"]).sort("date")
X=[c for c in d.columns if c.startswith("x_")]
dates=d["date"].unique().sort().to_list()
pdf=d.select(["date","instrument_id","fwd_5","y_ex","y_rk","p_v2","mkt_ret_ew_20d"]+X).to_pandas()
import pandas as pd
pdf["date"]=pd.to_datetime(pdf["date"])
starts=pd.date_range("2022-01-01","2026-11-01",freq="MS")
out=[]
params=dict(objective="regression",learning_rate=0.03,num_leaves=15,min_data_in_leaf=500,feature_fraction=0.6,bagging_fraction=0.7,bagging_freq=1,lambda_l2=50,verbose=-1,num_threads=8,seed=7)
for a,b in zip(starts[:-1],starts[1:]):
    tr=pdf[pdf.date<a-pd.Timedelta(days=10)]
    te=pdf[(pdf.date>=a)&(pdf.date<b)]
    if len(te)==0 or len(tr)<50000: continue
    m=lgb.train(params,lgb.Dataset(tr[X].values.astype("float32"),tr["y_rk"].values),num_boost_round=250)
    t=te[["date","instrument_id","fwd_5","y_ex","y_rk","p_v2","mkt_ret_ew_20d"]].copy()
    t["p_lgb"]=m.predict(te[X].values.astype("float32"))
    out.append(t)
r=pd.concat(out); r.to_parquet(f"{SP}/wf_out.parquet")
def rk(s): return s.groupby(r.date).rank(pct=True)
r["p_ens"]=(rk(r.p_lgb)+rk(r.p_v2))/2
r=r.dropna(subset=["fwd_5"])
COST=0.017512
def stats(col,sub):
    ics=[];top=[];bot=[]
    for dt,g in sub.groupby("date"):
        if len(g)<40: continue
        ics.append(spearmanr(g[col],g.fwd_5)[0])
        q=g[col].rank(pct=True)
        top.append(g.loc[q>0.9,"y_ex"].mean()); bot.append(g.loc[q<=0.1,"y_ex"].mean())
    ics=np.array(ics);top=np.array(top);bot=np.array(bot)
    n=len(ics); eff=max(n/5,2)
    return f"IC {ics.mean():+.4f} t~{ics.mean()/ics.std()*np.sqrt(eff):+.1f} | top10 excess {top.mean()*100:+.2f}% (hit {np.mean(top>0)*100:.0f}%) | bottom {bot.mean()*100:+.2f}% | days {n}"
for col in ["p_v2","p_lgb","p_ens"]:
    print("==",col)
    print(" all ",stats(col,r))
    for y,g in r.groupby(r.date.dt.year): print(f" {y} ",stats(col,g))
    reg=pd.cut(r.mkt_ret_ew_20d,[-9,-0.02,0.03,9],labels=["ew20<-2%","range","ew20>+3%"])
    for k,g in r.groupby(reg,observed=True): print(f" {k} ",stats(col,g))
print("cost per round trip",COST)
