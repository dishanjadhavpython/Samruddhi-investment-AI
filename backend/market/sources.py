"""
Network sources for the market pipeline.

Yahoo Finance supplies the Nifty 50 and India VIX daily closes for the
private demo deployment only (plan section 6). Valuation and TRI history never
come from here: they are loaded from files downloaded by hand (nse_files.py).
"""

import logging
import os
from datetime import datetime, time
from typing import Dict
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance

logger = logging.getLogger(__name__)

# yfinance's timezone cache defaults to the home directory, which is read-only
# on Lambda; threaded downloads also fight over it, so threads=False below.
yfinance.set_tz_cache_location(os.environ.get("YF_CACHE_DIR", "/tmp/yf-cache"))

IST = ZoneInfo("Asia/Kolkata")
BARS_FINAL_AFTER = time(15, 45)  # a same-day close is final 15 minutes after the session ends


def fetch_yahoo_closes(tickers: Dict[str, str], period: str = "1mo") -> Dict[str, pd.Series]:
    """Daily closes per series id from one batched download, oldest first."""
    frame = yfinance.download(
        sorted(tickers.values()),
        period=period,
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )
    closes: Dict[str, pd.Series] = {}
    for series_id, ticker in tickers.items():
        if frame is None or frame.empty or ticker not in frame.columns.get_level_values(0):
            logger.warning("Yahoo returned no data for %s", ticker)
            closes[series_id] = pd.Series(dtype=float)
            continue
        close = frame[ticker]["Close"].dropna()
        close.index = pd.to_datetime([stamp.date() for stamp in close.index])
        closes[series_id] = close[close > 0].astype(float)
    return closes


def final_closes(series: pd.Series, now: datetime) -> pd.Series:
    """Drop today's close while the session is still open (it would move)."""
    local = now.astimezone(IST)
    today = pd.Timestamp(local.date())
    if local.time() >= BARS_FINAL_AFTER:
        return series[series.index <= today]
    return series[series.index < today]
