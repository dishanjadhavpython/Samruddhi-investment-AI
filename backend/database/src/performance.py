"""
The Performance view's numbers (GET /api/portfolio/performance).

A pure function over data the API has already loaded: the user's ledger
rows, current prices, daily closes and a Nifty 50 series. It measures the
user's own holdings (not the cash beside them) and compares them with the
Nifty 50 bought and sold with the same rupees on the same dates.

Conventions, shown in the UI:
- Returns over less than a year are absolute; XIRR (annualised) is given only
  once the money has been invested for a year, as mutual funds must show them.
- A holding with no known cost or no price history is left out of every
  number (value, cost and flows alike) and listed under coverage.
"""

from datetime import date, timedelta
from typing import Dict, List, Optional

from .returns import (
    EPSILON,
    Series,
    Txn,
    benchmark_path,
    holding_flows,
    replay,
    same_flows_benchmark,
    value_history,
    xirr,
)

RANGES = {"1m": 31, "3m": 92, "6m": 183, "1y": 366, "3y": 1096, "all": None}
MAX_POINTS = 400
XIRR_MIN_DAYS = 365

INDEX_LABELS = {
    "NIFTY50_TRI": ("Nifty 50 Total Return Index", "Includes dividends, like your holdings' returns."),
    "NIFTY50": ("Nifty 50 (price index)",
                "The price index leaves out dividends (about 1–1.5% a year), so the comparison flatters your holdings slightly."),
}


def _gain(flows, end_value: float) -> Dict:
    paid_in = -sum(a for _, a in flows if a < 0)
    paid_out = sum(a for _, a in flows if a > 0)
    gain = end_value + paid_out - paid_in
    return {"paid_in": paid_in, "paid_out": paid_out, "gain": gain,
            "abs_return_pct": gain / paid_in if paid_in > EPSILON else None}


def _thin(rows: List[Dict]) -> List[Dict]:
    if len(rows) <= MAX_POINTS:
        return rows
    step = len(rows) / MAX_POINTS
    keep = sorted({int(i * step) for i in range(MAX_POINTS)} | {len(rows) - 1})
    return [rows[i] for i in keep]


def _r(value: Optional[float], digits: int = 2) -> Optional[float]:
    return None if value is None else round(value, digits)


