#!/usr/bin/env python3
"""
Give every existing holding an opening balance in the transaction ledger.

Positions entered before migration 005 have a quantity but no history. This
records one opening_balance row for each, dated the day the quantity was
entered and valued at that day's close, then recomputes the position's cost
from the ledger. Quantities don't change. Holdings that already have ledger
rows are left alone, so running it again changes nothing.

    uv run backfill_opening_balances.py --dry-run
    uv run backfill_opening_balances.py
"""

import argparse
from datetime import date

from src import Database
from src.ledger import set_quantity


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="list what would be recorded, change nothing")
    args = parser.parse_args()

    db = Database()
    created = skipped = 0
    for holding in db.positions.all_holdings():
        account_id, symbol = holding["account_id"], holding["symbol"]
        if db.transactions.for_holding(account_id, symbol):
            skipped += 1
            continue
        day = date.fromisoformat(holding["as_of_date"])
        print(f"{'Would record' if args.dry_run else 'Recording'} opening balance: {symbol} x {holding['quantity']:g} "
              f"on {day} in account {account_id[:8]}")
        if not args.dry_run:
            set_quantity(db, account_id, symbol, holding["quantity"], day)
        created += 1
    print(f"\n{created} opening balance(s) {'to record' if args.dry_run else 'recorded'}; {skipped} holding(s) already had a ledger.")


if __name__ == "__main__":
    main()
