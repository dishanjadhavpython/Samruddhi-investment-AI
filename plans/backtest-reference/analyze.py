# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "numpy", "scipy"]
# ///
"""Evidence checks on Nifty 50 valuation/trend signals vs forward total returns (NSE Indices data)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

D = Path(__file__).parent / "nse_data"
pe = pd.DataFrame(json.loads((D / "pepb.json").read_text()))
tri = pd.DataFrame(json.loads((D / "tri.json").read_text()))
pe["date"] = pd.to_datetime(pe["DATE"], format="%d %b %Y")
tri["date"] = pd.to_datetime(tri["Date"], format="%d %b %Y")
for c in ["pe", "pb", "divYield"]:
    pe[c] = pd.to_numeric(pe[c], errors="coerce")
tri["tri"] = pd.to_numeric(tri["TotalReturnsIndex"].astype(str).str.replace(",", ""), errors="coerce")
pe = pe.drop_duplicates("date").set_index("date").sort_index()[["pe", "pb", "divYield"]]
tri = tri.drop_duplicates("date").set_index("date").sort_index()[["tri"]]
df = tri.join(pe, how="left").dropna(subset=["tri"])
df = df[df.tri > 0]
print("TRI range", df.index.min().date(), df.index.max().date(), len(df))
print("PE range", pe.dropna().index.min().date(), pe.dropna().index.max().date(), len(pe.dropna()))
print("latest", df.dropna().tail(3))

# PE break around April 2021 (standalone -> consolidated)
w = pe.loc["2021-03-20":"2021-04-10"]
print("\nPE around Apr-2021 switch:\n", w.to_string())

# forward CAGR
def fwd(h_years: float) -> pd.Series:
    target = df.index + pd.Timedelta(days=int(round(365.25 * h_years)))
    s = df["tri"]
    idx = s.index.searchsorted(target)
    ok = idx < len(s)
    out = pd.Series(np.nan, index=df.index)
    vals = s.values
    out[ok] = (vals[idx[ok]] / vals[ok]) ** (1 / h_years) - 1
    # drop if target beyond last date
    out[target > s.index[-1]] = np.nan
    return out

H = [1, 3, 5, 7]
for h in H:
    df[f"f{h}"] = fwd(h)

# 1. Spearman rank correlations
print("\n=== Spearman rank correlation, signal vs forward CAGR (daily overlapping obs) ===")
for sig in ["pe", "pb", "divYield"]:
    row = []
    for h in H:
        sub = df[[sig, f"f{h}"]].dropna()
        r, _ = spearmanr(sub[sig], sub[f"f{h}"])
        row.append(f"{h}y: rho={r:+.2f} (n={len(sub)}, start {sub.index.min().year}-{sub.index.max().year})")
    print(sig, " | ".join(row))

# 2. PE quintiles (full-sample, look-ahead) — forward outcomes
print("\n=== Full-sample PE quintiles (look-ahead cut points) ===")
sub = df.dropna(subset=["pe"]).copy()
sub["q"] = pd.qcut(sub["pe"], 5, labels=["Q1 cheap", "Q2", "Q3", "Q4", "Q5 rich"])
for h in [1, 3, 5]:
    g = sub.dropna(subset=[f"f{h}"]).groupby("q", observed=True)
    t = pd.DataFrame({
        "PE range": g["pe"].agg(lambda x: f"{x.min():.1f}-{x.max():.1f}"),
        "median CAGR": g[f"f{h}"].median().map("{:.1%}".format),
        "p10": g[f"f{h}"].quantile(0.1).map("{:.1%}".format),
        "p90": g[f"f{h}"].quantile(0.9).map("{:.1%}".format),
        "% negative": g[f"f{h}"].apply(lambda x: (x < 0).mean()).map("{:.0%}".format),
        "days": g.size(),
    })
    print(f"\n-- {h}-year forward --\n", t.to_string())

# 3. Out-of-sample: expanding-window PE percentile (only past data), >=3y history
print("\n=== Expanding-window PE percentile (no look-ahead), from 2002 ===")
pes = df["pe"].dropna()
pct = pd.Series(np.nan, index=pes.index)
vals = pes.values
for i in range(len(pes)):
    if pes.index[i] < pes.index[0] + pd.Timedelta(days=3 * 365):
        continue
    pct.iloc[i] = (vals[: i + 1] <= vals[i]).mean()
df["pe_pct"] = pct
sub = df.dropna(subset=["pe_pct"]).copy()
sub["zone"] = pd.cut(sub["pe_pct"], [0, 0.2, 0.4, 0.6, 0.8, 1.0001], labels=["<20th", "20-40", "40-60", "60-80", ">80th"], include_lowest=True)
for h in [1, 3, 5]:
    g = sub.dropna(subset=[f"f{h}"]).groupby("zone", observed=True)
    t = pd.DataFrame({
        "median CAGR": g[f"f{h}"].median().map("{:.1%}".format),
        "p10": g[f"f{h}"].quantile(0.1).map("{:.1%}".format),
        "% negative": g[f"f{h}"].apply(lambda x: (x < 0).mean()).map("{:.0%}".format),
        "days": g.size(),
        "distinct years": g.apply(lambda x: x.index.year.nunique()),
    })
    print(f"\n-- {h}-year forward --\n", t.to_string())

# 4. Drawdown from all-time high (TRI)
print("\n=== Drawdown from TRI all-time high vs forward CAGR ===")
df["dd"] = df["tri"] / df["tri"].cummax() - 1
df["ddz"] = pd.cut(df["dd"], [-1, -0.3, -0.2, -0.1, -0.05, 0.0001], labels=[">30% off", "20-30%", "10-20%", "5-10%", "<5% off ATH"])
for h in [1, 3, 5]:
    g = df.dropna(subset=[f"f{h}"]).groupby("ddz", observed=True)
    t = pd.DataFrame({
        "median CAGR": g[f"f{h}"].median().map("{:.1%}".format),
        "% negative": g[f"f{h}"].apply(lambda x: (x < 0).mean()).map("{:.0%}".format),
        "days": g.size(),
        "distinct years": g.apply(lambda x: x.index.year.nunique()),
    })
    print(f"\n-- {h}-year forward --\n", t.to_string())

# 5. Trend: above/below 200-day moving average
print("\n=== 200-DMA trend (TRI) vs forward outcomes ===")
df["ma200"] = df["tri"].rolling(200).mean()
df["above"] = np.where(df["ma200"].isna(), np.nan, (df["tri"] > df["ma200"]).astype(float))
# forward 1-month return & forward 12m max drawdown
df["f1m"] = fwd(1 / 12)
tri_v = df["tri"].values
maxdd = np.full(len(df), np.nan)
idx_end = df.index.searchsorted(df.index + pd.Timedelta(days=365))
for i in range(len(df)):
    j = idx_end[i]
    if j >= len(df):
        break
    path = tri_v[i : j + 1]
    maxdd[i] = (path / np.maximum.accumulate(path) - 1).min()
df["fmaxdd12"] = maxdd
daily = df["tri"].pct_change().shift(-1)
df["next_day"] = daily
g = df.dropna(subset=["above"]).groupby("above")
print(pd.DataFrame({
    "share of days": g.size() / g.size().sum(),
    "median 1y fwd": g["f1"].median(),
    "mean 1y fwd": g["f1"].mean(),
    "% neg 1y": g["f1"].apply(lambda x: (x.dropna() < 0).mean()),
    "median next-12m maxDD": g["fmaxdd12"].median(),
    "ann. vol next-day (regime)": g["next_day"].std() * np.sqrt(250),
    "ann. mean next-day (regime)": g["next_day"].mean() * 250,
}).to_string())

# 6. Lump sum vs STP (monthly tranches) — India, Nifty 50 TRI
print("\n=== Lump sum vs staggered (STP) — Nifty 50 TRI, rolling daily starts ===")
m = df["tri"]
def stp_vs_ls(months: int, horizon_m: int, cash_rate: float):
    res = []
    starts = m.index[m.index <= m.index[-1] - pd.DateOffset(months=horizon_m)]
    for s0 in starts:
        dates = [s0 + pd.DateOffset(months=k) for k in range(months)]
        end = s0 + pd.DateOffset(months=horizon_m)
        pos = m.index.searchsorted(dates)
        pe_ = m.index.searchsorted(end)
        if pe_ >= len(m) or pos[-1] >= len(m):
            continue
        p_end = m.iloc[pe_]
        ls = p_end / m.iloc[pos[0]]
        tranche = 1 / months
        stp = 0.0
        for k, p in enumerate(pos):
            # cash waiting k months earns cash_rate before being invested
            grown = tranche * (1 + cash_rate) ** (k / 12)
            stp += grown * p_end / m.iloc[p]
        res.append((s0, ls, stp))
    r = pd.DataFrame(res, columns=["start", "ls", "stp"]).set_index("start")
    return r

for months, horizon, cash in [(3, 12, 0.0), (6, 12, 0.0), (6, 12, 0.06), (12, 12, 0.06), (12, 24, 0.06)]:
    r = stp_vs_ls(months, horizon, cash)
    win = (r.ls > r.stp).mean()
    diff = (r.ls / r.stp - 1)
    # condition on PE zone at start
    r = r.join(df[["pe_pct", "dd", "above"]], how="left")
    r["zone"] = pd.cut(r["pe_pct"], [0, 0.33, 0.67, 1.0001], labels=["cheap third", "mid third", "rich third"], include_lowest=True)
    zw = r.dropna(subset=["zone"]).groupby("zone", observed=True).apply(lambda x: f"LS wins {(x.ls > x.stp).mean():.0%}, median edge {(x.ls/x.stp-1).median():+.1%}, n={len(x)}")
    tw = r.dropna(subset=["above"]).groupby("above").apply(lambda x: f"LS wins {(x.ls > x.stp).mean():.0%}, median edge {(x.ls/x.stp-1).median():+.1%}")
    print(f"\n{months}-month STP, evaluated at {horizon}m, cash {cash:.0%}: LS wins {win:.0%} of {len(r)} start days "
          f"({r.index.min().date()}..{r.index.max().date()}); median LS edge {diff.median():+.1%}, p10 {diff.quantile(.1):+.1%}, p90 {diff.quantile(.9):+.1%}")
    print("  by expanding PE percentile at start:", dict(zw))
    print("  by 200DMA trend at start (1=above):", dict(tw))

# 7. latest readings for context
last = df.dropna(subset=["pe"]).iloc[-1]
print("\nLatest:", df.dropna(subset=["pe"]).index[-1].date(), "PE", last.pe, "PB", last.pb, "DY", last.divYield,
      "PE pct (expanding, all since 1999)", round(last.pe_pct, 2), "drawdown", round(last.dd, 3), "above200", last.above)
post = pe.loc["2021-04-01":, "pe"].dropna()
print("Post-Apr-2021 consolidated PE: min %.1f median %.1f max %.1f; latest percentile within post-2021 = %.2f" % (
    post.min(), post.median(), post.max(), (post <= post.iloc[-1]).mean()))
