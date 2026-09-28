"""
Backtest harness for the valuation temperature (plan section 5.5).

Compares percentile windows (expanding vs rolling 10 and 15 years), checks how
stable the valuation/return relationship is across sub-periods, puts
block-bootstrap intervals on each zone's median return, and checks the zone
table against the research figures in plan section 5.2.

    uv run backtest.py                 # series stored in Aurora
    uv run backtest.py --files nse_data/   # local downloads, no database

Writes reports/backtest-<method>.md next to this file.
"""

import argparse
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from dotenv import load_dotenv

import deployment
import history
import indicators
import nse_files
from series import KNOWN_BREAKS, METHOD_VERSION, PB, PE, TRI, DY
from zones import ZONES, raw_zone

load_dotenv(override=True)

WINDOWS = {"expanding": None, "rolling 10y": 10, "rolling 15y": 15}
SUB_PERIODS = [("1999", "2008"), ("2009", "2016"), ("2017", "2025")]
BOOTSTRAP_RESAMPLES = 300

# Plan section 5.2 (research walk-forward, Jun 1999 to Sep 2026): 1-yr median,
# 1-yr 10th percentile, 1-yr share negative, 3-yr median, 5-yr median
REFERENCE_52 = {
    "much_cheaper": (0.718, 0.378, 0.00, 0.403, 0.379),
    "cheaper": (0.311, 0.098, 0.00, 0.187, 0.147),
    "typical": (0.198, 0.005, 0.10, 0.135, 0.136),
    "pricier": (0.130, -0.076, 0.20, 0.106, 0.127),
    "much_pricier": (0.080, -0.224, 0.27, 0.122, 0.100),
}

# Plan section 5.3: a 6-month plan with 6% on waiting cash, compared after 12
# months. Share of periods the lump sum did better, median edge, worst-10% edge.
REFERENCE_53 = {
    "all": (0.60, 0.016, -0.079),
    "cheapest": (0.84, 0.066, -0.033),
    "middle": (0.65, 0.028, -0.063),
    "richest": (0.56, 0.009, -0.073),
}


def load_from_files(inputs: List[str]) -> Dict[str, pd.Series]:
    parsed = [nse_files.parse_file(p) for p in nse_files.collect_files(inputs)]
    series = {}
    for series_id, points in nse_files.merge(parsed).items():
        s = pd.Series(list(points.values()), index=pd.to_datetime(list(points.keys())), dtype=float, name=series_id)
        series[series_id] = s.sort_index()
    return series


def load_from_db() -> Dict[str, pd.Series]:
    from src import Database

    import store

    db = Database()
    return {sid: store.load_series(db, sid) for sid in (PE, PB, DY, TRI)}


def pct(value: Optional[float], digits: int = 1) -> str:
    return "–" if value is None else f"{value * 100:.{digits}f}%"


