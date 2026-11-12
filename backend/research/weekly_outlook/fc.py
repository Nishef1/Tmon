import sys, numpy as np, polars as pl, pandas as pd, lightgbm as lgb
SP=sys.argv[1]
p=pl.read_parquet(f"{SP}/panel.parquet").filter(pl.col("date")>=pl.date(2019,6,1))
X=[c for c in p.columns if c.startswith("x_")]
pdf=p.to_pandas(); pdf["date"]=pd.to_datetime(pdf["date"])
last=pdf.date.max(); print("last",last)
tr=pdf[(pdf.date<last-pd.Timedelta(days=10))].dropna(subset=["y_rk"])
params=dict(objective="regression",learning_rate=0.03,num_leaves=15,min_data_in_leaf=500,feature_fraction=0.6,bagging_fraction=0.7,bagging_freq=1,lambda_l2=50,verbose=-1,num_threads=8,seed=7)
m=lgb.train(params,lgb.Dataset(tr[X].values.astype("float32"),tr["y_rk"].values),num_boost_round=250)
today=pdf[pdf.date==last].copy()
today["p_lgb"]=m.predict(today[X].values.astype("float32"))
f=pl.read_parquet(f"{SP}/feats.parquet").select("instrument_id","date","ret_1").sort("instrument_id","date").with_columns(sd60=pl.col("ret_1").rolling_std(60).over("instrument_id")).filter(pl.col("date")==pl.lit(last.date())).select("instrument_id","sd60").to_pandas()
today=today.merge(f,on="instrument_id")
for c in ["p_lgb","p_v2"]: today["r_"+c]=today[c].rank(pct=True)
today["score"]=(today.r_p_lgb+today.r_p_v2)/2
today[["instrument_id","score","r_p_lgb","r_p_v2","sd60","median_value_20"]].to_parquet(f"{SP}/today.parquet")
print(len(today)); print(today.sort_values("score",ascending=False)[["instrument_id","score","r_p_lgb","r_p_v2","sd60"]].head(10))
