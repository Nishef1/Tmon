import sys, numpy as np, pandas as pd
SP=sys.argv[1]; C=0.017512
r=pd.read_parquet(f"{SP}/wf_out.parquet").dropna(subset=["fwd_5"]); r["date"]=pd.to_datetime(r.date)
dates=sorted(r.date.unique())
def sim(col,step,enter=0.1,keep=0.1,offset=0):
    held=set(); rows=[]
    for dt in dates[offset::step]:
        g=r[r.date==dt]
        if len(g)<100: continue
        q=g[col].rank(pct=True); g=g.assign(q=q).set_index("instrument_id")
        keepset={i for i in held if i in g.index and g.loc[i,"q"]>1-keep}
        want=g.index[g.q>1-enter]
        new=keepset|set(want[:max(0,len(want)-len(keepset))]) if keepset else set(want)
        sel=g.loc[list(new)]
        turn=len(new-held)/max(len(new),1)
        gross=sel.fwd_5.mean(); mkt=g.fwd_5.mean()
        rows.append((dt,gross,mkt,turn,gross-turn*C)); held=new
    d=pd.DataFrame(rows,columns=["date","gross","mkt","turn","net"])
    return d
for col in ["p_v2","p_lgb","p_ens"] if "p_ens" in r else ["p_v2","p_lgb"]:
    for enter,keep in [(0.1,0.1),(0.1,0.3)]:
        ds=[sim(col,5,enter,keep,o) for o in range(5)]
        d=pd.concat(ds)
        print(f"{col} enter{enter} keep{keep}: gross {d.gross.mean()*100:.2f}%/wk  mkt(eq-wt) {d.mkt.mean()*100:.2f}%  turnover {d.turn.mean()*100:.0f}%  net {d.net.mean()*100:.2f}%  net-mkt {(d.net-d.mkt).mean()*100:+.2f}%  hit(net>mkt) {((d.net>d.mkt).mean())*100:.0f}%  worst week net {d.net.min()*100:.1f}% (mkt {d.mkt.min()*100:.1f}%)")
