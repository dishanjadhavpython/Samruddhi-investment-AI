# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "numpy"]
# ///
import json
from pathlib import Path
import numpy as np, pandas as pd
D = Path(__file__).parent / "nse_data"
pe = pd.DataFrame(json.loads((D / "pepb.json").read_text())); tri = pd.DataFrame(json.loads((D / "tri.json").read_text()))
pe["date"] = pd.to_datetime(pe["DATE"], format="%d %b %Y"); tri["date"] = pd.to_datetime(tri["Date"], format="%d %b %Y")
for c in ["pe","pb"]: pe[c] = pd.to_numeric(pe[c], errors="coerce")
tri["tri"] = pd.to_numeric(tri["TotalReturnsIndex"].astype(str).str.replace(",",""), errors="coerce")
pe = pe.drop_duplicates("date").set_index("date").sort_index()[["pe","pb"]]
tri = tri.drop_duplicates("date").set_index("date").sort_index()[["tri"]]
df = tri.join(pe, how="left").dropna(subset=["tri"]); df = df[df.tri>0]
df["pe_adj"] = np.where(df.index < "2021-03-31", df.pe*33.20/40.43, df.pe)
df["pb_adj"] = np.where(df.index < "2023-09-29", df.pb*3.46/4.31, df.pb)
def exp_pct(col):
    s = df[col].dropna(); v = s.values
    return pd.Series([np.nan if s.index[i] < s.index[0]+pd.Timedelta(days=3*365) else (v[:i+1]<=v[i]).mean() for i in range(len(v))], index=s.index)
df["temp"] = pd.concat([exp_pct("pe_adj"), exp_pct("pb_adj")], axis=1).mean(axis=1)
m = df["tri"]
def run(months, horizon, cash):
    res = []
    for s0 in m.index[m.index <= m.index[-1] - pd.DateOffset(months=horizon)]:
        pos = m.index.searchsorted([s0 + pd.DateOffset(months=k) for k in range(months)])
        pe_ = m.index.searchsorted(s0 + pd.DateOffset(months=horizon))
        if pe_ >= len(m): continue
        p_end = m.iloc[pe_]
        stp = sum((1/months)*(1+cash)**(k/12)*p_end/m.iloc[p] for k,p in enumerate(pos))
        res.append((s0, p_end/m.iloc[pos[0]], stp))
    r = pd.DataFrame(res, columns=["start","ls","stp"]).set_index("start").join(df[["temp"]])
    r["zone"] = pd.cut(r["temp"], [0,.33,.67,1.0001], labels=["cool third","mid third","hot third"], include_lowest=True)
    out = r.dropna(subset=["zone"]).groupby("zone", observed=True).apply(lambda x: f"LS wins {(x.ls>x.stp).mean():.0%}, median LS edge {(x.ls/x.stp-1).median():+.1%}, worst-10% edge {(x.ls/x.stp-1).quantile(.1):+.1%}, n={len(x)}, yrs={x.index.year.nunique()}")
    print(f"\n{months}m STP @ {horizon}m, cash {cash:.0%}: overall LS wins {(r.ls>r.stp).mean():.0%}")
    for k,v in out.items(): print("  ", k, v)
for a in [(6,12,0.06),(12,12,0.06)]: run(*a)
