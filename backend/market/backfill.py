"""
One-off setup for the market pipeline: registers the known methodology
breaks and NSE holidays, loads the full Nifty 50 and India VIX history from
Yahoo, and computes the first market signals.

    uv run backfill.py
"""

import json

from dotenv import load_dotenv

load_dotenv(override=True)

from src import Database

import market_eod
import store


def main() -> None:
    db = Database()
    print("Loading full Nifty 50 and India VIX history from Yahoo...")
    summary = market_eod.run(db, period="max")
    print(json.dumps(summary, indent=2, default=str))
    print("\nCoverage:")
    for row in store.series_coverage(db):
        print(f"  {row['series_id']}: {row['n']} days, {row['first']} → {row['last']}")


if __name__ == "__main__":
    main()
