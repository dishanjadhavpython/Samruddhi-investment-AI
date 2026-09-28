"""
Builds the daily market_signals row and the Market page charts from stored
series. No LLM, no network, no database: everything here is deterministic and
unit-tested (plan section 8.4).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import breaks as break_checks
import deployment
import history
import indicators
from series import DY, METHOD_VERSION, PB, PE, SOURCE_NIFTY_INDICES, SOURCE_YAHOO, TRI, Break
from zones import HYSTERESIS, ZONES, raw_zone, zones_with_hysteresis

# Valuation data older than this (against the index date) is shown as stale
VALUATION_STALE_AFTER = timedelta(days=10)

# Charts: full resolution for the recent past, weekly before that
DAILY_CHART_YEARS = 2

METHOD = {
    "version": METHOD_VERSION,
    "window": "expanding",
    "window_years": None,
    "min_history_years": 3,
    "hysteresis_points": HYSTERESIS,
    "components": ["pe", "pb"],
}


@dataclass
class MarketData:
    nifty: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    vix: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    tri: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    pe: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    pb: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    dy: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    breaks: List[Break] = field(default_factory=list)


@dataclass
class Result:
    as_of: date
    valuation_score: Optional[float]
    zone: Optional[str]
    indicators: Dict
    history_stats: Optional[Dict]
    charts: Dict[str, Dict]


def _r(value, digits: int = 4) -> Optional[float]:
    if value is None:
        return None
    value = float(value)
    return None if np.isnan(value) else round(value, digits)


def _day(stamp) -> str:
    return pd.Timestamp(stamp).date().isoformat()


def _chart_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Weekly points for older history, every day for the last two years."""
    if index.empty:
        return index
    cutoff = index[-1] - pd.DateOffset(years=DAILY_CHART_YEARS)
    older = index[index < cutoff]
    weekly = pd.Series(older, index=older).groupby(older.to_period("W")).last()
    return pd.DatetimeIndex(list(weekly.values) + list(index[index >= cutoff]))


def _index_block(nifty: pd.Series) -> Optional[Dict]:
    s = nifty.dropna().sort_index()
    if s.empty:
        return None
    prev = s.iloc[-2] if len(s) > 1 else None
    return {
        "id": "NIFTY50",
        "name": "Nifty 50",
        "level": _r(s.iloc[-1], 2),
        "prev_close": _r(prev, 2),
        "change": _r(s.iloc[-1] - prev, 2) if prev else None,
        "change_pct": _r(s.iloc[-1] / prev - 1) if prev else None,
        "as_of": _day(s.index[-1]),
        "source": SOURCE_YAHOO,
        "delay": "end_of_day",
    }


def _turbulence_block(nifty: pd.Series, vix: pd.Series) -> Optional[Dict]:
    s = nifty.dropna().sort_index()
    if s.empty:
        return None
    dd = indicators.drawdown(s)
    dma = s.rolling(200).mean()
    vol = indicators.realised_volatility(s)
    block = {
        "as_of": _day(s.index[-1]),
        "series": "Nifty 50 price index",
        "drawdown_pct": _r(dd.iloc[-1]),
        "all_time_high": _r(s.cummax().iloc[-1], 2),
        "all_time_high_date": _day(s.idxmax()),
        "dma200": _r(dma.iloc[-1], 2),
        "dma200_distance_pct": _r(s.iloc[-1] / dma.iloc[-1] - 1) if not np.isnan(dma.iloc[-1]) else None,
        "above_200dma": bool(s.iloc[-1] > dma.iloc[-1]) if not np.isnan(dma.iloc[-1]) else None,
        "realised_vol_20d": _r(vol.iloc[-1]),
        "source": SOURCE_YAHOO,
        "vix": None,
    }
    v = vix.dropna().sort_index()
    if not v.empty:
        block["vix"] = {"value": _r(v.iloc[-1], 2), "as_of": _day(v.index[-1]), **indicators.vix_band(float(v.iloc[-1]))}
    return block


