"""
Unit tests for the market pipeline. Synthetic data only: no AWS, no network,
no NSE files.

    uv run test_market.py
"""

import json
import math
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import breaks
import deployment
import history
import indicators
import nse_files
import signals
from series import DY, PB, PE, TRI, Break
from sources import final_closes
from zones import ZONES, raw_zone, zones_with_hysteresis


def days(start: str, end: str) -> pd.DatetimeIndex:
    return pd.bdate_range(start, end)


def near(a, b, tol=1e-9) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def test_percentile_waits_for_three_years_and_never_looks_ahead():
    idx = days("2010-01-01", "2016-12-31")
    rising = pd.Series(np.arange(len(idx), dtype=float), index=idx)
    pct = indicators.walk_forward_percentile(rising)
    assert pct[: "2012-12-30"].isna().all(), "percentiles before 3 years of history must be NaN"
    assert (pct["2013-01-02":] == 1.0).all(), "a new high is at the 100th percentile of its own past"

    changed = rising.copy()
    changed.iloc[-1] = -1000.0  # change only the last day
    again = indicators.walk_forward_percentile(changed)
    assert again.iloc[:-1].equals(pct.iloc[:-1]), "a later value must not change earlier percentiles"
    assert again.iloc[-1] == 1 / len(idx)


def test_rolling_window_forgets_old_history():
    idx = days("2000-01-01", "2012-12-31")
    values = pd.Series(100.0, index=idx)
    values["2006-01-01":] = 10.0
    values.iloc[-1] = 50.0
    expanding = indicators.walk_forward_percentile(values).iloc[-1]
    rolling = indicators.walk_forward_percentile(values, window_years=3).iloc[-1]
    assert 0.4 < expanding < 0.6, expanding  # half the history is 100s
    assert rolling == 1.0, rolling  # the last 3 years are all 10s


def test_quantile_bands_use_only_the_past():
    idx = days("2000-01-01", "2010-12-31")
    s = pd.Series(np.arange(len(idx), dtype=float), index=idx)
    at = [pd.Timestamp("2002-06-03"), pd.Timestamp("2005-01-03"), pd.Timestamp("2010-12-31")]
    bands = indicators.walk_forward_quantiles(s, at)
    assert bands.loc[at[0]].isna().all()
    upto = s[: at[1]]
    assert near(bands.at[at[1], "p50"], float(np.quantile(upto, 0.5)))


def test_chain_link_scales_only_before_the_break():
    idx = pd.to_datetime(["2021-03-29", "2021-03-30", "2021-03-31", "2021-04-01"])
    pe = pd.Series([40.0, 40.4, 33.2, 33.5], index=idx)
    adj = indicators.chain_link(pe, [Break(PE, date(2021, 3, 31), 0.821172, "")])
    assert near(adj.iloc[0], 40.0 * 0.821172)
    assert adj.iloc[2] == 33.2 and adj.iloc[3] == 33.5


def test_forward_cagr_matches_a_known_growth_rate():
    idx = pd.date_range("2000-01-01", "2010-12-31", freq="D")
    years = (idx - idx[0]).days / 365.25
    s = pd.Series(100 * 1.10**years, index=idx)
    f1 = indicators.forward_cagr(s, 1)
    f5 = indicators.forward_cagr(s, 5)
    assert abs(f1.iloc[0] - 0.10) < 0.001 and abs(f5.iloc[0] - 0.10) < 0.001
    assert f1.iloc[-1] != f1.iloc[-1], "no forward return past the end of the data"


def test_drawdown_dma_and_volatility():
    s = pd.Series([100.0, 120.0, 90.0, 108.0], index=days("2020-01-01", "2020-01-06"))
    dd = indicators.drawdown(s)
    assert near(dd.iloc[2], -0.25) and near(dd.iloc[1], 0.0)
    flat = pd.Series(100.0, index=days("2019-01-01", "2020-12-31"))
    assert indicators.dma_distance(flat).iloc[-1] == 0.0
    assert indicators.realised_volatility(flat).iloc[-1] == 0.0


def test_vix_bands():
    assert indicators.vix_band(12.99)["id"] == "calm"
    assert indicators.vix_band(13.0)["id"] == "normal"
    assert indicators.vix_band(17.0)["id"] == "nervous"
    assert indicators.vix_band(25.0)["id"] == "elevated"


# ---------------------------------------------------------------------------
# Breaks and zones
# ---------------------------------------------------------------------------

