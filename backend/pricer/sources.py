"""
Market data sources for the pricer. Network access lives here; the decisions
about what to store live in refresh_prices.py.

- Yahoo Finance (via yfinance): NSE-listed ETFs and stocks and the Nifty 50
  and India VIX: one batched daily download and one 5-minute download per run. Personal/demo use only; a commercial launch needs an
  NSE-authorised vendor (plans/realtime-market-intelligence.md, section 6).
- AMFI NAVAll.txt: daily NAVs for open-ended mutual funds.
"""

import csv
import io
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Iterable, List

import requests
import yfinance

logger = logging.getLogger(__name__)

# yfinance keeps a SQLite timezone cache in the home directory by default,
# which is read-only on Lambda. Concurrent writes to it also fail ("database is
# locked"), so downloads run with threads=False.
yfinance.set_tz_cache_location(os.environ.get("YF_CACHE_DIR", "/tmp/yf-cache"))

AMFI_NAV_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"


@dataclass
class Bar:
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int


@dataclass
class IntradayBar:
    start: datetime  # tz-aware; the bar covers start to start + its interval
    open: float
    high: float
    low: float
    close: float


@dataclass
class Nav:
    scheme_code: str
    nav: float
    nav_date: date


def _num(value) -> float:
    return float(value) if value == value else None  # NaN -> None


def fetch_yahoo_daily(tickers: Iterable[str], period: str = "10d") -> Dict[str, List[Bar]]:
    """Daily bars per ticker, oldest first, from one batched download.

    During the NSE session the last bar is today's, and its close is the
    latest (delayed) traded price. Tickers Yahoo doesn't know come back empty.
    """
    tickers = sorted(set(tickers))
    if not tickers:
        return {}

    frame = yfinance.download(
        tickers,
        period=period,
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )

    bars: Dict[str, List[Bar]] = {}
    for ticker in tickers:
        if frame is None or frame.empty or ticker not in frame.columns.get_level_values(0):
            bars[ticker] = []
            continue
        rows = frame[ticker].dropna(subset=["Close"])
        bars[ticker] = [
            Bar(
                trade_date=index.date(),
                open=_num(row["Open"]),
                high=_num(row["High"]),
                low=_num(row["Low"]),
                close=float(row["Close"]),
                adj_close=_num(row["Adj Close"]),
                volume=int(row["Volume"]) if row["Volume"] == row["Volume"] else None,
            )
            for index, row in rows.iterrows()
        ]
    return bars


def fetch_yahoo_intraday(tickers: Iterable[str], interval: str = "5m") -> Dict[str, List[IntradayBar]]:
    """The latest session's 5-minute bars per ticker, oldest first, from one batched download.

    Yahoo labels each bar by its start time and includes the bar still in
    progress; refresh_prices.delayed_quote decides which bars may be shown.
    """
    tickers = sorted(set(tickers))
    if not tickers:
        return {}

    frame = yfinance.download(
        tickers,
        period="1d",
        interval=interval,
        group_by="ticker",
        auto_adjust=False,
        actions=False,
        prepost=False,
        progress=False,
        threads=False,
    )

    bars: Dict[str, List[IntradayBar]] = {}
    for ticker in tickers:
        if frame is None or frame.empty or ticker not in frame.columns.get_level_values(0):
            bars[ticker] = []
            continue
        rows = frame[ticker].dropna(subset=["Close"])
        bars[ticker] = [
            IntradayBar(
                start=index.to_pydatetime(),
                open=_num(row["Open"]),
                high=_num(row["High"]),
                low=_num(row["Low"]),
                close=float(row["Close"]),
            )
            for index, row in rows.iterrows()
        ]
    return bars


def parse_amfi_nav_rows(text: str, scheme_codes: Iterable[str]) -> List[Nav]:
    """Every NAV row for the given scheme codes, from any AMFI NAV file.

    AMFI files are semicolon-separated with AMC and category heading lines
    mixed in. Columns are found by header name, because the layout differs
    between NAVAll.txt and the history report, and AMFI has changed it before.
    """
    wanted = set(scheme_codes)
    reader = csv.reader(io.StringIO(text), delimiter=";")
    header = next(reader)
    columns = {name.strip(): i for i, name in enumerate(header)}
    code_col = columns["Scheme Code"]
    nav_col = columns["Net Asset Value"]
    date_col = columns["Date"]

    navs: List[Nav] = []
    for row in reader:
        if len(row) <= max(code_col, nav_col, date_col):
            continue  # AMC names, category headings and blank lines
        code = row[code_col].strip()
        if code not in wanted:
            continue
        try:
            navs.append(Nav(
                scheme_code=code,
                nav=float(row[nav_col]),
                nav_date=datetime.strptime(row[date_col].strip(), "%d-%b-%Y").date(),
            ))
        except ValueError:
            logger.warning(f"AMFI: unreadable row for scheme {code}: {row}")
    return navs


def parse_amfi_navs(text: str, scheme_codes: Iterable[str]) -> Dict[str, Nav]:
    """The latest NAV per scheme code."""
    latest: Dict[str, Nav] = {}
    for nav in parse_amfi_nav_rows(text, scheme_codes):
        if nav.scheme_code not in latest or nav.nav_date > latest[nav.scheme_code].nav_date:
            latest[nav.scheme_code] = nav
    return latest


AMFI_HISTORY_URL = "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx"


def fetch_amfi_nav_history(fund_house: str, start: date, end: date, scheme_codes: Iterable[str]) -> List[Nav]:
    """NAV history for one fund house (AMFI's "mf" code) between two dates, inclusive."""
    response = requests.get(
        AMFI_HISTORY_URL,
        params={"mf": fund_house, "tp": "1", "frmdt": start.strftime("%d-%b-%Y"), "todt": end.strftime("%d-%b-%Y")},
        timeout=120,
        headers={"User-Agent": "samruddhi-ai-pricer"},
    )
    response.raise_for_status()
    return parse_amfi_nav_rows(response.text, scheme_codes)


def fetch_amfi_navs(scheme_codes: Iterable[str]) -> Dict[str, Nav]:
    scheme_codes = set(scheme_codes)
    if not scheme_codes:
        return {}
    response = requests.get(AMFI_NAV_URL, timeout=60, headers={"User-Agent": "samruddhi-ai-pricer"})
    response.raise_for_status()
    return parse_amfi_navs(response.text, scheme_codes)
