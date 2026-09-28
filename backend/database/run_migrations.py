#!/usr/bin/env python3
"""
Tracked migration runner.

Applies migrations/*.sql in filename order. Statements inside a file are
separated by "-- statement" lines. Each file runs in one transaction together
with its row in schema_migrations, so a file is either fully applied or not
at all. Files already recorded are skipped, so running this again is a no-op.

Usage:
    uv run run_migrations.py            # apply pending migrations
    uv run run_migrations.py --status   # list applied and pending, change nothing
"""

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
STATEMENT_MARKER = re.compile(r"^--\s*statement\s*$", re.MULTILINE)

TRACKING_TABLE_SQL = """CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(100) PRIMARY KEY,
    checksum CHAR(64) NOT NULL,
    applied_at TIMESTAMPTZ DEFAULT NOW()
)"""


def split_statements(sql: str, name: str) -> list[str]:
    """Split a migration file on "-- statement" lines.

    Text before the first marker may only be comments. Comment-only lines
    inside a statement are dropped; trailing semicolons are removed because
    the Data API runs one statement per call.
    """
    chunks = STATEMENT_MARKER.split(sql)
    header, bodies = chunks[0], chunks[1:]
    if any(line.strip() and not line.strip().startswith("--") for line in header.splitlines()):
        raise ValueError(f"{name}: SQL found before the first '-- statement' marker")
    if not bodies:
        raise ValueError(f"{name}: no '-- statement' markers")

    statements = []
    for body in bodies:
        lines = [line for line in body.splitlines() if not line.strip().startswith("--")]
        statement = "\n".join(lines).strip().rstrip(";").strip()
        if statement:
            statements.append(statement)
    return statements


def load_migrations() -> list[dict]:
    migrations = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text()
        migrations.append({
            "version": path.stem,
            "checksum": hashlib.sha256(sql.encode()).hexdigest(),
            "statements": split_statements(sql, path.name),
        })
    return migrations


class Migrator:
    def __init__(self):
        self.cluster_arn = os.environ.get("AURORA_CLUSTER_ARN")
        self.secret_arn = os.environ.get("AURORA_SECRET_ARN")
        self.database = os.environ.get("AURORA_DATABASE", "samruddhi")
        if not self.cluster_arn or not self.secret_arn:
            raise ValueError("Missing AURORA_CLUSTER_ARN or AURORA_SECRET_ARN in environment variables")
        region = os.environ.get("DEFAULT_AWS_REGION", "us-east-1")
        self.client = boto3.client("rds-data", region_name=region)

    def execute(self, sql: str, parameters: list = None, transaction_id: str = None) -> dict:
        kwargs = {
            "resourceArn": self.cluster_arn,
            "secretArn": self.secret_arn,
            "database": self.database,
            "sql": sql,
        }
        if parameters:
            kwargs["parameters"] = parameters
        if transaction_id:
            kwargs["transactionId"] = transaction_id
        return self.client.execute_statement(**kwargs)

    def tracking_table_exists(self) -> bool:
        response = self.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = 'schema_migrations'"
        )
        return bool(response.get("records"))

    def applied(self) -> dict:
        """version -> (checksum, applied_at) for every recorded migration."""
        if not self.tracking_table_exists():
            return {}
        response = self.execute(
            "SELECT version, checksum, applied_at::text FROM schema_migrations ORDER BY version"
        )
        return {
            row[0]["stringValue"]: (row[1]["stringValue"], row[2]["stringValue"])
            for row in response.get("records", [])
        }

    def apply(self, migration: dict) -> None:
        """Run one migration file and record it, all in one transaction."""
        transaction_id = self.client.begin_transaction(
            resourceArn=self.cluster_arn, secretArn=self.secret_arn, database=self.database
        )["transactionId"]
        try:
            for statement in migration["statements"]:
                first_line = statement.splitlines()[0][:70]
                print(f"    {first_line}")
                self.execute(statement, transaction_id=transaction_id)
            self.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES (:version, :checksum)",
                [
                    {"name": "version", "value": {"stringValue": migration["version"]}},
                    {"name": "checksum", "value": {"stringValue": migration["checksum"]}},
                ],
                transaction_id,
            )
            self.client.commit_transaction(
                resourceArn=self.cluster_arn, secretArn=self.secret_arn, transactionId=transaction_id
            )
        except Exception:
            self.client.rollback_transaction(
                resourceArn=self.cluster_arn, secretArn=self.secret_arn, transactionId=transaction_id
            )
            raise


def main():
    parser = argparse.ArgumentParser(description="Apply database migrations")
    parser.add_argument("--status", action="store_true", help="list applied and pending migrations only")
    args = parser.parse_args()

    migrations = load_migrations()
    migrator = Migrator()
    applied = migrator.applied()

    print("🚀 Database migrations")
    print("=" * 50)

    pending = []
    for migration in migrations:
        version = migration["version"]
        if version in applied:
            checksum, applied_at = applied[version]
            note = "" if checksum == migration["checksum"] else "  ⚠️  file changed since it was applied (not re-run; add a new migration instead)"
            print(f"  ✅ {version} (applied {applied_at[:19]}){note}")
        else:
            print(f"  ⏳ {version} ({len(migration['statements'])} statements) pending")
            pending.append(migration)

    if args.status or not pending:
        print("\nNothing to apply." if not pending else f"\n{len(pending)} pending. Run without --status to apply.")
        return

    migrator.execute(TRACKING_TABLE_SQL)
    for migration in pending:
        print(f"\n▶ Applying {migration['version']}")
        try:
            migrator.apply(migration)
        except ClientError as e:
            print(f"\n❌ {migration['version']} failed and was rolled back: {e.response['Error']['Message']}")
            sys.exit(1)
        print(f"  ✅ {migration['version']} applied")

    print("\n✅ All migrations applied")
    print("\n📝 Next steps:")
    print("1. Load seed data: uv run seed_data.py")
    print("2. Test database operations: uv run test_data_api.py")


if __name__ == "__main__":
    main()
