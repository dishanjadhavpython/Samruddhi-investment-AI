#!/usr/bin/env python3
"""
Remove the stale US-instrument catalog left over from before the India localization.

positions.symbol REFERENCES instruments(symbol) with the default RESTRICT behavior,
so an instrument can only be deleted if no position still references it. For each
old US symbol this script checks how many positions reference it:
  - 0 positions  -> safe to delete (deleted only with --apply)
  - >0 positions -> skipped, reported so a human can decide what to do

Defaults to dry-run (report only). Pass --apply to actually delete.

This script does NOT get run automatically - it's a standalone, explicitly-invoked
cleanup step for the live Aurora database.
"""

import os
import argparse
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Get config from environment
cluster_arn = os.environ.get("AURORA_CLUSTER_ARN")
secret_arn = os.environ.get("AURORA_SECRET_ARN")
database = os.environ.get("AURORA_DATABASE", "samruddhi")
region = os.environ.get("DEFAULT_AWS_REGION", "us-east-1")

if not cluster_arn or not secret_arn:
    print("❌ Missing AURORA_CLUSTER_ARN or AURORA_SECRET_ARN in .env file")
    exit(1)

client = boto3.client("rds-data", region_name=region)

# The 22 US ETF symbols that were seeded before the India localization pass
OLD_US_SYMBOLS = [
    "SPY", "QQQ", "IWM", "VEA", "VWO", "EFA", "AGG", "BND", "TLT", "HYG",
    "XLK", "XLV", "XLF", "XLE", "VNQ", "GLD", "SLV", "AOR", "AOA", "VUG",
    "VTV", "VIG",
]


def count_positions(symbol: str) -> int:
    """Count how many positions reference this symbol."""
    response = client.execute_statement(
        resourceArn=cluster_arn,
        secretArn=secret_arn,
        database=database,
        sql="SELECT COUNT(*) AS count FROM positions WHERE symbol = :symbol",
        parameters=[{"name": "symbol", "value": {"stringValue": symbol}}],
    )
    return response["records"][0][0]["longValue"]


def delete_instrument(symbol: str) -> None:
    """Delete the instrument row for this symbol."""
    client.execute_statement(
        resourceArn=cluster_arn,
        secretArn=secret_arn,
        database=database,
        sql="DELETE FROM instruments WHERE symbol = :symbol",
        parameters=[{"name": "symbol", "value": {"stringValue": symbol}}],
    )


def main():
    parser = argparse.ArgumentParser(
        description="Remove stale US instruments no longer used after India localization"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete unreferenced instruments (default is dry-run/report-only)",
    )
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"🚀 Removing stale US instruments ({mode})")
    print("=" * 50)
    if not args.apply:
        print("Dry-run mode: no changes will be made. Pass --apply to actually delete.\n")

    deleted = []
    skipped = []
    would_delete = []

    for symbol in OLD_US_SYMBOLS:
        try:
            count = count_positions(symbol)
        except ClientError as e:
            print(f"  ❌ {symbol}: error checking positions - {e.response['Error']['Message'][:100]}")
            continue

        if count == 0:
            if args.apply:
                try:
                    delete_instrument(symbol)
                    print(f"  🗑️  deleted: {symbol}")
                    deleted.append(symbol)
                except ClientError as e:
                    print(f"  ❌ {symbol}: error deleting - {e.response['Error']['Message'][:100]}")
            else:
                print(f"  would delete: {symbol}")
                would_delete.append(symbol)
        else:
            print(f"  ⏭️  skipped: {symbol} — still held in {count} position(s)")
            skipped.append(symbol)

    print("\n" + "=" * 50)
    if args.apply:
        print(f"Summary: {len(deleted)} deleted, {len(skipped)} skipped")
    else:
        print(f"Summary: {len(would_delete)} would delete, {len(skipped)} skipped (dry run)")
        print("\nRun again with --apply to actually delete the unreferenced instruments.")


if __name__ == "__main__":
    main()