def compute(
    txns: List[Txn],
    current_prices: Dict[str, Optional[float]],
    closes: Dict[str, Series],
    indices: Dict[str, Series],
    today: date,
    range_key: str = "1y",
    opening_estimates: Optional[List[str]] = None,
) -> Dict:
    if range_key not in RANGES:
        raise ValueError(f"range must be one of {list(RANGES)}")
    holdings = replay(txns)
    held = {s: h for s, h in holdings.items() if h.quantity > EPSILON}
    if not txns:
        return {"available": False, "reason": "no_transactions"}

    # Which symbols can be measured
    excluded = []
    for symbol in sorted(holdings):
        h = holdings[symbol]
        if h.unknown_cost:
            excluded.append({"symbol": symbol, "reason": "unknown_cost"})
        elif not closes.get(symbol) or (symbol in held and not current_prices.get(symbol)):
            excluded.append({"symbol": symbol, "reason": "no_prices"})
    skip = {e["symbol"] for e in excluded}
    measured = [t for t in txns if t.symbol and t.symbol not in skip]
    flows = holding_flows(measured)
    if not flows:
        return {"available": False, "reason": "nothing_measurable", "coverage": {"excluded": excluded}}

    market_value = sum(h.quantity * current_prices[s] for s, h in held.items() if s not in skip)
    cost_basis = sum(h.cost_basis for s, h in held.items() if s not in skip)
    since = min(d for d, _ in flows)
    period_days = (today - since).days
    portfolio_xirr = xirr(flows + [(today, market_value)])
    totals = _gain(flows, market_value)

    # Benchmark: the total return index when it covers every flow, else the price index
    benchmark = None
    for series_id in ("NIFTY50_TRI", "NIFTY50"):
        index = indices.get(series_id)
        if index and index.first <= since:
            result = same_flows_benchmark(flows, index, today)
            if result:
                label, note = INDEX_LABELS[series_id]
                bench_totals = _gain(flows, result["value"])
                benchmark = {
                    "id": series_id, "label": label, "note": note, "as_of": index.last.isoformat(),
                    "value": _r(result["value"]), "gain": _r(bench_totals["gain"]),
                    "abs_return_pct": _r(bench_totals["abs_return_pct"], 6),
                    "xirr": _r(result["xirr"], 6) if period_days >= XIRR_MIN_DAYS else None,
                    "series": index,
                }
                break

    # Chart: from the later of the range start and the first day every measured holding has a close
    measured_symbols = sorted({t.symbol for t in measured})
    first_close = max(closes[s].first for s in measured_symbols)
    span = RANGES[range_key]
    start = max(since, first_close, today - timedelta(days=span) if span else since)
    days = sorted({d for s in measured_symbols for d in closes[s].dates if start <= d <= today})
    series_rows = []
    if days:
        history = value_history(measured, {s: closes[s] for s in measured_symbols}, days)
        bench_path = benchmark_path(flows, benchmark["series"], days) if benchmark else [None] * len(days)
        for row, bench in zip(history, bench_path):
            if row["value"] is None:
                continue
            series_rows.append([row["d"].isoformat(), _r(row["value"]), _r(row["invested"]), _r(bench)])

    per_holding = []
    for symbol in measured_symbols:
        own = [t for t in measured if t.symbol == symbol]
        h = holdings[symbol]
        value = h.quantity * current_prices[symbol] if symbol in held else 0.0
        own_flows = holding_flows(own)
        own_since = min(d for d, _ in own_flows) if own_flows else today
        g = _gain(own_flows, value)
        per_holding.append({
            "symbol": symbol,
            "quantity": _r(h.quantity, 6),
            "avg_cost": _r(h.avg_cost, 4),
            "cost_basis": _r(h.cost_basis),
            "market_value": _r(value),
            "unrealised": _r(value - h.cost_basis) if symbol in held else None,
            "realised": _r(h.realised),
            "dividends": _r(h.dividends),
            "abs_return_pct": _r(g["abs_return_pct"], 6),
            "xirr": _r(xirr(own_flows + [(today, value)]), 6) if (today - own_since).days >= XIRR_MIN_DAYS else None,
            "since": own_since.isoformat(),
        })

    if benchmark:
        benchmark.pop("series")
    return {
        "available": True,
        "as_of": today.isoformat(),
        "range": range_key,
        "since": since.isoformat(),
        "period_days": period_days,
        "summary": {
            "market_value": _r(market_value),
            "cost_basis": _r(cost_basis),
            "unrealised": _r(market_value - cost_basis),
            "realised": _r(sum(h.realised for s, h in holdings.items() if s not in skip)),
            "dividends": _r(sum(h.dividends for s, h in holdings.items() if s not in skip)),
            "paid_in": _r(totals["paid_in"]),
            "paid_out": _r(totals["paid_out"]),
            "gain": _r(totals["gain"]),
            "abs_return_pct": _r(totals["abs_return_pct"], 6),
            "xirr": _r(portfolio_xirr, 6) if period_days >= XIRR_MIN_DAYS else None,
            "xirr_min_days": XIRR_MIN_DAYS,
        },
        "benchmark": benchmark,
        "series": {"fields": ["d", "value", "invested", "benchmark"], "rows": _thin(series_rows)},
        "holdings": per_holding,
        "coverage": {
            "holdings_total": len(holdings),
            "holdings_measured": len(measured_symbols),
            "excluded": excluded,
            "opening_estimates": sorted(set(opening_estimates or []) - skip),
            "chart_from": start.isoformat() if series_rows else None,
        },
    }
