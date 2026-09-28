"""
Manual, prices-only refresh — no SQS, no analysis jobs, no Bedrock cost.

Updates instruments.current_price for exchange-traded instruments from Yahoo
Finance (15 minutes delayed during the session) and publishes the same prices,
the Nifty 50 and India VIX to DynamoDB for GET /api/market/snapshot. Run this
any time you want fresh prices outside the scheduled Lambda in
lambda_handler.py (every 5 minutes during NSE hours once deployed).

Usage:
    cd backend/pricer
    uv run refresh_prices_only.py
"""

from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv(override=True)

from src import Database
from refresh_prices import refresh_exchange_prices


def main():
    print("Refreshing instrument prices from Yahoo Finance...")
    print("=" * 50)

    result = refresh_exchange_prices(Database(), datetime.now(timezone.utc))
    for symbol, outcome in result["prices"].items():
        print(f"  {symbol}: {outcome}")

    updated = sum(1 for v in result["prices"].values() if not v.startswith(("no data", "error", "held")))
    print("\n" + "=" * 50)
    print(f"Updated {updated}/{len(result['prices'])} prices. DynamoDB: {result['live']}")


if __name__ == "__main__":
    main()
