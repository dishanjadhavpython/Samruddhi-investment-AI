#!/usr/bin/env python3
"""
Database Reset Script
Drops all tables, recreates schema, and loads seed data
"""

import sys
import argparse
from pathlib import Path
from src.client import DataAPIClient
from src.models import Database
from src.schemas import UserCreate, AccountCreate, PositionCreate
from decimal import Decimal


def drop_all_tables(db: DataAPIClient):
    """Drop all tables in correct order (respecting foreign keys)"""
    print("🗑️  Dropping existing tables...")
    
    # Order matters due to foreign key constraints
    tables_to_drop = [
        'portfolio_snapshots',
        'price_bars_daily',
        'market_signals',
        'market_series_breaks',
        'market_series',
        'market_holidays',
        'positions',
        'accounts',
        'jobs',
        'instruments',
        'users',
        # Dropped last so run_migrations.py re-applies every migration
        'schema_migrations'
    ]
    
    for table in tables_to_drop:
        try:
            db.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
            print(f"   ✅ Dropped {table}")
        except Exception as e:
            print(f"   ⚠️  Error dropping {table}: {e}")
    
    # Also drop the function
    try:
        db.execute("DROP FUNCTION IF EXISTS update_updated_at_column() CASCADE")
        print(f"   ✅ Dropped update_updated_at_column function")
    except Exception as e:
        print(f"   ⚠️  Error dropping function: {e}")


def create_test_data(db_models: Database):
    """Create test user with sample portfolio"""
    print("\n👤 Creating test user and portfolio...")
    
    # Create test user with Pydantic validation
    user_data = UserCreate(
        clerk_user_id='test_user_001',
        display_name='Test User',
        years_until_retirement=25,
        target_retirement_income=Decimal('100000')
    )
    
    # Check if user exists
    existing = db_models.users.find_by_clerk_id('test_user_001')
    if existing:
        print("   ℹ️  Test user already exists")
    else:
        # Use validated data from Pydantic model
        validated = user_data.model_dump()
        db_models.users.create_user(
            clerk_user_id=validated['clerk_user_id'],
            display_name=validated['display_name'],
            years_until_retirement=validated['years_until_retirement'],
            target_retirement_income=validated['target_retirement_income']
        )
        print("   ✅ Created test user")
    
    # Create test accounts with Pydantic validation
    accounts = [
        AccountCreate(
            account_name='EPF',
            account_purpose='Primary retirement savings',
            cash_balance=Decimal('5000'),
            cash_interest=Decimal('0.045')
        ),
        AccountCreate(
            account_name='PPF',
            account_purpose='Tax-free retirement savings',
            cash_balance=Decimal('1000'),
            cash_interest=Decimal('0.04')
        ),
        AccountCreate(
            account_name='Demat / Brokerage',
            account_purpose='General investment account',
            cash_balance=Decimal('2500'),
            cash_interest=Decimal('0.035')
        )
    ]
    
    user_accounts = db_models.accounts.find_by_user('test_user_001')
    
    if user_accounts:
        print(f"   ℹ️  User already has {len(user_accounts)} accounts")
        account_ids = [acc['id'] for acc in user_accounts]
    else:
        account_ids = []
        for acc_data in accounts:
            validated = acc_data.model_dump()
            acc_id = db_models.accounts.create_account(
                'test_user_001',
                account_name=validated['account_name'],
                account_purpose=validated['account_purpose'],
                cash_balance=validated['cash_balance'],
                cash_interest=validated['cash_interest']
            )
            account_ids.append(acc_id)
            print(f"   ✅ Created account: {validated['account_name']}")
    
    # Create test positions in first account (EPF)
    if account_ids:
        positions = [
            ('NIFTYBEES', Decimal('100')),   # Nifty 50 broad market equity
            ('ITBEES', Decimal('50')),       # IT sector equity
            ('HDFCLIQF', Decimal('200')),    # Fixed income / liquid fund
            ('JUNIORBEES', Decimal('150')),  # Nifty Next 50 equity
            ('GOLDBEES', Decimal('25')),     # Gold commodity
        ]
        
        account_id = account_ids[0]
        existing_positions = db_models.positions.find_by_account(account_id)
        
        if existing_positions:
            print(f"   ℹ️  Account already has {len(existing_positions)} positions")
        else:
            for symbol, quantity in positions:
                # Validate position with Pydantic
                position = PositionCreate(
                    account_id=account_id,
                    symbol=symbol,
                    quantity=quantity
                )
                validated = position.model_dump()
                db_models.positions.add_position(
                    validated['account_id'],
                    validated['symbol'],
                    validated['quantity']
                )
                print(f"   ✅ Added position: {quantity} shares of {symbol}")


def main():
    parser = argparse.ArgumentParser(description='Reset Samruddhi database')
    parser.add_argument('--with-test-data', action='store_true',
                       help='Create test user with sample portfolio')
    parser.add_argument('--skip-drop', action='store_true',
                       help='Skip dropping tables (just reload data)')
    args = parser.parse_args()
    
    print("🚀 Database Reset Script")
    print("=" * 50)
    
    # Initialize database
    db = DataAPIClient()
    db_models = Database()
    
    if not args.skip_drop:
        # Drop all tables
        drop_all_tables(db)
        
        # Run migrations
        print("\n📝 Running migrations...")
        import subprocess
        result = subprocess.run(['uv', 'run', 'run_migrations.py'], 
                              capture_output=True, text=True)
        
        if result.returncode != 0:
            print("❌ Migration failed!")
            print(result.stderr)
            sys.exit(1)
        else:
            print("✅ Migrations completed")
    
    # Load seed data
    print("\n🌱 Loading seed data...")
    import subprocess
    result = subprocess.run(['uv', 'run', 'seed_data.py'], 
                          capture_output=True, text=True)
    
    if result.returncode != 0:
        print("❌ Seed data failed!")
        print(result.stderr)
        sys.exit(1)
    else:
        # Extract instrument count from output
        if '10/10 instruments loaded' in result.stdout:
            print("✅ Loaded 10 instruments")
        else:
            print("✅ Seed data loaded")
    
    # Create test data if requested
    if args.with_test_data:
        create_test_data(db_models)
    
    # Final verification
    print("\n🔍 Final verification...")
    
    # Count records
    tables = ['users', 'instruments', 'accounts', 'positions', 'jobs']
    for table in tables:
        result = db.query(f"SELECT COUNT(*) as count FROM {table}")
        count = result[0]['count'] if result else 0
        print(f"   • {table}: {count} records")
    
    print("\n" + "=" * 50)
    print("✅ Database reset complete!")
    
    if args.with_test_data:
        print("\n📝 Test user created:")
        print("   • User ID: test_user_001")
        print("   • 3 accounts (EPF, PPF, Demat)")
        print("   • 5 positions in EPF account")


if __name__ == "__main__":
    main()