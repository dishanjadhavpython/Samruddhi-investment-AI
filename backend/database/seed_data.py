#!/usr/bin/env python3
"""
Seed data for Samruddhi AI
Loads popular Indian ETF/mutual fund instruments with allocation data
"""

import os
import json
import boto3
from botocore.exceptions import ClientError
from src.schemas import InstrumentCreate
from pydantic import ValidationError
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

# Define popular Indian instruments with realistic allocation data
# All percentages should sum to 100 for each allocation type
INSTRUMENTS = [
    {
        "symbol": "NIFTYBEES", "name": "Nippon India ETF Nifty BeES",
        "instrument_type": "etf", "current_price": 245.30,
        "allocation_regions": {"india": 100},
        "allocation_sectors": {"financials": 34, "technology": 13, "energy": 11,
            "consumer_staples": 9, "consumer_discretionary": 7, "healthcare": 4,
            "materials": 6, "utilities": 3, "communication": 4, "industrials": 6, "other": 3},
        "allocation_asset_class": {"equity": 100},
    },
    {
        "symbol": "JUNIORBEES", "name": "Nippon India ETF Nifty Next 50 Junior BeES",
        "instrument_type": "etf", "current_price": 620.50,
        "allocation_regions": {"india": 100},
        "allocation_sectors": {"financials": 20, "consumer_discretionary": 15, "industrials": 14,
            "materials": 12, "healthcare": 10, "technology": 8, "consumer_staples": 8,
            "energy": 6, "utilities": 4, "communication": 3},
        "allocation_asset_class": {"equity": 100},
    },
    {
        "symbol": "BANKBEES", "name": "Nippon India ETF Bank BeES",
        "instrument_type": "etf", "current_price": 485.75,
        "allocation_regions": {"india": 100},
        "allocation_sectors": {"financials": 100},
        "allocation_asset_class": {"equity": 100},
    },
    {
        "symbol": "ITBEES", "name": "ICICI Prudential Nifty IT ETF",
        "instrument_type": "etf", "current_price": 42.10,
        "allocation_regions": {"india": 100},
        "allocation_sectors": {"technology": 100},
        "allocation_asset_class": {"equity": 100},
    },
    {
        "symbol": "GOLDBEES", "name": "Nippon India ETF Gold BeES",
        "instrument_type": "etf", "current_price": 62.40,
        "allocation_regions": {"global": 100},
        "allocation_sectors": {"commodities": 100},
        "allocation_asset_class": {"commodities": 100},
    },
    {
        "symbol": "SILVERBEES", "name": "Nippon India Silver ETF",
        "instrument_type": "etf", "current_price": 95.20,
        "allocation_regions": {"global": 100},
        "allocation_sectors": {"commodities": 100},
        "allocation_asset_class": {"commodities": 100},
    },
    {
        "symbol": "LIQUIDBEES", "name": "Nippon India ETF Liquid BeES",
        "instrument_type": "bond_fund", "current_price": 1000.15,
        "allocation_regions": {"india": 100},
        "allocation_sectors": {"treasury": 35, "corporate": 65},
        "allocation_asset_class": {"fixed_income": 100},
    },
    {
        "symbol": "HDFCLIQF", "name": "HDFC Liquid Fund",
        "instrument_type": "mutual_fund", "current_price": 4650.30,
        "allocation_regions": {"india": 100},
        "allocation_sectors": {"treasury": 30, "corporate": 55, "government_related": 15},
        "allocation_asset_class": {"fixed_income": 100},
    },
    {
        "symbol": "ICICICORP", "name": "ICICI Prudential Corporate Bond Fund",
        "instrument_type": "mutual_fund", "current_price": 27.85,
        "allocation_regions": {"india": 100},
        "allocation_sectors": {"corporate": 82, "treasury": 18},
        "allocation_asset_class": {"fixed_income": 100},
    },
    {
        "symbol": "UTINIFTY", "name": "UTI Nifty 50 Index Fund",
        "instrument_type": "mutual_fund", "current_price": 187.40,
        "allocation_regions": {"india": 100},
        "allocation_sectors": {"financials": 34, "technology": 13, "energy": 11,
            "consumer_staples": 9, "consumer_discretionary": 7, "healthcare": 4,
            "materials": 6, "utilities": 3, "communication": 4, "industrials": 6, "other": 3},
        "allocation_asset_class": {"equity": 100},
    },
]


# Where the pricer gets each price (see backend/pricer). ETFs trade on NSE and
# are priced from Yahoo Finance; the open-ended funds are priced from AMFI's
# daily NAV file. AMFI codes are the Direct Plan - Growth options, checked
# against NAVAll.txt on 27 Sep 2026.
PRICE_SOURCES = {
    "NIFTYBEES": {"yahoo_ticker": "NIFTYBEES.NS"},
    "JUNIORBEES": {"yahoo_ticker": "JUNIORBEES.NS"},
    "BANKBEES": {"yahoo_ticker": "BANKBEES.NS"},
    "ITBEES": {"yahoo_ticker": "ITBEES.NS"},
    "GOLDBEES": {"yahoo_ticker": "GOLDBEES.NS"},
    "SILVERBEES": {"yahoo_ticker": "SILVERBEES.NS"},
    "LIQUIDBEES": {"yahoo_ticker": "LIQUIDBEES.NS"},
    "HDFCLIQF": {"amfi_scheme_code": "119091", "isin": "INF179KB1HP9"},
    "ICICICORP": {"amfi_scheme_code": "120692", "isin": "INF109K016B1"},
    "UTINIFTY": {"amfi_scheme_code": "120716", "isin": "INF789F01XA0"},
}


