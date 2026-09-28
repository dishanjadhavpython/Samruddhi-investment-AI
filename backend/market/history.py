"""
What happened after each valuation zone, and other perspective statistics
(plan sections 4.1 and 5.2).

Every statistic is a range over past periods, reported with how many days,
distinct years and non-overlapping episodes sit behind it. None of it is a
forecast.
"""

from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from indicators import forward_cagr
from zones import ZONES, raw_zone

HORIZONS = (1, 3, 5)

# Windows used to find the three big market lows since 1999
CYCLE_LOW_WINDOWS = [
    ("2003", "2002-06-01", "2003-12-31"),
    ("2009", "2008-01-01", "2009-12-31"),
    ("2020", "2020-01-01", "2020-12-31"),
]


def _round(value, digits: int = 4) -> Optional[float]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return round(float(value), digits)


def count_episodes(dates: pd.DatetimeIndex, years: int) -> int:
    """Non-overlapping windows of `years` that start on one of these dates.

    Overlapping daily windows are not independent; this is the honest count.
    """
    count = 0
    next_start = None
    for day in sorted(dates):
        if next_start is None or day >= next_start:
            count += 1
            next_start = day + pd.DateOffset(years=years)
    return count


def horizon_stats(returns: pd.Series, years: float) -> Dict:
    r = returns.dropna()
    if r.empty:
        return {"n_days": 0, "distinct_years": 0, "episodes": 0, "median": None, "p10": None, "p90": None, "pct_negative": None}
    return {
        "median": _round(r.median()),
        "p10": _round(r.quantile(0.1)),
        "p90": _round(r.quantile(0.9)),
        "pct_negative": _round((r < 0).mean()),
        "n_days": int(len(r)),
        "distinct_years": int(r.index.year.nunique()),
        "episodes": count_episodes(r.index, years),
    }


def zone_table(temperature: pd.Series, total_return: pd.Series, horizons: Sequence[int] = HORIZONS) -> Optional[Dict]:
    """Forward total returns grouped by the valuation zone on the start day.

    temperature is 0-100; total_return is the Nifty 50 TRI. Uses the raw zone
    (no hysteresis), as in the research.
    """
    tri = total_return.dropna().sort_index()
    if tri.empty or temperature.dropna().empty:
        return None
    frame = tri.rename("tri").to_frame().join(temperature.rename("temp"), how="left")
    for h in horizons:
        frame[f"f{h}"] = forward_cagr(tri, h)
    frame = frame.dropna(subset=["temp"])
    if frame.empty:
        return None
    frame["zone"] = [raw_zone(score).id for score in frame["temp"]]

    zones = []
    for zone in ZONES:
        in_zone = frame[frame["zone"] == zone.id]
        entry = {
            "id": zone.id,
            "label": zone.label,
            "lo": zone.lo,
            "hi": zone.hi,
            "share_of_days": _round(len(in_zone) / len(frame)),
        }
        for h in horizons:
            entry[f"h{h}"] = horizon_stats(in_zone[f"f{h}"], h)
        zones.append(entry)

    return {
        "horizons": list(horizons),
        "data_from": frame.index[0].date().isoformat(),
        "data_to": tri.index[-1].date().isoformat(),
        "series": "Nifty 50 Total Return Index",
        "zones": zones,
    }


def intra_year(series: pd.Series, last_full_year: Optional[int] = None) -> List[Dict]:
    """Each complete calendar year's return and its deepest fall along the way."""
    s = series.dropna().sort_index()
    if s.empty:
        return []
    last_full_year = last_full_year or s.index[-1].year - 1
    rows = []
    for year, values in s.groupby(s.index.year):
        prior = s[s.index.year < year]
        if prior.empty or year > last_full_year:
            continue
        base = prior.iloc[-1]
        path = np.concatenate([[base], values.to_numpy(dtype=float)])
        fall = (path / np.maximum.accumulate(path) - 1).min()
        rows.append({"year": int(year), "calendar_return": _round(values.iloc[-1] / base - 1), "intra_year_fall": _round(fall)})
    return rows


def entry_year_triangle(series: pd.Series, last_full_year: Optional[int] = None) -> List[Dict]:
    """Annualised return for every entry year and holding period, year-end to year-end."""
    s = series.dropna().sort_index()
    if s.empty:
        return []
    last_full_year = last_full_year or s.index[-1].year - 1
    year_end = s.groupby(s.index.year).last()
    first_entry = year_end.index[0] + 1  # needs the prior year-end as a base
    cells = []
    for entry in range(first_entry, last_full_year + 1):
        base = year_end.get(entry - 1)
        for exit_year in range(entry, last_full_year + 1):
            held = exit_year - entry + 1
            cells.append({"entry": int(entry), "years": held, "cagr": _round((year_end[exit_year] / base) ** (1 / held) - 1)})
    return cells


def _value_on(series: pd.Series, day: pd.Timestamp) -> Optional[float]:
    s = series.dropna().sort_index()
    upto = s[s.index <= day]
    return float(upto.iloc[-1]) if not upto.empty else None


def cycle_table(metrics: Dict[str, pd.Series], price: pd.Series) -> Optional[Dict]:
    """Today's valuation against its long-term median and the big market lows."""
    p = price.dropna().sort_index()
    if p.empty or not any(not m.dropna().empty for m in metrics.values()):
        return None
    lows = []
    for name, start, end in CYCLE_LOW_WINDOWS:
        window = p.loc[start:end]
        if window.empty or window.index[0] > pd.Timestamp(start) + pd.Timedelta(days=31):
            continue  # the data doesn't cover this low
        lows.append({"name": name, "date": window.idxmin().date().isoformat(), "stamp": window.idxmin()})

    rows = []
    for metric_id, values in metrics.items():
        s = values.dropna().sort_index()
        if s.empty:
            continue
        at_lows = [v for v in (_value_on(s, low["stamp"]) for low in lows) if v is not None]
        rows.append(
            {
                "id": metric_id,
                "current": _round(s.iloc[-1], 2),
                "as_of": s.index[-1].date().isoformat(),
                "median": _round(s.median(), 2),
                "at_lows": _round(np.mean(at_lows), 2) if at_lows else None,
                "since": s.index[0].date().isoformat(),
            }
        )
    return {"lows": [{"name": low["name"], "date": low["date"]} for low in lows], "rows": rows}
