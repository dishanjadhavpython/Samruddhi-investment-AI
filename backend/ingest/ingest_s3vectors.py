"""
Knowledge-base ingest v2 (plans/realtime-market-intelligence.md, section 8.6).

Every document is dated and sourced. It is filtered for sell-side language
(ratings, target prices, "top picks") so the Reporter can't repeat it, split
into chunks of about 200 words (the MiniLM embedding model truncates longer
text), and stored under keys derived from its source, so ingesting the same
source again overwrites it instead of adding duplicates.

Events:
- API Gateway, from the Researcher: body = {"text": ..., "metadata": {...}}
- Direct invoke, the daily market digest: {"action": "ingest", "documents": [{"text", "metadata"}]}
- Direct invoke, weekly housekeeping: {"action": "cleanup"} deletes expired vectors

metadata: title, source_name and published_at (ISO date) are required;
source_url is required except for code-generated documents, which pass a
stable doc_id instead; symbols (NSE tickers) and doc_type are optional.

Index: text, source_url and title are non-filterable metadata (see
create_index_v2.py); doc_type, symbols, published_ts, expires_ts and
source_name are filterable.
"""

import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timezone

import boto3

VECTOR_BUCKET = os.environ.get("VECTOR_BUCKET", "samruddhi-vectors")
SAGEMAKER_ENDPOINT = os.environ.get("SAGEMAKER_ENDPOINT")
INDEX_NAME = os.environ.get("INDEX_NAME", "financial-research-v2")
AWS_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("DEFAULT_AWS_REGION") or "us-east-1"

CHUNK_WORDS = 200
MAX_CHUNKS = 40
MAX_SYMBOLS = 10
MAX_TEXT_CHARS = 60_000
DAY = 86_400

# How long each kind of document stays searchable
TTL_DAYS = {
    "news": 30,
    "research_note": 30,
    "market_digest": 14,
    "regulator": 365,
    "fund_factsheet": 120,
    "other": 30,
}
URL_OPTIONAL = {"market_digest"}

# Sell-side language, dropped sentence by sentence before storing
SELL_SIDE = re.compile(
    r"\b(?:target price|price target|\bTP\b of|stop[- ]loss|upside (?:of|potential)|potential upside"
    r"|(?:strong )?buy (?:rating|call|recommendation)"
    r"|(?:sell|hold|accumulate|reduce|add|outperform|underperform|overweight|underweight|neutral) (?:rating|call|recommendation)"
    r"|(?:rates?|rated|rating) (?:it |the stock |the fund )?(?:a |as )?(?:buy|sell|hold|accumulate)"
    r"|top picks?|stock picks?|multibagger|buy on dips?|accumulate on dips?|sure[- ]?shot"
    r"|recommends? (?:buying|selling|investing|accumulating)|(?:analysts?|brokerages?|experts?) (?:recommend|suggest|advise)"
    r"|(?:should|must) (?:buy|sell|invest|accumulate|exit|book profits?))",
    re.IGNORECASE,
)
RATING_LABEL = re.compile(r"\b(?:BUY|SELL|HOLD|ACCUMULATE)\b")  # capitalised rating labels only
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
TICKER = re.compile(r"^[A-Z0-9&\-]{2,20}$")

sagemaker_runtime = boto3.client("sagemaker-runtime", region_name=AWS_REGION)
s3_vectors = boto3.client("s3vectors", region_name=AWS_REGION)


class IngestError(ValueError):
    pass


def get_embedding(text):
    """Get embedding vector from SageMaker endpoint."""
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT,
        ContentType="application/json",
        Body=json.dumps({"inputs": text}),
    )
    result = json.loads(response["Body"].read().decode())
    while isinstance(result, list) and result and isinstance(result[0], list):
        result = result[0]  # [[[embedding]]] -> [embedding]
    return result


def parse_date(value) -> datetime:
    if not value:
        raise IngestError("metadata.published_at is required (the date the source was published)")
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text) if "T" in text or " " in text else datetime.combine(date.fromisoformat(text[:10]), datetime.min.time())
    except ValueError:
        raise IngestError(f"metadata.published_at must be an ISO date, got {value!r}")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def filter_sell_side(text: str):
    """Drop sentences with ratings, targets or tips. Returns (kept sentences, dropped count)."""
    kept, dropped = [], 0
    for sentence in SENTENCE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if SELL_SIDE.search(sentence) or RATING_LABEL.search(sentence):
            dropped += 1
            continue
        kept.append(sentence)
    return kept, dropped


