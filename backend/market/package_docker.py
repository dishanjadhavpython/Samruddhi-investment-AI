#!/usr/bin/env python3
"""
Package the market_eod Lambda using Docker, so pandas/numpy wheels match
Lambda's linux/amd64 runtime whatever machine you build on.

    uv run package_docker.py            # build market_lambda.zip
    uv run package_docker.py --deploy   # build and update samruddhi-market-eod
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()

NAME_PREFIX = os.getenv("NAME_PREFIX", "samruddhi")  # resource name prefix; set NAME_PREFIX in .env to match your deployment

# Modules the Lambda imports (the CLIs and tests stay out of the package)
MODULES = [
    "lambda_handler.py",
    "market_eod.py",
    "signals.py",
    "deployment.py",
    "indicators.py",
    "history.py",
    "zones.py",
    "breaks.py",
    "series.py",
    "sources.py",
    "store.py",
    "nse_files.py",
]

FUNCTION_NAME = f"{NAME_PREFIX}-market-eod"


def run_command(cmd, cwd=None):
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        sys.exit(1)
    return result.stdout


def package_lambda() -> Path:
    market_dir = Path(__file__).parent.absolute()
    backend_dir = market_dir.parent

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        package_dir = temp_path / "package"
        package_dir.mkdir()

        print("Exporting requirements from uv.lock...")
        requirements = run_command(["uv", "export", "--no-hashes", "--no-emit-project"], cwd=str(market_dir))
        # samruddhi-database is a workspace member; it is installed separately below
        filtered = [line for line in requirements.splitlines() if not line.strip().startswith("-e ")]
        (temp_path / "requirements.txt").write_text("\n".join(filtered))

        print("Installing dependencies for linux/amd64 in Docker...")
        run_command(
            [
                "docker", "run", "--rm",
                "--platform", "linux/amd64",
                "-v", f"{temp_path}:/build",
                "-v", f"{backend_dir}/database:/database",
                "--entrypoint", "/bin/bash",
                "public.ecr.aws/lambda/python:3.12",
                "-c",
                "cd /build && pip install --target ./package -r requirements.txt && pip install --target ./package --no-deps /database",
            ]
        )

        for module in MODULES:
            shutil.copy(market_dir / module, package_dir)

        zip_path = market_dir / "market_lambda.zip"
        if zip_path.exists():
            zip_path.unlink()
        run_command(["zip", "-qr", str(zip_path), "."], cwd=str(package_dir))
        print(f"Package created: {zip_path} ({zip_path.stat().st_size / (1024 * 1024):.1f} MB)")
        return zip_path


def deploy_lambda(zip_path: Path) -> None:
    """Upload through the Terraform-managed S3 object, then point the function at it."""
    import boto3

    account = boto3.client("sts").get_caller_identity()["Account"]
    bucket = f"{NAME_PREFIX}-market-{account}"
    key = "lambda/market_lambda.zip"
    boto3.client("s3").upload_file(str(zip_path), bucket, key)
    boto3.client("lambda").update_function_code(FunctionName=FUNCTION_NAME, S3Bucket=bucket, S3Key=key)
    print(f"Updated {FUNCTION_NAME} from s3://{bucket}/{key}")


def main():
    parser = argparse.ArgumentParser(description="Package the market_eod Lambda")
    parser.add_argument("--deploy", action="store_true", help="update the deployed function after packaging")
    args = parser.parse_args()

    try:
        run_command(["docker", "info"])
    except FileNotFoundError:
        print("Error: Docker is not installed or not in PATH")
        sys.exit(1)

    zip_path = package_lambda()
    if args.deploy:
        deploy_lambda(zip_path)


if __name__ == "__main__":
    main()