def zone_rows(table: Dict) -> List[str]:
    lines = [
        "| Zone | Days | 1-yr median | 1-yr p10 | 1-yr negative | 3-yr median | 5-yr median | Distinct years (1-yr) | 5-yr episodes |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for z in table["zones"]:
        h1, h3, h5 = z["h1"], z["h3"], z["h5"]
        lines.append(
            f"| {z['label']} | {pct(z['share_of_days'], 0)} | {pct(h1['median'])} | {pct(h1['p10'])} | {pct(h1['pct_negative'], 0)} | "
            f"{pct(h3['median'])} | {pct(h5['median'])} | {h1['distinct_years']} | {h5['episodes']} |"
        )
    return lines


def block_bootstrap_medians(returns: pd.Series, zones: pd.Series, years: int, seed: int = 7) -> Dict[str, tuple]:
    """90% intervals for each zone's median forward return.

    Overlapping windows make daily observations far from independent, so
    whole blocks of one horizon's length are resampled together.
    """
    frame = pd.DataFrame({"r": returns, "z": zones}).dropna()
    n = len(frame)
    block = min(n, 252 * years)
    if n < 2 * block:
        return {}
    rng = np.random.default_rng(seed)
    r = frame["r"].to_numpy()
    z = frame["z"].to_numpy()
    medians: Dict[str, List[float]] = {zone.id: [] for zone in ZONES}
    for _ in range(BOOTSTRAP_RESAMPLES):
        starts = rng.integers(0, n - block + 1, size=int(np.ceil(n / block)))
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        for zone in ZONES:
            picked = r[idx][z[idx] == zone.id]
            if len(picked):
                medians[zone.id].append(float(np.median(picked)))
    return {k: (float(np.quantile(v, 0.05)), float(np.quantile(v, 0.95))) for k, v in medians.items() if len(v) > BOOTSTRAP_RESAMPLES // 2}


def spearman(a: pd.Series, b: pd.Series) -> Optional[float]:
    """Spearman's rho: Pearson correlation of the ranks (no scipy needed)."""
    frame = pd.concat([a, b], axis=1).dropna()
    if len(frame) <= 250 or frame.iloc[:, 0].nunique() < 2 or frame.iloc[:, 1].nunique() < 2:
        return None
    return float(frame.iloc[:, 0].rank().corr(frame.iloc[:, 1].rank()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--files", nargs="+", help="read these downloads instead of Aurora")
    args = parser.parse_args()

    data = load_from_files(args.files) if args.files else load_from_db()
    tri = data.get(TRI, pd.Series(dtype=float)).dropna()
    pe_raw = data.get(PE, pd.Series(dtype=float)).dropna()
    pb_raw = data.get(PB, pd.Series(dtype=float)).dropna()
    if tri.empty or (pe_raw.empty and pb_raw.empty):
        print("Needs the Nifty 50 TRI and P/E or P/B history. Load the manual downloads first (see README.md).")
        return

    pe = indicators.chain_link(pe_raw, [b for b in KNOWN_BREAKS if b.series_id == PE])
    pb = indicators.chain_link(pb_raw, [b for b in KNOWN_BREAKS if b.series_id == PB])
    out = [
        f"# Valuation temperature backtest ({METHOD_VERSION})",
        "",
        f"Generated {date.today().isoformat()}. TRI {tri.index[0].date()} to {tri.index[-1].date()}; "
        f"P/E {pe.index[0].date() if not pe.empty else '–'} to {pe.index[-1].date() if not pe.empty else '–'}; "
        f"P/B {pb.index[0].date() if not pb.empty else '–'} to {pb.index[-1].date() if not pb.empty else '–'}.",
        "",
        "Every figure is a past distribution of forward Nifty 50 total returns, not a forecast. "
        "Overlapping daily windows are not independent; see the episode counts and bootstrap intervals.",
        "",
    ]

    forward = {h: indicators.forward_cagr(tri, h) for h in history.HORIZONS}
    expanding_temp = None
    for name, years in WINDOWS.items():
        temp = indicators.valuation_temperature(pe, pb, years)
        if years is None:
            expanding_temp = temp
        table = history.zone_table(temp, tri)
        hot = (temp >= 60).mean()
        cold = (temp <= 40).mean()
        out += [
            f"## Window: {name}",
            "",
            f"Latest score {temp.iloc[-1]:.0f} ({raw_zone(temp.iloc[-1]).label}) on {temp.index[-1].date()}. "
            f"Days reading 60 or more: {hot:.0%}; 40 or less: {cold:.0%}.",
            "",
            *zone_rows(table),
            "",
        ]

    # Research reference check (expanding window only)
    table = history.zone_table(expanding_temp, tri)
    out += [
        "## Check against plan section 5.2 (expanding window)",
        "",
        "Differences in percentage points; the research rounded to 0.1.",
        "",
        "| Zone | 1-yr median | 1-yr p10 | 1-yr negative | 3-yr median | 5-yr median |",
        "|---|---|---|---|---|---|",
    ]
    worst = 0.0
    for z in table["zones"]:
        ref = REFERENCE_52[z["id"]]
        got = (z["h1"]["median"], z["h1"]["p10"], z["h1"]["pct_negative"], z["h3"]["median"], z["h5"]["median"])
        diffs = [None if g is None else (g - r) * 100 for g, r in zip(got, ref)]
        worst = max([worst] + [abs(d) for d in diffs if d is not None])
        out.append(f"| {z['label']} | " + " | ".join("–" if d is None else f"{d:+.1f}" for d in diffs) + " |")
    out += ["", f"Largest difference: {worst:.1f} points.", ""]

    # Lump sum vs staggered, daily starts as in the research (plan section 5.3)
    from src import deployment as explorer

    ratios = deployment.growth_ratios(tri, step=1)
    temp_at = expanding_temp.reindex(ratios.index)
    rows = [[d.date().isoformat(), None if np.isnan(temp_at[d]) else float(temp_at[d])] + list(g) for d, g in ratios.iterrows()]
    result = explorer.explore({"rows": rows, "horizon_months": 12, "has_temperature": True}, 6, 0.06)
    out += [
        "## Check against plan section 5.3 (6-month plan, 6% on waiting cash)",
        "",
        "| Group | Lump sum did better | Median edge | Worst-10% edge | Periods | Research |",
        "|---|---|---|---|---|---|",
    ]
    for group in result["groups"]:
        ref = REFERENCE_53[group["id"]]
        if not group["n"]:
            continue
        out.append(
            f"| {group['label']} | {group['lump_better_pct']:.0%} | {pct(group['median_edge'])} | {pct(group['p10_edge'])} | "
            f"{group['n']} | {ref[0]:.0%}, {pct(ref[1])}, {pct(ref[2])} |"
        )
    out.append("")

    # Stability across sub-periods
    out += ["## Rank correlation with forward returns", "", "| Signal | Period | 1-yr | 3-yr | 5-yr |", "|---|---|---|---|---|"]
    signals = {"P/E (linked)": pe, "P/B (linked)": pb}
    if DY in data and not data[DY].dropna().empty:
        signals["Dividend yield"] = data[DY].dropna()
    for label, s in signals.items():
        for start, end in [(None, None)] + SUB_PERIODS:
            period = "all" if start is None else f"{start}–{end}"
            cells = []
            for h in history.HORIZONS:
                f = forward[h]
                rho = spearman(s.loc[start:end] if start else s, f.loc[start:end] if start else f)
                cells.append("–" if rho is None else f"{rho:+.2f}")
            out.append(f"| {label} | {period} | " + " | ".join(cells) + " |")
    out.append("")

    # Bootstrap intervals (expanding window)
    zones_daily = pd.Series([raw_zone(v).id for v in expanding_temp], index=expanding_temp.index)
    out += ["## Block-bootstrap 90% intervals for the median (expanding window)", "", "| Zone | 1-yr | 3-yr |", "|---|---|---|"]
    intervals = {h: block_bootstrap_medians(forward[h], zones_daily, h) for h in (1, 3)}
    for zone in ZONES:
        cells = []
        for h in (1, 3):
            ci = intervals[h].get(zone.id)
            cells.append("–" if not ci else f"{pct(ci[0])} to {pct(ci[1])}")
        out.append(f"| {zone.label} | " + " | ".join(cells) + " |")
    out.append("")

    report = Path(__file__).parent / "reports" / f"backtest-{METHOD_VERSION}.md"
    report.parent.mkdir(exist_ok=True)
    report.write_text("\n".join(out))
    print("\n".join(out))
    print(f"\nWrote {report}")


if __name__ == "__main__":
    main()
