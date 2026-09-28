"""
Near-real-time market data in DynamoDB (plans/realtime-market-intelligence.md, Phase 5).

backend/pricer writes it every 5 minutes during the NSE session, and
GET /api/market/snapshot reads it, so an open tab can poll every minute
without touching Aurora.

  samruddhi-market-latest    PK symbol. One item per instrument or index, plus "_meta"
                        (source, delay and exchange holidays, for the session state).
  samruddhi-market-intraday  PK series ("NIFTY50#2026-09-28"), SK minute (minutes after
                        midnight IST at the end of the 5-minute bar). Items expire
                        after 7 days.

Every price is published DELAY_MINUTES after the end of the 5-minute bar it
comes from, whatever the source's own delay, so "15 min delayed" is always true.
Yahoo Finance is demo data; a licensed vendor must replace it before any public
launch (section 10.4).
"""

import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .market_session import CLOSE, IST, OPEN, session_state

LATEST_TABLE = os.getenv("MARKET_LATEST_TABLE", "samruddhi-market-latest")
INTRADAY_TABLE = os.getenv("MARKET_INTRADAY_TABLE", "samruddhi-market-intraday")
DELAY_MINUTES = int(os.getenv("SNAPSHOT_DELAY_MINUTES", "15"))
BAR_MINUTES = 5
INTRADAY_TTL = timedelta(days=7)
META = "_meta"
MAX_SYMBOLS = 50

# Index-level series for the Market page, with their Yahoo tickers (as in backend/market/series.py)
INDICES: Dict[str, Tuple[str, str]] = {"NIFTY50": ("Nifty 50", "^NSEI"), "INDIAVIX": ("India VIX", "^INDIAVIX")}
SOURCE_LABELS = {"yahoo": "Yahoo Finance (demo data)"}


def _clock(at: time, minutes: int) -> time:
    return (datetime.combine(date.min, at) + timedelta(minutes=minutes)).time()


# The first bar (09:15-09:20) can be shown at 09:35 and the last (15:25-15:30)
# at 15:45; the pricer runs every 5 minutes, so readers look for new prices
# from 09:36 until 15:50 IST.
FIRST_UPDATE = _clock(OPEN, BAR_MINUTES + DELAY_MINUTES + 1)
LAST_UPDATE = _clock(CLOSE, DELAY_MINUTES + BAR_MINUTES)


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested in test_market_live.py)
# ---------------------------------------------------------------------------

def update_window(now: datetime, holidays: Iterable[date]) -> Dict:
    """Whether delayed prices can still change today, until when, or when they next will."""
    closed = set(holidays)
    local = now.astimezone(IST)
    today = local.date()

    def trading_day(day: date) -> bool:
        return day.weekday() < 5 and day not in closed

    if trading_day(today) and FIRST_UPDATE <= local.time() < LAST_UPDATE:
        return {"active": True, "until": datetime.combine(today, LAST_UPDATE, IST).isoformat(), "next": None}
    day = today if trading_day(today) and local.time() < FIRST_UPDATE else today + timedelta(days=1)
    while not trading_day(day):
        day += timedelta(days=1)
    return {"active": False, "until": None, "next": datetime.combine(day, FIRST_UPDATE, IST).isoformat()}


def _dec(value: Optional[float], places: int = 4) -> Optional[Decimal]:
    return None if value is None else Decimal(str(round(float(value), places)))


def latest_item(
    symbol: str,
    *,
    kind: str,
    price: float,
    prev_close: Optional[float],
    as_of: datetime,
    source: str,
    updated_at: datetime,
    name: Optional[str] = None,
    day_open: Optional[float] = None,
    day_high: Optional[float] = None,
    day_low: Optional[float] = None,
) -> Dict:
    """One samruddhi-market-latest item. change_pct is a fraction (0.012 = 1.2%), like /api/market/*."""
    change = price - prev_close if prev_close else None
    item = {
        "symbol": symbol,
        "kind": kind,
        "name": name,
        "price": _dec(price),
        "prev_close": _dec(prev_close),
        "change": _dec(change),
        "change_pct": _dec(change / prev_close, 6) if change is not None else None,
        "day_open": _dec(day_open),
        "day_high": _dec(day_high),
        "day_low": _dec(day_low),
        "as_of": as_of.astimezone(IST).isoformat(),
        "source": source,
        "delay_minutes": DELAY_MINUTES,
        "updated_at": updated_at.astimezone(IST).isoformat(),
    }
    return {k: v for k, v in item.items() if v is not None}


