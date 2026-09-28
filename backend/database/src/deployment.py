"""
Lump sum vs staggered investing, index level (plan sections 4.2 and 5.3).

backend/market/deployment.py precomputes, for each historical start date,
how much one rupee invested at each monthly tranche date (start + k months,
k = 0..11) had grown twelve months after the start. From those ratios this
module works out, for any plan length and any yield on the waiting cash:

- lump sum: everything invested at the start (ratio g0)
- staggered: 1/N invested at each of the first N monthly dates, the rest
  earning the cash yield until its turn: sum((1/N) * (1 + y)^(k/12) * g_k)

The method is the research scripts' (plans/backtest-reference/stp_adj.py).
Everything is described, never recommended: no fund names, no default plan.
"""

import math
from typing import Dict, Iterable, List, Optional, Sequence

PLANS = (3, 6, 12)
# Valuation temperature thirds, right-inclusive like the research (pd.cut at .33/.67)
THIRDS = [
    ("cheapest", "Cheapest third of valuations", 0.0, 33.0),
    ("middle", "Middle third", 33.0, 67.0),
    ("richest", "Richest third", 67.0, 100.0),
]
HIST_STEP = 0.05


def quantile(values: Sequence[float], q: float) -> Optional[float]:
    """Linear interpolation between closest ranks (pandas' default)."""
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def third_of(temperature: Optional[float]) -> Optional[str]:
    if temperature is None:
        return None
    for third_id, _, lo, hi in THIRDS:
        if (lo == 0.0 and temperature <= hi) or lo < temperature <= hi:
            return third_id
    return None


def outcomes(rows: Iterable[list], months: int, cash_yield: float) -> List[Dict]:
    """Growth of ₹1 after twelve months for each start: lump sum and staggered."""
    out = []
    weights = [(1.0 + cash_yield) ** (k / 12.0) / months for k in range(months)]
    for row in rows:
        day, temperature, ratios = row[0], row[1], row[2:]
        staged = sum(w * g for w, g in zip(weights, ratios[:months]))
        out.append({"d": day, "t": temperature, "lump": ratios[0], "staged": staged})
    return out


def _dist(values: List[float]) -> Dict:
    return {
        "p10": quantile(values, 0.1),
        "median": quantile(values, 0.5),
        "p90": quantile(values, 0.9),
        "pct_negative": sum(1 for v in values if v < 0) / len(values) if values else None,
    }


def summarise(results: List[Dict]) -> Optional[Dict]:
    if not results:
        return None
    edges = [r["lump"] / r["staged"] - 1.0 for r in results]
    lump = [r["lump"] - 1.0 for r in results]
    staged = [r["staged"] - 1.0 for r in results]
    return {
        "n": len(results),
        "distinct_years": len({r["d"][:4] for r in results}),
        "first_start": results[0]["d"],
        "last_start": results[-1]["d"],
        "lump_better_pct": sum(1 for r in results if r["lump"] > r["staged"]) / len(results),
        "median_edge": quantile(edges, 0.5),
        "p10_edge": quantile(edges, 0.1),
        "p90_edge": quantile(edges, 0.9),
        "lump": _dist(lump),
        "staged": _dist(staged),
        "histogram": histogram(lump, staged),
    }


def histogram(lump: List[float], staged: List[float]) -> Dict:
    """Both distributions of twelve-month returns on shared 5-point bins."""
    values = lump + staged
    lo = math.floor(min(values) / HIST_STEP) * HIST_STEP
    hi = math.ceil(max(values) / HIST_STEP) * HIST_STEP
    count = max(1, round((hi - lo) / HIST_STEP))
    edges = [round(lo + i * HIST_STEP, 4) for i in range(count + 1)]

    def counts(xs):
        bins = [0] * count
        for x in xs:
            bins[min(count - 1, int((x - lo) / HIST_STEP))] += 1
        return bins

    return {"edges": edges, "lump": counts(lump), "staged": counts(staged)}


def explore(table: Dict, months: int, cash_yield: float) -> Dict:
    """Everything the explorer shows for one plan length and cash yield."""
    if months not in PLANS:
        raise ValueError(f"months must be one of {list(PLANS)}")
    if not 0.0 <= cash_yield <= 0.15:
        raise ValueError("cash_yield must be between 0 and 0.15")
    results = outcomes(table["rows"], months, cash_yield)
    groups = [{"id": "all", "label": "All periods", **(summarise(results) or {"n": 0})}]
    if table.get("has_temperature"):
        for third_id, label, _, _ in THIRDS:
            members = [r for r in results if third_of(r["t"]) == third_id]
            groups.append({"id": third_id, "label": label, **(summarise(members) or {"n": 0})})
    current = table.get("current_temperature")
    return {
        "months": months,
        "cash_yield": cash_yield,
        "horizon_months": table["horizon_months"],
        "groups": groups,
        "current": {"temperature": current, "third": third_of(current)} if current is not None else None,
    }
