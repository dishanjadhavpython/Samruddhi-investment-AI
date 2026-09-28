"""
Load Nifty 50 valuation and Total Return Index files you downloaded by hand
from https://www.niftyindices.com/reports/historical-data, then recompute the
market signals.

    uv run ingest.py nse_data/            # every .csv/.json in the folder
    uv run ingest.py pe_2024.csv tri.csv  # specific files
    uv run ingest.py nse_data/ --dry-run  # parse and report only

See README.md in this folder for what to download.
"""

import argparse
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv(override=True)

from src import Database

import breaks as break_checks
import market_eod
import nse_files
import store
from series import KNOWN_BREAKS, PB, PE, TRI


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="+", help="files or folders")
    parser.add_argument("--dry-run", action="store_true", help="parse and report, write nothing")
    args = parser.parse_args()

    try:
        paths = nse_files.collect_files(args.inputs)
    except nse_files.NseFileError as e:
        print(f"❌ {e}")
        return 1
    if not paths:
        print("❌ No .csv or .json files found")
        return 1

    parsed, failed = [], 0
    for path in paths:
        try:
            p = nse_files.parse_file(path)
            parsed.append(p)
            skipped = f", {p.skipped} rows skipped" if p.skipped else ""
            print(f"  ✅ {path.name}: {p.kind}, {p.rows} days {p.first} → {p.last}{skipped}")
        except nse_files.NseFileError as e:
            failed += 1
            print(f"  ❌ {e}")

    merged = nse_files.merge(parsed)
    print("\nSeries found:")
    for series_id, points in sorted(merged.items()):
        days = sorted(points)
        print(f"  {series_id}: {len(days)} days, {days[0]} → {days[-1]}")

    missing = [s for s in (PE, PB, TRI) if s not in merged]
    if missing:
        print(f"\n⚠️  Not in these files: {', '.join(missing)}. The page shows what it can without them.")

    if args.dry_run:
        print("\nDry run: nothing written.")
        return 1 if failed else 0

    db = Database()
    store.register_breaks(db, KNOWN_BREAKS)
    counts = market_eod.load_parsed(db, parsed)
    print(f"\nWrote to market_series: {counts}")

    # Flag valuation jumps the break registry doesn't explain
    registered = store.load_breaks(db)
    basis = store.load_series(db, TRI)
    if basis.empty:
        basis = store.load_series(db, "NIFTY50")
    for series_id in (PE, PB):
        found = break_checks.detect_breaks(store.load_series(db, series_id), basis)
        for c in break_checks.unregistered(found, registered, series_id):
            print(f"⚠️  Possible methodology break in {series_id} on {c['date']}: {c['valuation_change']:+.1%} while the index moved {c['price_change']:+.1%}")

    summary = market_eod.compute_and_store(db, datetime.now(timezone.utc))
    print(f"\nSignals as of {summary['as_of']}: score {summary['valuation_score']}, zone {summary['zone']}, history table: {summary['has_history_table']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
