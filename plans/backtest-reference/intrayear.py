# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "numpy"]
# ///
import json
from pathlib import Path
import numpy as np, pandas as pd
D = Path(__file__).parent / "nse_data"
tri = pd.DataFrame(json.loads((D / "tri.json").read_text()))
tri["date"] = pd.to_datetime(tri["Date"], format="%d %b %Y")
tri["tri"] = pd.to_numeric(tri["TotalReturnsIndex"].astype(str).str.replace(",",""), errors="coerce")
s = tri.drop_duplicates("date").set_index("date").sort_index()["tri"].dropna()
s = s[s>0]
rows = []
for y, g in s.groupby(s.index.year):
    prev = s[s.index.year < y]
    base = prev.iloc[-1] if len(prev) else g.iloc[0]
    path = pd.concat([pd.Series([base]), g.reset_index(drop=True)])
    dd = (path / path.cummax() - 1).min()
    rows.append((y, g.iloc[-1]/base - 1, dd, len(prev) > 0))
t = pd.DataFrame(rows, columns=["year","cal_ret","intra_dd","full"]).set_index("year")
t = t[t.full]
print(t.assign(cal_ret=t.cal_ret.map("{:+.1%}".format), intra_dd=t.intra_dd.map("{:.1%}".format)).drop(columns="full").to_string())
full = t.loc[:2025]
print("\nYears 2000-2025:", len(full), "negative years:", (full.cal_ret<0).sum(), list(full.index[full.cal_ret<0]))
print("median intra-year drawdown: %.1f%%" % (full.intra_dd.median()*100))
print("years with intra-year DD worse than -10%%: %d; of which ended positive: %d" % ((full.intra_dd<-0.10).sum(), ((full.intra_dd<-0.10)&(full.cal_ret>0)).sum()))
# max drawdown episodes
dd = s/s.cummax()-1
print("worst drawdown %.1f%% on %s" % (dd.min()*100, dd.idxmin().date()))
print("current drawdown %.1f%% ; ATH date %s" % (dd.iloc[-1]*100, s.idxmax().date()))
