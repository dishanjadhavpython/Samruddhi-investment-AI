#!/usr/bin/env python3
"""
One-off history backfill for price_bars_daily.

- ETFs and held stocks: daily OHLC bars from Yahoo Finance (one batched download).
- Mutual funds: daily NAVs from AMFI's NAV history report, fetched per fund
  house in 90-day chunks.

Safe to re-run: every row is an upsert. Finishes by refreshing NAVs so each
fund gets a previous close from the backfilled history.

Usage:
    cd backend/pricer
    uv run backfill.py              # about 2 years
    uv run backfill.py --days 400
"""

import argparse
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(override=True)

from src import Database

from refresh_prices import AMFI, YAHOO, final_bars, load_targets, refresh_navs, write_bars
from sources import Bar, fetch_amfi_nav_history, fetch_yahoo_daily

# AMFI fund-house ("mf") code for each scheme code, found by querying the
# history report on 27 Sep 2026. Add an entry when a new fund joins the catalogue.
AMFI_FUND_HOUSES = {
    "119091": "9",   # HDFC Mutual Fund
    "120692": "20",  # ICICI Prudential Mutual Fund
    "120716": "28",  # UTI Mutual Fund
}

CHUNK_DAYS = 90


def backfill_exchange_bars(db, days: int, now: datetime) -> None:
    targets = [t for t in load_targets(db) if t.get("yahoo_ticker")]
    period = "2y" if days > 365 else "1y"
    print(f"Yahoo: downloading {period} of daily bars for {len(targets)} tickers...")
    bars_by_ticker = fetch_yahoo_daily([t["yahoo_ticker"] for t in targets], period=period)
    for target in targets:
        bars = final_bars(bars_by_ticker.get(target["yahoo_ticker"], []), now)
        written = write_bars(db, target["symbol"], bars, YAHOO)
        span = f"{bars[0].trade_date} to {bars[-1].trade_date}" if bars else "no data"
        print(f"  {target['symbol']:<12} {written:>4} bars  ({span})")


def backfill_navs(db, days: int, today: date) -> None:
    targets = [t for t in load_targets(db) if t.get("amfi_scheme_code")]
    for target in targets:
        code = target["amfi_scheme_code"]
        fund_house = AMFI_FUND_HOUSES.get(code)
        if not fund_house:
            print(f"  {target['symbol']:<12} skipped: no fund-house code for scheme {code}")
            continue

        navs = []
        start = today - timedelta(days=days)
        while start <= today:
            end = min(start + timedelta(days=CHUNK_DAYS - 1), today)
            navs += fetch_amfi_nav_history(fund_house, start, end, {code})
            start = end + timedelta(days=1)

        bars = [Bar(n.nav_date, None, None, None, n.nav, n.nav, None) for n in navs]
        written = write_bars(db, target["symbol"], bars, AMFI)
        span = f"{bars[0].trade_date} to {bars[-1].trade_date}" if bars else "no data"
        print(f"  {target['symbol']:<12} {written:>4} NAVs  ({span})")


def main():
    parser = argparse.ArgumentParser(description="Backfill daily price history")
    parser.add_argument("--days", type=int, default=730, help="how far back to go (default 730)")
    args = parser.parse_args()

    db = Database()
    now = datetime.now(timezone.utc)

    backfill_exchange_bars(db, args.days, now)
    print("\nAMFI: downloading NAV history...")
    backfill_navs(db, args.days, now.date())

    print("\nRefreshing NAVs so each fund has a previous close...")
    for symbol, result in refresh_navs(db, now).items():
        print(f"  {symbol}: {result}")
    print("\n✅ Backfill complete")


if __name__ == "__main__":
    main()