def chunk(sentences, size: int = CHUNK_WORDS):
    """Group sentences into chunks of at most `size` words; split any longer sentence."""
    chunks, current = [], []
    for sentence in sentences:
        words = sentence.split()
        while len(words) > size:
            if current:
                chunks.append(" ".join(current))
                current = []
            chunks.append(" ".join(words[:size]))
            words = words[size:]
        if len(current) + len(words) > size and current:
            chunks.append(" ".join(current))
            current = []
        current += words
    if current:
        chunks.append(" ".join(current))
    return chunks


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def prepare(document: dict, now: float) -> dict:
    """Validate one document and turn it into chunks with their keys and metadata."""
    text = (document.get("text") or "").strip()
    meta = document.get("metadata") or {}
    if not text:
        raise IngestError("text is required")
    text = text[:MAX_TEXT_CHARS]
    doc_type = meta.get("doc_type") or "other"
    if doc_type not in TTL_DAYS:
        raise IngestError(f"metadata.doc_type must be one of {sorted(TTL_DAYS)}")
    title = (meta.get("title") or meta.get("topic") or "").strip()
    source_name = (meta.get("source_name") or "").strip()
    source_url = (meta.get("source_url") or "").strip()
    if not title or not source_name:
        raise IngestError("metadata.title and metadata.source_name are required")
    if not source_url and doc_type not in URL_OPTIONAL:
        raise IngestError("metadata.source_url is required")
    if source_url and not source_url.startswith(("https://", "http://")):
        raise IngestError("metadata.source_url must be an http(s) URL")

    published = parse_date(meta.get("published_at")).timestamp()
    if published > now + DAY:
        raise IngestError("metadata.published_at is in the future")
    expires = published + TTL_DAYS[doc_type] * DAY
    if expires <= now:
        raise IngestError(f"the document is older than the {TTL_DAYS[doc_type]}-day limit for {doc_type}")

    symbols = sorted({str(s).strip().upper() for s in (meta.get("symbols") or []) if TICKER.match(str(s).strip().upper())})[:MAX_SYMBOLS]
    sentences, dropped = filter_sell_side(text)
    chunks = chunk(sentences)[:MAX_CHUNKS]
    if not chunks:
        raise IngestError("nothing left to store after removing sell-side language")

    # Same source, same keys: re-ingesting overwrites instead of duplicating
    basis = meta.get("doc_id") or source_url or "text:" + hashlib.sha256(normalise(text).encode()).hexdigest()
    doc_key = hashlib.sha256(basis.encode()).hexdigest()[:24]
    vectors = []
    for i, piece in enumerate(chunks):
        filterable = {
            "doc_type": doc_type,
            "published_ts": int(published),
            "expires_ts": int(expires),
            "source_name": source_name[:120],
            "doc_key": doc_key,
            "chunk": i,
            "chunks": len(chunks),
        }
        if symbols:
            filterable["symbols"] = symbols
        vectors.append(
            {
                "key": hashlib.sha256(f"{basis}#{i}".encode()).hexdigest(),
                "text": piece,
                "metadata": {**filterable, "text": piece, "title": title[:300], "source_url": source_url},
            }
        )
    return {"basis": basis, "doc_key": doc_key, "vectors": vectors, "dropped_sentences": dropped}


def store(prepared: dict) -> None:
    s3_vectors.put_vectors(
        vectorBucketName=VECTOR_BUCKET,
        indexName=INDEX_NAME,
        vectors=[
            {"key": v["key"], "data": {"float32": get_embedding(v["text"])}, "metadata": v["metadata"]}
            for v in prepared["vectors"]
        ],
    )
    # A shorter new version of the document leaves no stale chunks behind
    stale = [
        hashlib.sha256(f"{prepared['basis']}#{i}".encode()).hexdigest()
        for i in range(len(prepared["vectors"]), MAX_CHUNKS)
    ]
    if stale:
        s3_vectors.delete_vectors(vectorBucketName=VECTOR_BUCKET, indexName=INDEX_NAME, keys=stale)


def ingest(documents, now: float) -> dict:
    results = []
    for document in documents:
        try:
            prepared = prepare(document, now)
            store(prepared)
            results.append(
                {
                    "status": "ok",
                    "document_id": prepared["doc_key"],
                    "chunks": len(prepared["vectors"]),
                    "dropped_sentences": prepared["dropped_sentences"],
                }
            )
        except IngestError as e:
            results.append({"status": "rejected", "error": str(e)})
    return {"results": results}


def cleanup(now: float) -> dict:
    """Delete every vector whose expires_ts has passed (weekly schedule)."""
    expired, scanned, token = [], 0, None
    while True:
        kwargs = {"vectorBucketName": VECTOR_BUCKET, "indexName": INDEX_NAME, "maxResults": 500, "returnMetadata": True}
        if token:
            kwargs["nextToken"] = token
        page = s3_vectors.list_vectors(**kwargs)
        for v in page.get("vectors", []):
            scanned += 1
            expires = (v.get("metadata") or {}).get("expires_ts")
            if expires is None or float(expires) <= now:
                expired.append(v["key"])
        token = page.get("nextToken")
        if not token:
            break
    for start in range(0, len(expired), 500):
        s3_vectors.delete_vectors(vectorBucketName=VECTOR_BUCKET, indexName=INDEX_NAME, keys=expired[start : start + 500])
    return {"scanned": scanned, "deleted": len(expired)}


def _response(status: int, body: dict) -> dict:
    return {"statusCode": status, "body": json.dumps(body)}


def lambda_handler(event, context):
    now = time.time()
    try:
        action = event.get("action")
        if action == "cleanup":
            result = cleanup(now)
            print(f"Cleanup: {result}")
            return _response(200, result)
        if action == "ingest":
            result = ingest(event.get("documents") or [], now)
            print(f"Ingest: {result}")
            return _response(200, result)

        # API Gateway: one document in the request body
        body = json.loads(event["body"]) if isinstance(event.get("body"), str) else (event.get("body") or {})
        result = ingest([body], now)["results"][0]
        if result["status"] != "ok":
            return _response(400, {"error": result["error"]})
        return _response(200, {"message": "Document indexed successfully", **result})
    except Exception as e:
        print(f"Error: {e}")
        return _response(500, {"error": str(e)})
