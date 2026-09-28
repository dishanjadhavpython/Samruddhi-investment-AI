"""
Precomputes the lump sum vs staggered table for the explorer (plan 4.2, 5.3).

For each start date, the growth of ₹1 invested at start + k months
(k = 0..11), measured twelve months after the start. The API turns these
ratios into any plan length (3, 6 or 12 monthly instalments) and any yield
on the waiting cash (backend/database/src/deployment.py), so nothing is
recomputed per request. Method: plans/backtest-reference/stp_adj.py.

Data stops 30 days before the latest close, per SEBI's rule for price data
used in education (circular of 8 May 2026).
"""

from datetime import date, timedelta
from typing import Dict, Optional

import numpy as np
import pandas as pd

HORIZON_MONTHS = 12
TRANCHES = 12
EMBARGO_DAYS = 30
# Weekly starts keep the stored table small; daily starts are used for research
STEP_TRADING_DAYS = 5


def growth_ratios(base: pd.Series, step: int = STEP_TRADING_DAYS) -> pd.DataFrame:
    """Rows: start dates. Columns g0..g11: end value / value at tranche k."""
    s = base.dropna().sort_index()
    s = s[s > 0]
    if len(s) < 300:
        return pd.DataFrame()
    index, values = s.index, s.to_numpy()
    last_start = index[-1] - pd.DateOffset(months=HORIZON_MONTHS)
    starts = index[index <= last_start][::step]
    records, kept = [], []
    for start in starts:
        end_pos = index.searchsorted(start + pd.DateOffset(months=HORIZON_MONTHS))
        if end_pos >= len(index):
            continue
        tranche_pos = index.searchsorted([start + pd.DateOffset(months=k) for k in range(TRANCHES)])
        records.append(values[end_pos] / values[tranche_pos])
        kept.append(start)
    return pd.DataFrame(records, index=pd.DatetimeIndex(kept), columns=[f"g{k}" for k in range(TRANCHES)])


def build_table(base: pd.Series, label: str, source: str, temperature: pd.Series, as_of: date,
                step: int = STEP_TRADING_DAYS) -> Dict:
    """The market_charts 'deployment' payload."""
    data_until = as_of - timedelta(days=EMBARGO_DAYS)
    base = base.dropna().sort_index()
    base = base[base.index <= pd.Timestamp(data_until)]
    ratios = growth_ratios(base, step)
    if ratios.empty:
        return {"available": False}
    temp = temperature.dropna().sort_index()
    has_temperature = not temp.empty
    at_start = temp.reindex(ratios.index, method="ffill", tolerance=pd.Timedelta(days=7)) if has_temperature else None
    rows = []
    for start, g in ratios.iterrows():
        t = at_start.get(start) if at_start is not None else None
        t = None if t is None or np.isnan(t) else round(float(t), 1)
        rows.append([start.date().isoformat(), t] + [round(float(x), 6) for x in g.to_numpy()])
    current: Optional[float] = round(float(temp.iloc[-1]), 1) if has_temperature else None
    return {
        "available": True,
        "series": label,
        "source": source,
        "data_until": base.index[-1].date().isoformat(),
        "horizon_months": HORIZON_MONTHS,
        "tranches": TRANCHES,
        "step_trading_days": step,
        "has_temperature": bool(has_temperature and any(r[1] is not None for r in rows)),
        "current_temperature": current,
        "fields": ["d", "t"] + [f"g{k}" for k in range(TRANCHES)],
        "rows": rows,
    }
