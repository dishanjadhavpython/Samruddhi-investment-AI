# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "numpy"]
# ///
import json
from pathlib import Path
import pandas as pd
D = Path(__file__).parent / "nse_data"
pe = pd.DataFrame(json.loads((D / "pepb.json").read_text())); tri = pd.DataFrame(json.loads((D / "tri.json").read_text()))
pe["date"] = pd.to_datetime(pe["DATE"], format="%d %b %Y"); tri["date"] = pd.to_datetime(tri["Date"], format="%d %b %Y")
for c in ["pe","pb","divYield"]: pe[c] = pd.to_numeric(pe[c], errors="coerce")
tri["tri"] = pd.to_numeric(tri["TotalReturnsIndex"].astype(str).str.replace(",",""), errors="coerce")
pe = pe.drop_duplicates("date").set_index("date").sort_index()[["pe","pb","divYield"]]
tri = tri.drop_duplicates("date").set_index("date").sort_index()[["tri"]]
df = pe.join(tri, how="inner").dropna()
r = df.pct_change()
x = df.loc["2023-09-25":"2023-10-04"]; print(x.to_string())
y = df.loc["2025-06-01":]
ry = y.pct_change()
print((y.assign(dpb=ry.pb, dpe=ry.pe, dpx=ry.tri))[((ry.pb-ry.tri).abs()>0.025)|((ry.pe-ry.tri).abs()>0.025)].to_string())
print(df.resample("QE").last().loc["2025":].to_string())
