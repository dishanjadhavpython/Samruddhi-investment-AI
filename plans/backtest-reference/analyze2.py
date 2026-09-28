# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "numpy", "scipy"]
# ///
import json
from pathlib import Path
import numpy as np, pandas as pd
from scipy.stats import spearmanr
D = Path(__file__).parent / "nse_data"
pe = pd.DataFrame(json.loads((D / "pepb.json").read_text())); tri = pd.DataFrame(json.loads((D / "tri.json").read_text()))
pe["date"] = pd.to_datetime(pe["DATE"], format="%d %b %Y"); tri["date"] = pd.to_datetime(tri["Date"], format="%d %b %Y")
for c in ["pe","pb","divYield"]: pe[c] = pd.to_numeric(pe[c], errors="coerce")
tri["tri"] = pd.to_numeric(tri["TotalReturnsIndex"].astype(str).str.replace(",",""), errors="coerce")
pe = pe.drop_duplicates("date").set_index("date").sort_index()[["pe","pb","divYield"]]
tri = tri.drop_duplicates("date").set_index("date").sort_index()[["tri"]]
df = tri.join(pe, how="left").dropna(subset=["tri"]); df = df[df.tri>0]
def fwd(h):
    t = df.index + pd.Timedelta(days=int(round(365.25*h))); s = df["tri"]; idx = s.index.searchsorted(t); out = pd.Series(np.nan, index=df.index)
    ok = idx < len(s); out[ok] = (s.values[idx[ok]]/s.values[ok])**(1/h)-1; out[t > s.index[-1]] = np.nan; return out
for h in [1,3,5]: df[f"f{h}"] = fwd(h)
print("PB/DY around switch:\n", pe.loc["2021-03-26":"2021-04-05"].to_string())
print("\nDY jumps > 8% day-on-day:", (pe["divYield"].pct_change().abs()>0.08).sum(), "PB jumps > 8%:", (pe["pb"].pct_change().abs()>0.08).sum())
pbs = df["pb"].dropna(); v = pbs.values
pct = np.array([np.nan if pbs.index[i] < pbs.index[0]+pd.Timedelta(days=3*365) else (v[:i+1]<=v[i]).mean() for i in range(len(v))])
df["pb_pct"] = pd.Series(pct, index=pbs.index)
sub = df.dropna(subset=["pb_pct"]).copy()
sub["zone"] = pd.cut(sub["pb_pct"], [0,.2,.4,.6,.8,1.0001], labels=["<20th","20-40","40-60","60-80",">80th"], include_lowest=True)
for h in [1,3,5]:
    g = sub.dropna(subset=[f"f{h}"]).groupby("zone", observed=True)
    print(f"\nPB expanding pct, {h}y fwd\n", pd.DataFrame({"median": g[f"f{h}"].median().map("{:.1%}".format), "p10": g[f"f{h}"].quantile(.1).map("{:.1%}".format), "%neg": g[f"f{h}"].apply(lambda x:(x<0).mean()).map("{:.0%}".format), "days": g.size(), "yrs": g.apply(lambda x: x.index.year.nunique())}).to_string())
print("\nFull-history PB percentile of latest (%.2f): %.2f ; PB long-run median %.2f mean %.2f" % (pbs.iloc[-1], (v<=v[-1]).mean(), np.median(v), v.mean()))
print("PB min/max since 1999: %.2f / %.2f" % (v.min(), v.max()))
# Out-of-sample 1y: correlations within sub-periods to show instability
for a,b in [("1999","2008"),("2009","2016"),("2017","2025")]:
    s = df.loc[a:b, ["pb","f1","f3"]].dropna()
    r1,_ = spearmanr(s.pb, s.f1); 
    s3 = s.dropna(subset=["f3"]); r3,_ = spearmanr(s3.pb, s3.f3) if len(s3)>100 else (np.nan,None)
    print(f"PB vs fwd rho {a}-{b}: 1y {r1:+.2f}, 3y {r3:+.2f}")
# effective independent obs
print("\nNon-overlapping 5y windows available since mid-1999:", int((df.index[-1]-df.index[0]).days/365.25/5))
