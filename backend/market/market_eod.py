"""
The daily market job (plan section 7): 19:00 IST, Mon-Fri.

1. Load any valuation/TRI files dropped into the market bucket's incoming/
   folder (downloaded by hand from niftyindices.com).
2. Add the latest Nifty 50 and India VIX closes.
3. Recompute the valuation temperature, turbulence and history tables, and
   write one market_signals row plus the Market page charts.

Runs are idempotent: re-running a day overwrites that day's row.
"""

import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import nse_files
import signals
import store
from series import (
    DY,
    INDIAVIX,
    KNOWN_BREAKS,
    METHOD_VERSION,
    NIFTY50,
    NSE_HOLIDAYS,
    PB,
    PE,
    SOURCE_NIFTY_INDICES,
    SOURCE_YAHOO,
    TRI,
    YAHOO_TICKERS,
)
from sources import fetch_yahoo_closes, final_closes

logger = logging.getLogger(__name__)

INCOMING = "incoming/"
PROCESSED = "processed/"
REJECTED = "rejected/"


def load_parsed(db, parsed: List[nse_files.ParsedFile]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for series_id, points in nse_files.merge(parsed).items():
        counts[series_id] = store.upsert_series(db, series_id, sorted(points.items()), SOURCE_NIFTY_INDICES)
    return counts


def ingest_incoming(db, s3, bucket: str) -> Dict:
    """Parse every file under incoming/, then move it to processed/ or rejected/."""
    listing = s3.list_objects_v2(Bucket=bucket, Prefix=INCOMING)
    keys = [o["Key"] for o in listing.get("Contents", []) if not o["Key"].endswith("/")]
    if not keys:
        return {"files": 0}
    parsed, rejected = [], []
    with tempfile.TemporaryDirectory() as tmp:
        for key in keys:
            local = Path(tmp) / Path(key).name
            s3.download_file(bucket, key, str(local))
            try:
                parsed.append((key, nse_files.parse_file(local)))
            except nse_files.NseFileError as e:
                logger.error("Rejected %s: %s", key, e)
                rejected.append({"key": key, "error": str(e)})
    counts = load_parsed(db, [p for _, p in parsed])
    for key, _ in parsed:
        _move(s3, bucket, key, PROCESSED)
    for item in rejected:
        _move(s3, bucket, item["key"], REJECTED)
    return {"files": len(keys), "loaded": counts, "rejected": rejected}


def _move(s3, bucket: str, key: str, prefix: str) -> None:
    target = prefix + key[len(INCOMING):]
    s3.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": key}, Key=target)
    s3.delete_object(Bucket=bucket, Key=key)


def update_closes(db, now: datetime, period: str = "1mo") -> Dict[str, int]:
    closes = fetch_yahoo_closes(YAHOO_TICKERS, period=period)
    counts = {}
    for series_id, series in closes.items():
        final = final_closes(series, now)
        counts[series_id] = store.upsert_series(db, series_id, [(d.date(), v) for d, v in final.items()], SOURCE_YAHOO)
    return counts


def load_market_data(db) -> signals.MarketData:
    return signals.MarketData(
        nifty=store.load_series(db, NIFTY50),
        vix=store.load_series(db, INDIAVIX),
        tri=store.load_series(db, TRI),
        pe=store.load_series(db, PE),
        pb=store.load_series(db, PB),
        dy=store.load_series(db, DY),
        breaks=store.load_breaks(db),
    )


def compute_and_store(db, now: datetime) -> Dict:
    data = load_market_data(db)
    result = signals.compute(data, now.date())
    store.write_signal(db, result, METHOD_VERSION)
    sizes = {chart_id: store.write_chart(db, chart_id, METHOD_VERSION, result.as_of, payload) for chart_id, payload in result.charts.items()}
    candidates = result.indicators["breaks"]["unregistered_candidates"]
    if candidates:
        logger.warning("Possible methodology breaks to review: %s", candidates)
    return {
        "as_of": result.as_of.isoformat(),
        "valuation_score": result.valuation_score,
        "zone": result.zone,
        "has_history_table": result.history_stats is not None,
        "chart_bytes": sizes,
        "break_candidates": candidates,
    }


def run(db, s3=None, bucket: Optional[str] = None, now: Optional[datetime] = None, period: str = "1mo") -> Dict:
    now = now or datetime.now(timezone.utc)
    store.register_breaks(db, KNOWN_BREAKS)
    store.upsert_holidays(db, NSE_HOLIDAYS)
    summary: Dict = {}
    if s3 is not None and bucket:
        summary["incoming"] = ingest_incoming(db, s3, bucket)
    summary["closes"] = update_closes(db, now, period)
    summary.update(compute_and_store(db, now))
    return summary