def compute(data: MarketData, today: date) -> Result:
    nifty = data.nifty.dropna().sort_index()
    pe_breaks = [b for b in data.breaks if b.series_id == PE]
    pb_breaks = [b for b in data.breaks if b.series_id == PB]
    pe_adj = indicators.chain_link(data.pe.dropna().sort_index(), pe_breaks)
    pb_adj = indicators.chain_link(data.pb.dropna().sort_index(), pb_breaks)
    dy = data.dy.dropna().sort_index()
    tri = data.tri.dropna().sort_index()

    index_block = _index_block(nifty)
    turbulence = _turbulence_block(nifty, data.vix)

    # Valuation temperature and its displayed zone
    temperature = indicators.valuation_temperature(pe_adj, pb_adj, METHOD["window_years"]) if not (pe_adj.empty and pb_adj.empty) else pd.Series(dtype=float)
    valuation: Dict = {"available": not temperature.empty, "method": METHOD}
    score = zone = None
    if not temperature.empty:
        labels = zones_with_hysteresis(temperature.tolist())
        score = _r(temperature.iloc[-1], 2)
        zone = labels[-1].id
        valuation_as_of = temperature.index[-1]
        reference = nifty.index[-1] if not nifty.empty else pd.Timestamp(today)
        pe_pct = indicators.walk_forward_percentile(pe_adj)
        pb_pct = indicators.walk_forward_percentile(pb_adj)
        valuation.update(
            {
                "as_of": _day(valuation_as_of),
                "stale": bool(reference - valuation_as_of > VALUATION_STALE_AFTER),
                "score": score,
                "zone": zone,
                "zone_label": labels[-1].label,
                "raw_zone": raw_zone(temperature.iloc[-1]).id,
                "history_from": _day(min(s.index[0] for s in (pe_adj, pb_adj) if not s.empty)),
                "source": SOURCE_NIFTY_INDICES,
                "components": [
                    {
                        "id": "pe",
                        "label": "P/E",
                        "value": _r(data.pe.dropna().iloc[-1], 2) if not data.pe.dropna().empty else None,
                        "adjusted": _r(pe_adj.iloc[-1], 2) if not pe_adj.empty else None,
                        "pct": _r(pe_pct.iloc[-1]) if not pe_pct.empty else None,
                        "as_of": _day(pe_adj.index[-1]) if not pe_adj.empty else None,
                    },
                    {
                        "id": "pb",
                        "label": "P/B",
                        "value": _r(data.pb.dropna().iloc[-1], 2) if not data.pb.dropna().empty else None,
                        "adjusted": _r(pb_adj.iloc[-1], 2) if not pb_adj.empty else None,
                        "pct": _r(pb_pct.iloc[-1]) if not pb_pct.empty else None,
                        "as_of": _day(pb_adj.index[-1]) if not pb_adj.empty else None,
                    },
                ],
                "dividend_yield": {"value": _r(dy.iloc[-1], 2), "as_of": _day(dy.index[-1])} if not dy.empty else None,
            }
        )

    # Breaks: the registry, plus anything the detector finds that isn't in it
    move_basis = tri if not tri.empty else nifty
    candidates = []
    for series_id, raw in ((PE, data.pe), (PB, data.pb)):
        found = break_checks.detect_breaks(raw.dropna().sort_index(), move_basis)
        for c in break_checks.unregistered(found, data.breaks, series_id):
            candidates.append({"series_id": series_id, **c})
    registered = [
        {"series_id": b.series_id, "date": b.break_date.isoformat(), "factor": b.factor, "note": b.note} for b in data.breaks
    ]

    history_stats = history.zone_table(temperature, tri) if not tri.empty else None
    if history_stats:
        history_stats["method_version"] = METHOD_VERSION

    as_of_candidates = [s.index[-1] for s in (nifty, temperature) if not s.empty]
    as_of = max(as_of_candidates).date() if as_of_candidates else today

    indicator_block = {
        "index": index_block,
        "valuation": valuation,
        "turbulence": turbulence,
        "breaks": {"registered": registered, "unregistered_candidates": candidates},
        "coverage": {
            "nifty": [_day(nifty.index[0]), _day(nifty.index[-1])] if not nifty.empty else None,
            "vix": [_day(data.vix.dropna().index[0]), _day(data.vix.dropna().index[-1])] if not data.vix.dropna().empty else None,
            "tri": [_day(tri.index[0]), _day(tri.index[-1])] if not tri.empty else None,
            "pe": [_day(pe_adj.index[0]), _day(pe_adj.index[-1])] if not pe_adj.empty else None,
            "pb": [_day(pb_adj.index[0]), _day(pb_adj.index[-1])] if not pb_adj.empty else None,
        },
    }

    charts = {
        "valuation": _valuation_chart(pe_adj, pb_adj, temperature, registered),
        "turbulence": _turbulence_chart(nifty, data.vix),
        "perspective": _perspective_chart(tri, nifty, pe_adj, pb_adj, dy, today),
        "deployment": _deployment_chart(tri, nifty, temperature, as_of),
    }
    return Result(as_of, score, zone, indicator_block, history_stats, charts)


