"""
Tools for the Samruddhi Researcher agent
"""
import os
from typing import Dict, Any, List
from agents import function_tool
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential
import httpx

# Configuration from environment
INGEST_API_ENDPOINT = os.getenv("INGEST_API_ENDPOINT")
INGEST_API_KEY = os.getenv("INGEST_API_KEY")

# Must match TTL_DAYS in backend/ingest/ingest_s3vectors.py
DOC_TYPES = ("news", "regulator", "fund_factsheet", "research_note", "other")


class IngestRejected(Exception):
    """The ingest API refused the document (400); retrying won't help."""


def _ingest(document: Dict[str, Any]) -> Dict[str, Any]:
    """Internal function to make the actual API call."""
    with httpx.Client() as client:
        response = client.post(
            INGEST_API_ENDPOINT,
            json=document,
            headers={"x-api-key": INGEST_API_KEY},
            timeout=60.0
        )
        if response.status_code == 400:
            raise IngestRejected(response.json().get("error", response.text))
        response.raise_for_status()
        return response.json()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_not_exception_type(IngestRejected),
    reraise=True,
)
def ingest_with_retries(document: Dict[str, Any]) -> Dict[str, Any]:
    """Ingest with retry logic for SageMaker cold starts."""
    return _ingest(document)


@function_tool
def ingest_financial_document(
    topic: str,
    analysis: str,
    source_url: str,
    source_name: str,
    published_at: str,
    symbols: List[str],
    doc_type: str,
) -> Dict[str, Any]:
    """
    Save a short research note to the Samruddhi AI knowledge base.

    Args:
        topic: A short title for the note, e.g. "RBI keeps the repo rate unchanged"
        analysis: The note itself: factual bullet points, each with its figure and date
        source_url: The full https:// address of the page the facts came from
        source_name: The publisher, e.g. "Reserve Bank of India", "SEBI", "Economic Times"
        published_at: The date the source page was published, as YYYY-MM-DD
        symbols: NSE symbols the note is about, e.g. ["NIFTYBEES"]; an empty list for market-wide notes
        doc_type: One of news, regulator, fund_factsheet, research_note, other

    Returns:
        Dictionary with success status and document ID
    """
    if not INGEST_API_ENDPOINT or not INGEST_API_KEY:
        return {
            "success": False,
            "error": "Ingest API not configured. Running in local mode."
        }
    if doc_type not in DOC_TYPES:
        return {"success": False, "error": f"doc_type must be one of {', '.join(DOC_TYPES)}"}

    document = {
        "text": analysis,
        "metadata": {
            "title": topic,
            "source_url": source_url,
            "source_name": source_name,
            "published_at": published_at,
            "symbols": symbols,
            "doc_type": doc_type,
        }
    }

    try:
        result = ingest_with_retries(document)
        return {
            "success": True,
            "document_id": result.get("document_id"),
            "chunks": result.get("chunks"),
            "dropped_sentences": result.get("dropped_sentences"),
            "message": f"Saved the note on {topic}"
        }
    except IngestRejected as e:
        return {"success": False, "error": f"The knowledge base refused the note: {e}. Fix the fields and try once more."}
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