def test_detector_flags_valuation_jumps_the_index_does_not_explain():
    idx = days("2023-09-25", "2023-10-06")
    price = pd.Series(100.0, index=idx)
    pb = pd.Series(4.3, index=idx)
    pb["2023-09-29":] = 3.45  # -19.8% on a flat index: a break
    price["2023-10-04":] = 94.0
    pb["2023-10-04":] = 3.45 * 0.93  # -7% with a -6% index move: real
    found = breaks.detect_breaks(pb, price)
    assert [c["date"] for c in found] == ["2023-09-29"], found
    assert near(found[0]["factor"], 3.45 / 4.3, 1e-6)
    known = [Break(PB, date(2023, 9, 29), 0.802784, "")]
    assert breaks.unregistered(found, known, PB) == []
    assert breaks.unregistered(found, known, PE) == found


def test_zone_bands_are_right_inclusive():
    assert raw_zone(0).id == "much_cheaper"
    assert raw_zone(20).id == "much_cheaper"
    assert raw_zone(20.01).id == "cheaper"
    assert raw_zone(60).id == "typical"
    assert raw_zone(100).id == "much_pricier"


def test_hysteresis_stops_the_label_flickering():
    labels = [z.id for z in zones_with_hysteresis([50, 61, 63, 63.5, 58, 57.5, 57])]
    assert labels == ["typical", "typical", "typical", "pricier", "pricier", "pricier", "typical"], labels
    kept = zones_with_hysteresis([50, float("nan"), None, 52])
    assert all(z.id == "typical" for z in kept)


# ---------------------------------------------------------------------------
# History tables
# ---------------------------------------------------------------------------

def test_zone_table_groups_forward_returns_by_starting_zone():
    idx = pd.date_range("2000-01-01", "2011-12-31", freq="D")
    split = pd.Timestamp("2006-01-01")
    years = np.minimum((idx - idx[0]).days, (split - idx[0]).days) / 365.25
    tri = pd.Series(1000 * 1.20**years, index=idx)  # +20%/yr, then flat
    temp = pd.Series(np.where(idx < split, 10.0, 90.0), index=idx)
    table = history.zone_table(temp, tri)
    by_id = {z["id"]: z for z in table["zones"]}
    cheap, rich = by_id["much_cheaper"], by_id["much_pricier"]
    assert cheap["h1"]["median"] > 0.15 and near(rich["h1"]["median"], 0.0, 1e-9)
    assert rich["h1"]["pct_negative"] == 0.0
    assert cheap["h5"]["episodes"] == 2 and rich["h5"]["episodes"] == 1, (cheap["h5"], rich["h5"])
    assert by_id["typical"]["h1"]["n_days"] == 0 and by_id["typical"]["h1"]["median"] is None
    assert abs(sum(z["share_of_days"] for z in table["zones"]) - 1) < 1e-3


def test_episodes_count_non_overlapping_windows():
    stamps = pd.DatetimeIndex(pd.date_range("2000-01-01", "2009-12-31", freq="D"))
    assert history.count_episodes(stamps, 5) == 2
    assert history.count_episodes(stamps, 1) == 10
    assert history.count_episodes(stamps[stamps < "2004-12-31"], 5) == 1


def _year_path():
    points = {"2019-12-31": 100.0, "2020-03-20": 70.0, "2020-12-31": 120.0, "2021-06-30": 110.0, "2021-12-31": 132.0, "2022-03-31": 140.0}
    return pd.Series(points.values(), index=pd.to_datetime(list(points)))


def test_intra_year_falls_and_calendar_returns():
    rows = {r["year"]: r for r in history.intra_year(_year_path(), last_full_year=2021)}
    assert set(rows) == {2020, 2021}
    assert near(rows[2020]["calendar_return"], 0.2) and near(rows[2020]["intra_year_fall"], -0.3)
    assert near(rows[2021]["calendar_return"], 0.1) and near(rows[2021]["intra_year_fall"], 110 / 120 - 1, 1e-4)


def test_entry_year_triangle():
    cells = {(c["entry"], c["years"]): c["cagr"] for c in history.entry_year_triangle(_year_path(), last_full_year=2021)}
    assert set(cells) == {(2020, 1), (2020, 2), (2021, 1)}
    assert near(cells[(2020, 2)], math.sqrt(1.32) - 1, 1e-4)


def test_cycle_table_reads_values_at_the_lows():
    idx = days("2007-01-01", "2021-12-31")
    price = pd.Series(100.0, index=idx)
    price["2009-03-09"] = 50.0
    price["2020-03-23"] = 60.0
    pe = pd.Series(20.0, index=idx)
    pe["2009-03-09"] = 12.0
    pe["2020-03-23"] = 18.0
    table = history.cycle_table({"pe": pe}, price)
    assert [low["date"] for low in table["lows"]] == ["2009-03-09", "2020-03-23"]  # no 2003 data
    assert table["rows"][0]["at_lows"] == 15.0 and table["rows"][0]["median"] == 20.0


# ---------------------------------------------------------------------------
# Manual NSE files
# ---------------------------------------------------------------------------

