#!/usr/bin/env python3
"""
Apply migration 002: set the new-user default for users.region_targets to an
India-first split ({"india": 70, "international": 30}).

Existing user rows are NOT backfilled - this only changes the column default
applied to rows inserted after this migration runs. See
migrations/002_add_india_region_default.sql for the exact statement.
"""

import os
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

SQL = """
    ALTER TABLE users ALTER COLUMN region_targets
    SET DEFAULT '{"india": 70, "international": 30}'::jsonb
"""


def main():
    print("🚀 Applying migration 002: India-first region_targets default")
    print("=" * 50)
    print("This changes the DEFAULT for NEW rows only - existing users are not backfilled.")

    try:
        client.execute_statement(
            resourceArn=cluster_arn,
            secretArn=secret_arn,
            database=database,
            sql=SQL,
        )
        print("\n✅ Migration 002 applied successfully!")
        print("   New users will now default to region_targets = "
              '{"india": 70, "international": 30}')
    except ClientError as e:
        print(f"\n❌ Error applying migration: {e.response['Error']['Message'][:200]}")
        exit(1)


if __name__ == "__main__":
    main()
