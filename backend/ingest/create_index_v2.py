"""
Create the v2 knowledge-base index (plan section 8.6).

The console-created index "financial-research" treats all metadata as
filterable, and filterable metadata is capped at 2 KB per vector, which the
chunk text alone can exceed. v2 marks text, source_url and title as
non-filterable. The old index is left in place; nothing is deleted.

    uv run create_index_v2.py
"""

import os
import sys
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)

BUCKET = os.getenv("VECTOR_BUCKET")
REGION = os.getenv("DEFAULT_AWS_REGION", "us-east-1")
INDEX = "financial-research-v2"
NON_FILTERABLE = ["text", "source_url", "title"]


def main():
    if not BUCKET:
        sys.exit("VECTOR_BUCKET is not set in .env")
    client = boto3.client("s3vectors", region_name=REGION)
    existing = {i["indexName"] for i in client.list_indexes(vectorBucketName=BUCKET).get("indexes", [])}
    if INDEX in existing:
        print(f"{INDEX} already exists in {BUCKET}")
    else:
        client.create_index(
            vectorBucketName=BUCKET,
            indexName=INDEX,
            dataType="float32",
            dimension=384,  # all-MiniLM-L6-v2 (guides/2_sagemaker.md)
            distanceMetric="cosine",
            metadataConfiguration={"nonFilterableMetadataKeys": NON_FILTERABLE},
        )
        print(f"Created {INDEX} in {BUCKET}")
    index = client.get_index(vectorBucketName=BUCKET, indexName=INDEX)["index"]
    print(f"  dimension={index['dimension']} metric={index['distanceMetric']} metadata={index.get('metadataConfiguration')}")


if __name__ == "__main__":
    main()