def _string_or_null(value):
    return {"stringValue": value} if value else {"isNull": True}


def insert_instrument(instrument_data):
    """Insert a single instrument into the database with Pydantic validation"""
    # Validate with Pydantic first
    try:
        instrument = InstrumentCreate(**instrument_data)
    except ValidationError as e:
        print(f"    ❌ Validation error: {e}")
        return False

    # Get validated data
    validated = instrument.model_dump()

    # The seed price is only a placeholder until the pricer runs, so it is
    # labelled as such and never overwrites a price on an existing row.
    sql = """
        INSERT INTO instruments (
            symbol, name, instrument_type, current_price, price_source, price_status,
            yahoo_ticker, amfi_scheme_code, isin,
            allocation_regions, allocation_sectors, allocation_asset_class
        ) VALUES (
            :symbol, :name, :instrument_type, :current_price::numeric, 'seed', 'stale',
            :yahoo_ticker, :amfi_scheme_code, :isin,
            :allocation_regions::jsonb, :allocation_sectors::jsonb, :allocation_asset_class::jsonb
        )
        ON CONFLICT (symbol) DO UPDATE SET
            name = EXCLUDED.name,
            instrument_type = EXCLUDED.instrument_type,
            yahoo_ticker = EXCLUDED.yahoo_ticker,
            amfi_scheme_code = EXCLUDED.amfi_scheme_code,
            isin = EXCLUDED.isin,
            allocation_regions = EXCLUDED.allocation_regions,
            allocation_sectors = EXCLUDED.allocation_sectors,
            allocation_asset_class = EXCLUDED.allocation_asset_class,
            updated_at = NOW()
    """
    sources = PRICE_SOURCES.get(validated["symbol"], {})

    try:
        response = client.execute_statement(
            resourceArn=cluster_arn,
            secretArn=secret_arn,
            database=database,
            sql=sql,
            parameters=[
                {"name": "symbol", "value": {"stringValue": validated["symbol"]}},
                {"name": "name", "value": {"stringValue": validated["name"]}},
                {"name": "instrument_type", "value": {"stringValue": validated["instrument_type"]}},
                {
                    "name": "current_price",
                    "value": {"stringValue": str(validated.get("current_price", 0))},
                },
                {"name": "yahoo_ticker", "value": _string_or_null(sources.get("yahoo_ticker"))},
                {"name": "amfi_scheme_code", "value": _string_or_null(sources.get("amfi_scheme_code"))},
                {"name": "isin", "value": _string_or_null(sources.get("isin"))},
                {
                    "name": "allocation_regions",
                    "value": {"stringValue": json.dumps(validated["allocation_regions"])},
                },
                {
                    "name": "allocation_sectors",
                    "value": {"stringValue": json.dumps(validated["allocation_sectors"])},
                },
                {
                    "name": "allocation_asset_class",
                    "value": {"stringValue": json.dumps(validated["allocation_asset_class"])},
                },
            ],
        )
        return True
    except ClientError as e:
        print(f"    ❌ Error: {e.response['Error']['Message'][:100]}")
        return False


def verify_allocations(instrument):
    """Verify instrument using Pydantic validation"""
    try:
        InstrumentCreate(**instrument)
        return []  # No errors
    except ValidationError as e:
        # Extract error messages
        errors = []
        for error in e.errors():
            field = ".".join(str(x) for x in error["loc"])
            msg = error["msg"]
            errors.append(f"{field}: {msg}")
        return errors


def main():
    print("🚀 Seeding Instrument Data")
    print("=" * 50)
    print(f"Loading {len(INSTRUMENTS)} instruments...")

    # First verify all allocations
    print("\n📊 Verifying allocation data...")
    all_valid = True
    for inst in INSTRUMENTS:
        errors = verify_allocations(inst)
        if errors:
            print(f"  ❌ {inst['symbol']}: {', '.join(errors)}")
            all_valid = False

    if not all_valid:
        print("\n❌ Some instruments have invalid allocations. Please fix before continuing.")
        exit(1)

    print("  ✅ All allocations valid!")

    # Insert instruments
    print("\n💾 Inserting instruments...")
    success_count = 0

    for inst in INSTRUMENTS:
        print(
            f"  [{success_count + 1}/{len(INSTRUMENTS)}] {inst['symbol']}: {inst['name'][:40]}..."
        )
        if insert_instrument(inst):
            print(f"    ✅ Success")
            success_count += 1
        else:
            print(f"    ❌ Failed")

    print("\n" + "=" * 50)
    print(f"Seeding complete: {success_count}/{len(INSTRUMENTS)} instruments loaded")

    # Verify by querying
    print("\n🔍 Verifying data...")
    try:
        response = client.execute_statement(
            resourceArn=cluster_arn,
            secretArn=secret_arn,
            database=database,
            sql="SELECT COUNT(*) as count FROM instruments",
        )
        count = response["records"][0][0]["longValue"]
        print(f"  Database now contains {count} instruments")

        # Show a sample
        response = client.execute_statement(
            resourceArn=cluster_arn,
            secretArn=secret_arn,
            database=database,
            sql="SELECT symbol, name FROM instruments ORDER BY symbol LIMIT 5",
        )

        print("\n  Sample instruments:")
        for record in response["records"]:
            symbol = record[0]["stringValue"]
            name = record[1]["stringValue"]
            print(f"    - {symbol}: {name}")

    except ClientError as e:
        print(f"  ❌ Error verifying: {e}")

    print("\n✅ Seed data loaded successfully!")
    print("\n📝 Next steps:")
    print("1. Create test user and portfolio: uv run create_test_data.py")
    print("2. Test database operations: uv run test_db.py")


if __name__ == "__main__":
    main()
