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
for c in ["pe","pb","divYield"]: pe[c] = pd.to_numeric(pe[c], errors="coerce")
tri["tri"] = pd.to_numeric(tri["TotalReturnsIndex"].astype(str).str.replace(",",""), errors="coerce")
pe = pe.drop_duplicates("date").set_index("date").sort_index()[["pe","pb","divYield"]]
tri = tri.drop_duplicates("date").set_index("date").sort_index()[["tri"]]
df = pe.join(tri, how="inner").dropna()
r = df.pct_change()
# valuation jump not explained by price move
for c in ["pe","pb"]:
    x = (r[c] - r["tri"]).abs()
    print(c, "unexplained jumps >6%:"); print(df.assign(chg=r[c], px=r["tri"])[x>0.06][[c,"chg","px"]].to_string())
print(df.resample("YE").last()[["pe","pb","divYield"]].to_string())
