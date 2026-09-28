# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "numpy", "scipy"]
# ///
import json
from pathlib import Path
import numpy as np, pandas as pd
D = Path(__file__).parent / "nse_data"
pe = pd.DataFrame(json.loads((D / "pepb.json").read_text())); tri = pd.DataFrame(json.loads((D / "tri.json").read_text()))
pe["date"] = pd.to_datetime(pe["DATE"], format="%d %b %Y"); tri["date"] = pd.to_datetime(tri["Date"], format="%d %b %Y")
for c in ["pe","pb","divYield"]: pe[c] = pd.to_numeric(pe[c], errors="coerce")
tri["tri"] = pd.to_numeric(tri["TotalReturnsIndex"].astype(str).str.replace(",",""), errors="coerce")
pe = pe.drop_duplicates("date").set_index("date").sort_index()[["pe","pb","divYield"]]
tri = tri.drop_duplicates("date").set_index("date").sort_index()[["tri"]]
df = tri.join(pe, how="left").dropna(subset=["tri"]); df = df[df.tri>0]
# chain-link: scale pre-break history onto the current basis
k_pe = 33.20/40.43; k_pb = 3.46/4.31
df["pe_adj"] = np.where(df.index < "2021-03-31", df.pe*k_pe, df.pe)
df["pb_adj"] = np.where(df.index < "2023-09-29", df.pb*k_pb, df.pb)
print(f"scale factors: PE {k_pe:.3f}, PB {k_pb:.3f}")
def fwd(h):
    t = df.index + pd.Timedelta(days=int(round(365.25*h))); s = df["tri"]; idx = s.index.searchsorted(t); out = pd.Series(np.nan, index=df.index)
    ok = idx < len(s); out[ok] = (s.values[idx[ok]]/s.values[ok])**(1/h)-1; out[t > s.index[-1]] = np.nan; return out
for h in [1,3,5]: df[f"f{h}"] = fwd(h)
def exp_pct(col):
    s = df[col].dropna(); v = s.values
    return pd.Series([np.nan if s.index[i] < s.index[0]+pd.Timedelta(days=3*365) else (v[:i+1]<=v[i]).mean() for i in range(len(v))], index=s.index)
for c in ["pe_adj","pb_adj"]:
    df[c+"_pct"] = exp_pct(c)
    s = df[c].dropna(); print(f"latest {c}={s.iloc[-1]:.2f}, full-history percentile (adjusted) {(s<=s.iloc[-1]).mean():.2f}, median {s.median():.2f}")
# composite: average of valuation percentiles (PE_adj, PB_adj), inverted so 0=cheap 100=rich
df["val_temp"] = df[["pe_adj_pct","pb_adj_pct"]].mean(axis=1)
sub = df.dropna(subset=["val_temp"]).copy()
sub["zone"] = pd.cut(sub["val_temp"], [0,.2,.4,.6,.8,1.0001], labels=["Cool <20","20-40","40-60","60-80","Hot >80"], include_lowest=True)
for h in [1,3,5]:
    g = sub.dropna(subset=[f"f{h}"]).groupby("zone", observed=True)
    print(f"\nValuation temperature (adj PE+PB expanding pct), {h}y fwd\n", pd.DataFrame({"median": g[f"f{h}"].median().map("{:.1%}".format), "p10": g[f"f{h}"].quantile(.1).map("{:.1%}".format), "p90": g[f"f{h}"].quantile(.9).map("{:.1%}".format), "%neg": g[f"f{h}"].apply(lambda x:(x<0).mean()).map("{:.0%}".format), "days": g.size(), "yrs": g.apply(lambda x: x.index.year.nunique())}).to_string())
print("\nLatest valuation temperature:", round(df["val_temp"].dropna().iloc[-1]*100), "(0=cheapest, 100=richest vs history to date)")
# share of time in each zone
print(sub["zone"].value_counts(normalize=True).sort_index().map("{:.0%}".format).to_string())
