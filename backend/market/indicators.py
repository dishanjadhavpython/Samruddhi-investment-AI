"""
Deterministic market indicators (plan sections 5.1 and 8.4).

Pure functions over pandas Series indexed by date. The formulas match the
research scripts in plans/backtest-reference/ so the zone table can be
reproduced from them.
"""

import math
from typing import Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

from series import Break

# A percentile needs at least this much history before it means anything
MIN_HISTORY_DAYS = 3 * 365

# India VIX bands (plan section 4.1). They describe current turbulence only.
VIX_BANDS = [
    (13.0, "calm", "Calm"),
    (17.0, "normal", "Normal"),
    (25.0, "nervous", "Nervous"),
    (math.inf, "elevated", "Elevated"),
]


def _window_starts(dates: np.ndarray, window_years: Optional[float]) -> np.ndarray:
    if not window_years:
        return np.zeros(len(dates), dtype=int)
    span = np.timedelta64(int(round(365.25 * window_years)), "D")
    return np.searchsorted(dates, dates - span, side="left")


def walk_forward_percentile(
    series: pd.Series,
    window_years: Optional[float] = None,
    min_history_days: int = MIN_HISTORY_DAYS,
) -> pd.Series:
    """Each day's value ranked only against history up to that day.

    Returns the share of observations in the window (expanding when
    window_years is None) that are at or below the day's value, from 0 to 1.
    Days with less than min_history_days of history since the series started
    are NaN. Nothing looks ahead.
    """
    s = series.dropna().sort_index()
    if s.empty:
        return pd.Series(dtype=float)
    values = s.to_numpy(dtype=float)
    dates = s.index.values
    first_allowed = dates[0] + np.timedelta64(min_history_days, "D")
    starts = _window_starts(dates, window_years)

    out = np.full(len(values), np.nan)
    for i in range(len(values)):
        if dates[i] < first_allowed:
            continue
        window = values[starts[i] : i + 1]
        out[i] = np.count_nonzero(window <= values[i]) / len(window)
    return pd.Series(out, index=s.index)


def walk_forward_quantiles(
    series: pd.Series,
    at: Iterable[pd.Timestamp],
    quantiles: Sequence[float] = (0.1, 0.25, 0.5, 0.75, 0.9),
    window_years: Optional[float] = None,
    min_history_days: int = MIN_HISTORY_DAYS,
) -> pd.DataFrame:
    """Percentile bands as they stood on each date in `at`, using only past data."""
    s = series.dropna().sort_index()
    at = pd.DatetimeIndex(list(at))
    columns = [f"p{round(q * 100)}" for q in quantiles]
    out = pd.DataFrame(np.nan, index=at, columns=columns)
    if s.empty:
        return out
    values = s.to_numpy(dtype=float)
    dates = s.index.values
    first_allowed = dates[0] + np.timedelta64(min_history_days, "D")
    span = np.timedelta64(int(round(365.25 * window_years)), "D") if window_years else None
    for stamp in at:
        day = np.datetime64(stamp)
        if day < first_allowed:
            continue
        end = np.searchsorted(dates, day, side="right")
        start = np.searchsorted(dates, day - span, side="left") if span is not None else 0
        if end - start < 2:
            continue
        out.loc[stamp] = np.quantile(values[start:end], quantiles)
    return out


def chain_link(series: pd.Series, breaks: List[Break]) -> pd.Series:
    """Put history before each methodology break on the current basis."""
    adjusted = series.astype(float).copy()
    for b in breaks:
        before = adjusted.index < pd.Timestamp(b.break_date)
        adjusted[before] = adjusted[before] * b.factor
    return adjusted


def valuation_temperature(
    pe_adjusted: pd.Series,
    pb_adjusted: pd.Series,
    window_years: Optional[float] = None,
) -> pd.Series:
    """0-100: the average walk-forward percentile of chain-linked P/E and P/B.

    0 means cheaper than all history to date, 100 pricier than all of it.
    If only one component has a percentile on a day, that one is used.
    """
    pct = pd.concat(
        [
            walk_forward_percentile(pe_adjusted, window_years),
            walk_forward_percentile(pb_adjusted, window_years),
        ],
        axis=1,
    ).mean(axis=1)
    return (pct * 100).dropna()


def forward_cagr(series: pd.Series, years: float) -> pd.Series:
    """Annualised return from each day to the first observation `years` later.

    NaN where that future date is beyond the data.
    """
    s = series.dropna().sort_index()
    target = s.index + pd.Timedelta(days=int(round(365.25 * years)))
    idx = s.index.searchsorted(target)
    out = pd.Series(np.nan, index=s.index)
    ok = idx < len(s)
    values = s.to_numpy(dtype=float)
    out[ok] = (values[idx[ok]] / values[ok]) ** (1 / years) - 1
    out[target > s.index[-1]] = np.nan
    return out


def drawdown(series: pd.Series) -> pd.Series:
    """Fall from the running all-time high, as a fraction (0 at a new high)."""
    s = series.dropna().sort_index()
    return s / s.cummax() - 1


def dma_distance(series: pd.Series, window: int = 200) -> pd.Series:
    """Distance from the trailing moving average, as a fraction."""
    s = series.dropna().sort_index()
    return s / s.rolling(window).mean() - 1


def realised_volatility(series: pd.Series, window: int = 20) -> pd.Series:
    """Annualised standard deviation of daily log returns over the window."""
    s = series.dropna().sort_index()
    return np.log(s).diff().rolling(window).std() * math.sqrt(252)


def vix_band(value: float) -> dict:
    for upper, band_id, label in VIX_BANDS:
        if value < upper:
            return {"id": band_id, "label": label}
    return {"id": VIX_BANDS[-1][1], "label": VIX_BANDS[-1][2]}
