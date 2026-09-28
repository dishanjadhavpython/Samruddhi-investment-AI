"""
Methodology-break detection for published valuation series (plan section 5.1).

NSE changes the basis of its P/E and P/B series without notice. A valuation
move of more than 6% on a day the index moved less than 1% is almost never
real, so it is flagged for a person to review. Flagged dates are never
chain-linked automatically: a break is applied only once it is registered.
"""

from typing import Dict, List

import pandas as pd

from series import Break

VALUATION_MOVE = 0.06
PRICE_MOVE = 0.01


def detect_breaks(
    valuation: pd.Series,
    price: pd.Series,
    valuation_move: float = VALUATION_MOVE,
    price_move: float = PRICE_MOVE,
) -> List[Dict]:
    """Days where the valuation series jumped but the index barely moved."""
    joined = pd.concat([valuation.rename("v"), price.rename("p")], axis=1, join="inner").dropna().sort_index()
    if len(joined) < 2:
        return []
    change = joined.pct_change()
    hits = change[(change["v"].abs() > valuation_move) & (change["p"].abs() < price_move)]
    candidates = []
    for day, row in hits.iterrows():
        position = joined.index.get_loc(day)
        candidates.append(
            {
                "date": day.date().isoformat(),
                "valuation_change": round(float(row["v"]), 4),
                "price_change": round(float(row["p"]), 4),
                "factor": round(float(joined["v"].iloc[position] / joined["v"].iloc[position - 1]), 6),
            }
        )
    return candidates


def unregistered(candidates: List[Dict], breaks: List[Break], series_id: str) -> List[Dict]:
    """Candidates that no registered break explains."""
    registered = {b.break_date.isoformat() for b in breaks if b.series_id == series_id}
    return [c for c in candidates if c["date"] not in registered]