def _table(fields: List[str], rows: List[list]) -> Dict:
    """Chart points as a field list plus one array per date (date first).

    Much smaller than one object per point, which keeps each chart row far
    under the Data API's 1 MiB response limit.
    """
    return {"fields": fields, "rows": rows}


def _valuation_chart(pe_adj: pd.Series, pb_adj: pd.Series, temperature: pd.Series, registered: List[Dict]) -> Dict:
    if pe_adj.empty and pb_adj.empty:
        return {"available": False}
    index = pe_adj.index.union(pb_adj.index)
    dates = _chart_dates(index)
    pe_bands = indicators.walk_forward_quantiles(pe_adj, dates)
    pb_bands = indicators.walk_forward_quantiles(pb_adj, dates)
    pe_at = pe_adj.reindex(dates, method="ffill")
    pb_at = pb_adj.reindex(dates, method="ffill")
    temp_at = temperature.reindex(dates)
    band_columns = list(pe_bands.columns)
    fields = ["d", "pe", "pb", "t"] + [f"pe_{c}" for c in band_columns] + [f"pb_{c}" for c in band_columns]
    rows = []
    for stamp in dates:
        row = [_day(stamp), _r(pe_at.get(stamp), 2), _r(pb_at.get(stamp), 3), _r(temp_at.get(stamp), 1)]
        row += [_r(pe_bands.at[stamp, c], 2) for c in band_columns]
        row += [_r(pb_bands.at[stamp, c], 3) for c in band_columns]
        rows.append(row)
    return {
        "available": True,
        "adjusted": True,
        "source": SOURCE_NIFTY_INDICES,
        "breaks": registered,
        "zones": [{"id": z.id, "label": z.label, "lo": z.lo, "hi": z.hi} for z in ZONES],
        **_table(fields, rows),
    }


def _turbulence_chart(nifty: pd.Series, vix: pd.Series) -> Dict:
    s = nifty.dropna().sort_index()
    if s.empty:
        return {"available": False}
    dd = indicators.drawdown(s)
    dma = s.rolling(200).mean()
    v = vix.dropna().sort_index()
    return {
        "available": True,
        "source": SOURCE_YAHOO,
        "series": "Nifty 50 price index",
        **_table(["d", "level", "dd", "dma"], [[_day(d), _r(s[d], 2), _r(dd[d]), _r(dma[d], 2)] for d in _chart_dates(s.index)]),
        "vix": _table(["d", "v"], [[_day(d), _r(v[d], 2)] for d in _chart_dates(v.index)]) if not v.empty else None,
        "vix_bands": [{"below": b[0] if np.isfinite(b[0]) else None, "id": b[1], "label": b[2]} for b in indicators.VIX_BANDS],
    }


def _perspective_chart(tri: pd.Series, nifty: pd.Series, pe_adj: pd.Series, pb_adj: pd.Series, dy: pd.Series, today: date) -> Dict:
    # Total returns when the TRI has been loaded; otherwise the price index
    base, label, source = (tri, "Nifty 50 Total Return Index", SOURCE_NIFTY_INDICES) if not tri.empty else (nifty, "Nifty 50 price index", SOURCE_YAHOO)
    if base.empty:
        return {"available": False}
    last_full_year = today.year - 1
    return {
        "available": True,
        "series": label,
        "source": source,
        "intra_year": history.intra_year(base, last_full_year),
        "entry_year": history.entry_year_triangle(base, last_full_year),
        "cycle": history.cycle_table({"pe": pe_adj, "pb": pb_adj, "dy": dy}, base),
    }


def _deployment_chart(tri: pd.Series, nifty: pd.Series, temperature: pd.Series, as_of: date) -> Dict:
    # Total returns when the TRI has been loaded; otherwise the price index
    base, label, source = (tri, "Nifty 50 Total Return Index", SOURCE_NIFTY_INDICES) if not tri.empty else (nifty, "Nifty 50 price index", SOURCE_YAHOO)
    if base.empty:
        return {"available": False}
    return deployment.build_table(base, label, source, temperature, as_of)