def _write(folder: Path, name: str, text: str) -> Path:
    path = folder / name
    path.write_text(text)
    return path


def test_parses_the_niftyindices_csv_export():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(
            Path(tmp),
            "pe.csv",
            "NIFTY 50 P/E, P/B & Div Yield\n"
            "Index Name,Date,P/E,P/B,Div Yield%\n"
            "NIFTY 50,24 Sep 2026,21.61,3.43,1.28\n"
            "NIFTY 50,25-Sep-2026,21.53,3.42,1.29\n"
            "NIFTY 50,26 Sep 2026,-,-,-\n"
            "NIFTY 50,29 Sep 2026,215.3,3.40,1.30\n",
        )
        parsed = nse_files.parse_file(path)
        assert parsed.kind == "valuation" and parsed.rows == 3 and parsed.skipped == 1
        assert parsed.series[PE] == {date(2026, 9, 24): 21.61, date(2026, 9, 25): 21.53}  # 215.3 is out of range
        assert parsed.series[PB][date(2026, 9, 29)] == 3.40 and parsed.series[DY][date(2026, 9, 25)] == 1.29


def test_parses_the_research_json_shapes_and_tri_with_commas():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        _write(folder, "pepb.json", json.dumps([{"DATE": "30 Dec 1999", "pe": "24.09", "pb": "4.30", "divYield": "1.02"}]))
        _write(folder, "tri.json", json.dumps([{"Date": "30 Dec 1999", "TotalReturnsIndex": "1,562.92"}]))
        _write(folder, "tri2.csv", "Index Name,Date,Total Returns Index\nNIFTY 50,31-Dec-1999,\"1,580.10\"\n")
        parsed = [nse_files.parse_file(p) for p in nse_files.collect_files([tmp])]
        merged = nse_files.merge(parsed)
        assert merged[PE] == {date(1999, 12, 30): 24.09}
        assert merged[TRI] == {date(1999, 12, 30): 1562.92, date(1999, 12, 31): 1580.10}


def test_rejects_other_indices_and_unknown_layouts():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        other = _write(folder, "next50.csv", "Index Name,Date,P/E,P/B,Div Yield\nNIFTY NEXT 50,25 Sep 2026,20,3,1\n")
        prices = _write(folder, "prices.csv", "Index Name,Date,Open,High,Low,Close\nNIFTY 50,25 Sep 2026,1,2,1,2\n")
        for path, expected in ((other, "not NIFTY 50"), (prices, "expected P/E")):
            try:
                nse_files.parse_file(path)
            except nse_files.NseFileError as e:
                assert expected in str(e), str(e)
            else:
                raise AssertionError(f"{path.name} should be rejected")


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------

def _synthetic_market(with_valuation=True) -> signals.MarketData:
    idx = days("1999-06-01", "2026-09-25")  # as long as the real history
    t = np.arange(len(idx))
    rng = np.random.default_rng(7)
    walk = np.exp(np.cumsum(rng.normal(0.0004, 0.011, len(idx))))
    nifty = pd.Series(5000 * walk, index=idx)
    vix = pd.Series(15 + 5 * np.sin(t / 200), index=idx)
    data = signals.MarketData(nifty=nifty, vix=vix)
    if with_valuation:
        pe = pd.Series(20 + 4 * np.sin(t / 300), index=idx)
        pe[: "2021-03-30"] *= 1.2  # an old basis, linked back by the break below
        data.pe = pe
        data.pb = pd.Series(3 + 0.5 * np.cos(t / 250), index=idx)
        data.dy = pd.Series(1.3 + 0.1 * np.sin(t / 100), index=idx)
        data.tri = nifty * (1 + t / len(t) * 0.3)
        data.breaks = [Break(PE, date(2021, 3, 31), 1 / 1.2, "test")]
    return data


def test_compute_builds_the_signal_row_and_charts():
    result = signals.compute(_synthetic_market(), date(2026, 9, 28))
    v = result.indicators["valuation"]
    assert v["available"] and 0 <= result.valuation_score <= 100
    assert result.zone in {z.id for z in ZONES} and v["zone"] == result.zone
    assert result.as_of == date(2026, 9, 25) and not v["stale"]
    assert result.indicators["breaks"]["unregistered_candidates"] == [], result.indicators["breaks"]
    assert len(result.history_stats["zones"]) == 5
    turbulence = result.indicators["turbulence"]
    assert turbulence["drawdown_pct"] <= 0 and turbulence["vix"]["id"] in {"calm", "normal", "nervous", "elevated"}
    for chart_id, payload in result.charts.items():
        size = len(json.dumps(payload))
        assert payload["available"], chart_id
        assert size < 300_000, f"{chart_id} chart is {size} bytes"
    json.dumps(result.indicators)  # must be JSON-ready as stored
    json.dumps(result.history_stats)


