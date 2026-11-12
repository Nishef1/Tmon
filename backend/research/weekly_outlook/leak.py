import sys, numpy as np, polars as pl, pandas as pd
from scipy.stats import spearmanr
SP=sys.argv[1]
r=pd.read_parquet(f"{SP}/wf_out.parquet")
p=pl.read_parquet(f"{SP}/panel.parquet").select("instrument_id","date","queue_state","ret_1","limit_pct","days_in_queue").to_pandas()
p["date"]=pd.to_datetime(p["date"]); r["date"]=pd.to_datetime(r["date"])
r=r.merge(p,on=["instrument_id","date"]).dropna(subset=["fwd_5"])
print(r.queue_state.value_counts(normalize=True).round(3).to_dict())
for name,sub in [("all",r),("not buy_queue",r[r.queue_state!="buy_queue"]),("normal only",r[r.queue_state=="normal"] if (r.queue_state=="normal").any() else r)]:
    out={}
    for col in ["p_v2","p_lgb"]:
        ics=[];top=[];n=0
        for dt,g in sub.groupby("date"):
            if len(g)<40: continue
            ics.append(spearmanr(g[col],g.fwd_5)[0])
            q=g[col].rank(pct=True); ex=g.fwd_5-g.fwd_5.median()
            top.append(ex[q>0.9].mean())
        out[col]=(np.mean(ics),np.mean(top)*100,np.mean(np.array(top)>0)*100,len(ics))
    print(name,len(sub),{k:tuple(round(x,3) for x in v) for k,v in out.items()})
# mean fwd of buy_queue vs others
print(r.groupby("queue_state").fwd_5.agg(["mean","median","count"]))