def meta_item(holidays: Iterable[date], source: str, updated_at: datetime) -> Dict:
    return {
        "symbol": META,
        "kind": "meta",
        "source": source,
        "delay_minutes": DELAY_MINUTES,
        "bar_minutes": BAR_MINUTES,
        "holidays": sorted(d.isoformat() for d in holidays),
        "updated_at": updated_at.astimezone(IST).isoformat(),
    }


def intraday_items(symbol: str, points: Sequence[Tuple[datetime, float]]) -> List[Dict]:
    """samruddhi-market-intraday items for (bar end, price) points."""
    items = []
    for end, price in points:
        local = end.astimezone(IST)
        items.append({
            "series": f"{symbol}#{local.date().isoformat()}",
            "minute": local.hour * 60 + local.minute,
            "price": _dec(price),
            "expires_at": int((end + INTRADAY_TTL).timestamp()),
        })
    return items


def _plain(value):
    """DynamoDB Decimals back to floats (the few integer fields are cast where they are read)."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# DynamoDB access
# ---------------------------------------------------------------------------

_resource = None


def resource():
    """One boto3 resource per process (Lambda keeps it warm between requests)."""
    global _resource
    if _resource is None:
        import boto3

        _resource = boto3.resource("dynamodb", region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1"))
    return _resource


def write_latest(items: List[Dict], dynamodb=None) -> int:
    table = (dynamodb or resource()).Table(LATEST_TABLE)
    with table.batch_writer(overwrite_by_pkeys=["symbol"]) as batch:
        for item in items:
            batch.put_item(Item=item)
    return len(items)


def write_intraday(items: List[Dict], dynamodb=None) -> int:
    table = (dynamodb or resource()).Table(INTRADAY_TABLE)
    with table.batch_writer(overwrite_by_pkeys=["series", "minute"]) as batch:
        for item in items:
            batch.put_item(Item=item)
    return len(items)


def read_snapshot(symbols: Sequence[str], now: datetime, intraday: Sequence[str] = (), dynamodb=None) -> Dict:
    """Delayed prices for the indices and the given symbols, plus the session state.

    Two DynamoDB calls at most (BatchGetItem, then a Query per intraday
    series); nothing here reads Aurora.
    """
    from boto3.dynamodb.conditions import Key

    dynamodb = dynamodb or resource()
    wanted = list(dict.fromkeys([META, *INDICES, *symbols]))
    keys = [{"symbol": s} for s in wanted]
    items: Dict[str, Dict] = {}
    for _ in range(3):  # BatchGetItem may return some keys unprocessed under load
        response = dynamodb.batch_get_item(RequestItems={LATEST_TABLE: {"Keys": keys}})
        for item in response.get("Responses", {}).get(LATEST_TABLE, []):
            plain = _plain(item)
            if "delay_minutes" in plain:
                plain["delay_minutes"] = int(plain["delay_minutes"])
            items[item["symbol"]] = plain
        keys = response.get("UnprocessedKeys", {}).get(LATEST_TABLE, {}).get("Keys", [])
        if not keys:
            break

    meta = items.pop(META, None) or {}
    holidays = [date.fromisoformat(d) for d in meta.get("holidays", [])]
    source = meta.get("source")
    body = {
        "available": bool(items),
        "session": session_state(now, holidays),
        "updates": update_window(now, holidays),
        "source": source,
        "source_label": SOURCE_LABELS.get(source, source),
        "delay_minutes": int(meta.get("delay_minutes", DELAY_MINUTES)),
        "updated_at": meta.get("updated_at"),
        "indices": {s: items[s] for s in INDICES if s in items},
        "quotes": {s: items[s] for s in symbols if s in items},
        "intraday": {},
    }
    for series_id in intraday:
        index = body["indices"].get(series_id)
        if not index:
            continue
        day = index["as_of"][:10]  # the IST date of the latest price
        response = dynamodb.Table(INTRADAY_TABLE).query(KeyConditionExpression=Key("series").eq(f"{series_id}#{day}"))
        points = [[int(i["minute"]), float(i["price"])] for i in response.get("Items", [])]
        body["intraday"][series_id] = {"date": day, "points": points}
    return body