def test_compute_without_valuation_files_still_serves_turbulence():
    result = signals.compute(_synthetic_market(with_valuation=False), date(2026, 9, 28))
    assert result.valuation_score is None and result.zone is None and result.history_stats is None
    assert not result.indicators["valuation"]["available"]
    assert not result.charts["valuation"]["available"]
    assert result.charts["turbulence"]["available"] and result.charts["perspective"]["series"] == "Nifty 50 price index"


def test_stale_valuation_is_flagged():
    data = _synthetic_market()
    for name in ("pe", "pb", "dy"):
        setattr(data, name, getattr(data, name)[:"2026-08-31"])
    v = signals.compute(data, date(2026, 9, 28)).indicators["valuation"]
    assert v["stale"] and v["as_of"] == "2026-08-31"


# ---------------------------------------------------------------------------
# Lump sum vs staggered (explorer)
# ---------------------------------------------------------------------------

def _reference_run(m: pd.Series, temp: pd.Series, months: int, horizon: int, cash: float) -> pd.DataFrame:
    """plans/backtest-reference/stp_adj.py's loop, unchanged apart from names."""
    res = []
    for s0 in m.index[m.index <= m.index[-1] - pd.DateOffset(months=horizon)]:
        pos = m.index.searchsorted([s0 + pd.DateOffset(months=k) for k in range(months)])
        pe_ = m.index.searchsorted(s0 + pd.DateOffset(months=horizon))
        if pe_ >= len(m):
            continue
        p_end = m.iloc[pe_]
        stp = sum((1 / months) * (1 + cash) ** (k / 12) * p_end / m.iloc[p] for k, p in enumerate(pos))
        res.append((s0, p_end / m.iloc[pos[0]], stp))
    r = pd.DataFrame(res, columns=["start", "ls", "stp"]).set_index("start").join(temp.rename("temp"))
    r["zone"] = pd.cut(r["temp"], [0, 33, 67, 100.0001], labels=["cheapest", "middle", "richest"], include_lowest=True)
    return r


def test_deployment_matches_the_research_script():
    from src import deployment as explorer

    data = _synthetic_market()
    tri = data.tri["2012-01-01":]
    temp = pd.Series(np.linspace(5, 95, len(tri)) % 100, index=tri.index)
    ratios = deployment.growth_ratios(tri, step=1)
    rows = [[d.date().isoformat(), float(temp[d])] + list(g) for d, g in ratios.iterrows()]
    for months, cash in ((6, 0.06), (12, 0.06), (3, 0.0)):
        ref = _reference_run(tri, temp, months, 12, cash)
        ours = explorer.outcomes(rows, months, cash)
        assert len(ours) == len(ref), (len(ours), len(ref))
        assert np.allclose([o["lump"] for o in ours], ref["ls"]) and np.allclose([o["staged"] for o in ours], ref["stp"])
        for third in ("cheapest", "middle", "richest"):
            members = ref[ref["zone"] == third]
            mine = explorer.summarise([o for o in ours if explorer.third_of(o["t"]) == third])
            assert mine["n"] == len(members), (third, mine["n"], len(members))
            assert near(mine["lump_better_pct"], (members.ls > members.stp).mean())
            assert near(mine["median_edge"], (members.ls / members.stp - 1).median())
            assert near(mine["p10_edge"], (members.ls / members.stp - 1).quantile(0.1))


def test_deployment_table_stops_thirty_days_back_and_stays_small():
    result = signals.compute(_synthetic_market(), date(2026, 9, 28))
    table = result.charts["deployment"]
    assert table["available"] and table["has_temperature"] and table["series"] == "Nifty 50 Total Return Index"
    assert table["data_until"] <= "2026-08-26", table["data_until"]
    last_start = pd.Timestamp(table["rows"][-1][0])
    assert last_start + pd.DateOffset(months=12) <= pd.Timestamp(table["data_until"])
    assert len(json.dumps(table)) < 300_000
    no_valuation = signals.compute(_synthetic_market(with_valuation=False), date(2026, 9, 28)).charts["deployment"]
    assert no_valuation["available"] and not no_valuation["has_temperature"] and no_valuation["series"] == "Nifty 50 price index"


def test_todays_close_is_dropped_until_the_session_ends():
    s = pd.Series([1.0, 2.0], index=pd.to_datetime(["2026-09-24", "2026-09-25"]))
    during = datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc)  # 13:30 IST
    after = datetime(2026, 9, 25, 13, 30, tzinfo=timezone.utc)  # 19:00 IST
    assert list(final_closes(s, during).index.day) == [24]
    assert list(final_closes(s, after).index.day) == [24, 25]


def main():
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_") and callable(fn)]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:  # noqa: BLE001 - report every failure, keep going
            failures += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
