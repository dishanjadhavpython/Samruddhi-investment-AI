"""
Pricer v2: instrument prices, daily bars, mutual-fund NAVs and portfolio snapshots.

backend/pricer is the only writer of instruments.current_price
(backend/test_price_writers.py enforces this). Every price is stored with
prev_close, price_as_of, price_source and price_status:

  ok       fresh
  held     the new price moved more than 20% from the previous close; the old
           price stays until a later run sees the same value again (within 2%)
  stale    price_as_of is older than STALE_AFTER
  missing  no price at all

What gets priced: every catalogue instrument with a Yahoo ticker or an AMFI
scheme code, plus every symbol anyone holds (held stocks without a ticker are
tried as SYMBOL.NS).

During the session, exchange prices are 15 minutes delayed on purpose
(Phase 5): the price is the close of the newest 5-minute bar that ended at
least DELAY ago, whatever the source's own delay. The same delayed prices, the
Nifty 50 and India VIX go to DynamoDB (src/market_live.py) for
GET /api/market/snapshot.
"""

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from src import market_live

from sources import Bar, IntradayBar, Nav, fetch_amfi_navs, fetch_yahoo_daily, fetch_yahoo_intraday

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
SESSION_CLOSE = time(15, 30)
BARS_FINAL_AFTER = time(15, 45)  # today's daily bar is final after this
MAX_JUMP = 0.20
CONFIRM_TOLERANCE = 0.02
STALE_AFTER = timedelta(days=4)  # a weekend plus a holiday
DELAY = timedelta(minutes=market_live.DELAY_MINUTES)
BAR = timedelta(minutes=market_live.BAR_MINUTES)
RECENT = timedelta(minutes=60)  # intraday points rewritten each run, so a missed run leaves no gap

YAHOO = "yahoo"
AMFI = "amfi"


@dataclass
class PriceUpdate:
    symbol: str
    status: str  # "ok" or "held"
    price: Optional[float]  # the new current_price; None when held
    prev_close: Optional[float]
    as_of: datetime
    source: str
    held_price: Optional[float] = None


# ---------------------------------------------------------------------------
# Decisions (pure functions, unit-tested in test_simple.py)
# ---------------------------------------------------------------------------

def bar_as_of(trade_date: date, now: datetime) -> datetime:
    """When a daily bar's close was the price: now while that session is open, else the close."""
    close_at = datetime.combine(trade_date, SESSION_CLOSE, IST)
    return min(now, close_at)


@dataclass
class Quote:
    """The latest price that may be shown now, from today's 5-minute bars."""
    price: float
    as_of: datetime  # end of the bar it comes from
    day_open: Optional[float]
    day_high: Optional[float]
    day_low: Optional[float]


def shown_bars(bars: List[IntradayBar], now: datetime) -> List[IntradayBar]:
    """Today's 5-minute bars that ended at least DELAY ago."""
    today = now.astimezone(IST).date()
    return [b for b in bars if b.start.astimezone(IST).date() == today and b.start + BAR <= now - DELAY]


def delayed_quote(bars: List[IntradayBar], now: datetime) -> Optional[Quote]:
    shown = shown_bars(bars, now)
    if not shown:
        return None
    highs = [b.high for b in shown if b.high is not None]
    lows = [b.low for b in shown if b.low is not None]
    return Quote(
        price=shown[-1].close,
        as_of=shown[-1].start + BAR,
        day_open=shown[0].open,
        day_high=max(highs) if highs else None,
        day_low=min(lows) if lows else None,
    )


def apply_delay(bars: List[Bar], quote: Optional[Quote], now: datetime) -> Tuple[List[Bar], Optional[datetime]]:
    """Daily bars as they may be shown now, and the as-of time of the last one if it changed.

    Until today's bar is final (BARS_FINAL_AFTER, which is also when the delay
    runs out), today's in-progress bar gives way to the delayed quote, or is
    dropped when there isn't one yet, so nothing fresher than DELAY is stored.
    """
    local = now.astimezone(IST)
    if not bars or bars[-1].trade_date != local.date() or local.time() >= BARS_FINAL_AFTER:
        return bars, None
    if quote is None:
        return bars[:-1], None
    today = replace(bars[-1], open=quote.day_open, high=quote.day_high, low=quote.day_low, close=quote.price, adj_close=quote.price)
    return bars[:-1] + [today], quote.as_of


def recent_points(bars: List[IntradayBar], now: datetime, full_day: bool = False) -> List[Tuple[datetime, float]]:
    """(bar end, close) for today's shown bars: the last hour's, or the whole day's."""
    return [(b.start + BAR, b.close) for b in shown_bars(bars, now) if full_day or b.start + BAR > now - DELAY - RECENT]


def decide_price(symbol: str, bars: List[Bar], stored: Dict, now: datetime,
                 as_of: Optional[datetime] = None) -> Optional[PriceUpdate]:
    """Turn a ticker's recent daily bars into a price update, applying the ±20% hold."""
    if not bars:
        return None
    latest = bars[-1]
    prev_close = bars[-2].close if len(bars) >= 2 else None
    as_of = as_of or bar_as_of(latest.trade_date, now)

    if prev_close and abs(latest.close / prev_close - 1) > MAX_JUMP:
        held = stored.get("held_price")
        confirmed = (
            stored.get("price_status") == "held"
            and held
            and abs(latest.close / held - 1) <= CONFIRM_TOLERANCE
        )
        if not confirmed:
            return PriceUpdate(symbol, "held", None, prev_close, as_of, YAHOO, held_price=latest.close)

    return PriceUpdate(symbol, "ok", latest.close, prev_close, as_of, YAHOO)


def decide_nav(symbol: str, nav: Nav, previous_nav: Optional[float]) -> PriceUpdate:
    """A NAV is the fund's official daily price, so it is never held."""
    as_of = datetime.combine(nav.nav_date, time(0, 0), IST)
    return PriceUpdate(symbol, "ok", nav.nav, previous_nav, as_of, AMFI)


def final_bars(bars: List[Bar], now: datetime) -> List[Bar]:
    """Bars safe to store: finished sessions only (today's once the market has closed)."""
    local = now.astimezone(IST)
    today = local.date()
    return [b for b in bars if b.trade_date < today or (b.trade_date == today and local.time() >= BARS_FINAL_AFTER)]


def is_stale(as_of: Optional[datetime], now: datetime) -> bool:
    return as_of is None or now - as_of > STALE_AFTER


# ---------------------------------------------------------------------------
# Database access (Aurora Data API via the shared Database class)
# ---------------------------------------------------------------------------

def _param(name: str, value) -> Dict:
    if value is None:
        return {"name": name, "value": {"isNull": True}}
    if isinstance(value, bool):
        return {"name": name, "value": {"booleanValue": value}}
    if isinstance(value, int):
        return {"name": name, "value": {"longValue": value}}
    if isinstance(value, float):
        return {"name": name, "value": {"stringValue": repr(round(value, 6))}}
    if isinstance(value, (date, datetime)):
        return {"name": name, "value": {"stringValue": value.isoformat()}}
    return {"name": name, "value": {"stringValue": str(value)}}


def _params(**values) -> List[Dict]:
    return [_param(name, value) for name, value in values.items()]


def _float(value) -> Optional[float]:
    return float(value) if value not in (None, "") else None


def _timestamp(value) -> Optional[datetime]:
    """Data API returns TIMESTAMPTZ as a UTC string without an offset."""
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_targets(db) -> List[Dict]:
    rows = db.query_raw(
        """
        SELECT symbol, yahoo_ticker, amfi_scheme_code, current_price, prev_close,
               price_as_of::text AS price_as_of, price_source, price_status, held_price
        FROM instruments
        WHERE yahoo_ticker IS NOT NULL
           OR amfi_scheme_code IS NOT NULL
           OR symbol IN (SELECT DISTINCT symbol FROM positions)
        ORDER BY symbol
        """
    )
    for row in rows:
        row["held_price"] = _float(row.get("held_price"))
        row["current_price"] = _float(row.get("current_price"))
        row["price_as_of"] = _timestamp(row.get("price_as_of"))
        if not row.get("yahoo_ticker") and not row.get("amfi_scheme_code"):
            row["yahoo_ticker"] = f"{row['symbol']}.NS"  # held stock added by a user
    return rows


def write_price(db, update: PriceUpdate) -> None:
    if update.status == "held":
        db.execute_raw(
            "UPDATE instruments SET price_status = 'held', held_price = :held::numeric WHERE symbol = :symbol",
            _params(held=update.held_price, symbol=update.symbol),
        )
        return
    db.execute_raw(
        """
        UPDATE instruments
        SET current_price = :price::numeric, prev_close = :prev_close::numeric,
            price_as_of = :as_of::timestamptz, price_source = :source,
            price_status = 'ok', held_price = NULL
        WHERE symbol = :symbol
        """,
        _params(price=update.price, prev_close=update.prev_close, as_of=update.as_of,
                source=update.source, symbol=update.symbol),
    )


def write_bars(db, symbol: str, bars: List[Bar], source: str) -> int:
    if not bars:
        return 0
    sql = """
        INSERT INTO price_bars_daily (symbol, trade_date, open, high, low, close, adj_close, volume, source)
        VALUES (:symbol, :trade_date::date, :open::numeric, :high::numeric, :low::numeric,
                :close::numeric, :adj_close::numeric, :volume, :source)
        ON CONFLICT (symbol, trade_date) DO UPDATE SET
            open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close,
            adj_close = EXCLUDED.adj_close, volume = EXCLUDED.volume, source = EXCLUDED.source,
            ingested_at = NOW()
    """
    parameter_sets = [
        _params(symbol=symbol, trade_date=b.trade_date, open=b.open, high=b.high, low=b.low,
                close=b.close, adj_close=b.adj_close, volume=b.volume, source=source)
        for b in bars
    ]
    client = db.client
    for start in range(0, len(parameter_sets), 200):
        client.client.batch_execute_statement(
            resourceArn=client.cluster_arn, secretArn=client.secret_arn, database=client.database,
            sql=sql, parameterSets=parameter_sets[start:start + 200],
        )
    return len(parameter_sets)


def previous_bar_close(db, symbol: str, before: date) -> Optional[float]:
    rows = db.query_raw(
        """
        SELECT close FROM price_bars_daily
        WHERE symbol = :symbol AND trade_date < :before::date
        ORDER BY trade_date DESC LIMIT 1
        """,
        _params(symbol=symbol, before=before),
    )
    return _float(rows[0]["close"]) if rows else None


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def refresh_exchange_prices(db, now: datetime, full_day: bool = False) -> Dict[str, Any]:
    """Batched Yahoo downloads (daily and 5-minute bars) for every exchange-traded target and index.

    Writes delayed prices to Aurora, then publishes the same prices to DynamoDB.
    full_day rewrites all of today's intraday points instead of the last hour's.
    """
    targets = [t for t in load_targets(db) if t.get("yahoo_ticker")]
    index_tickers = {ticker: series_id for series_id, (_, ticker) in market_live.INDICES.items()}
    tickers = [t["yahoo_ticker"] for t in targets] + list(index_tickers)
    bars_by_ticker = fetch_yahoo_daily(tickers)
    try:
        intraday = fetch_yahoo_intraday(tickers)
    except Exception as e:
        # Without 5-minute bars, today's price waits (apply_delay drops the in-progress bar)
        logger.error(f"Yahoo intraday download failed: {e}")
        intraday = {}

    results: Dict[str, str] = {}
    live: List[Dict] = []
    points: List[Dict] = []
    for target in targets:
        symbol, ticker = target["symbol"], target["yahoo_ticker"]
        bars = bars_by_ticker.get(ticker, [])
        try:
            quote = delayed_quote(intraday.get(ticker, []), now)
            shown, as_of = apply_delay(bars, quote, now)
            update = decide_price(symbol, shown, target, now, as_of=as_of)
            if update is None:
                results[symbol] = "no data"
                logger.warning(f"{symbol}: no Yahoo data for {ticker}")
                continue
            write_price(db, update)
            stored = write_bars(db, symbol, final_bars(bars, now), YAHOO)
            if update.status == "held":
                results[symbol] = f"held {update.held_price} (prev close {update.prev_close})"
                logger.warning(f"{symbol}: {update.held_price} is >20% from {update.prev_close}; held for confirmation")
                continue  # DynamoDB keeps the last confirmed price
            results[symbol] = f"{update.price} ({stored} bars)"
            live.append(_live_item(symbol, "instrument", None, update, quote, now))
            points += market_live.intraday_items(symbol, recent_points(intraday.get(ticker, []), now, full_day))
        except Exception as e:
            logger.error(f"{symbol}: price refresh failed: {e}")
            results[symbol] = f"error: {e}"

    for ticker, series_id in index_tickers.items():
        quote = delayed_quote(intraday.get(ticker, []), now)
        shown, as_of = apply_delay(bars_by_ticker.get(ticker, []), quote, now)
        if not shown:
            results[series_id] = "no data"
            continue
        # Index levels skip the ±20% hold: India VIX can move that much in a day
        prev_close = shown[-2].close if len(shown) >= 2 else None
        update = PriceUpdate(series_id, "ok", shown[-1].close, prev_close, as_of or bar_as_of(shown[-1].trade_date, now), YAHOO)
        results[series_id] = f"{update.price}"
        live.append(_live_item(series_id, "index", market_live.INDICES[series_id][0], update, quote, now))
        points += market_live.intraday_items(series_id, recent_points(intraday.get(ticker, []), now, full_day))

    return {"prices": results, "live": publish_live(db, live, points, now)}


def _live_item(symbol: str, kind: str, name: Optional[str], update: PriceUpdate, quote: Optional[Quote], now: datetime) -> Dict:
    today = quote is not None and update.as_of == quote.as_of  # the day range only while the quote is the price
    return market_live.latest_item(
        symbol, kind=kind, name=name, price=update.price, prev_close=update.prev_close, as_of=update.as_of,
        source=update.source, updated_at=now,
        day_open=quote.day_open if today else None,
        day_high=quote.day_high if today else None,
        day_low=quote.day_low if today else None,
    )


def publish_live(db, live: List[Dict], points: List[Dict], now: datetime) -> str:
    """Write the delayed prices and intraday points to DynamoDB. A failure here never undoes the Aurora prices."""
    try:
        today = now.astimezone(IST).date()
        holidays = db.market.holidays(today - timedelta(days=7), today + timedelta(days=60))
        written = market_live.write_latest(live + [market_live.meta_item(holidays, YAHOO, now)])
        market_live.write_intraday(points)
        return f"{written - 1} prices, {len(points)} intraday points"
    except Exception as e:
        logger.error(f"Publishing to DynamoDB failed: {e}")
        return f"error: {e}"


def refresh_navs(db, now: datetime) -> Dict[str, str]:
    """Latest AMFI NAV for every fund with a scheme code."""
    targets = [t for t in load_targets(db) if t.get("amfi_scheme_code")]
    navs = fetch_amfi_navs(t["amfi_scheme_code"] for t in targets)

    results: Dict[str, str] = {}
    for target in targets:
        symbol = target["symbol"]
        nav = navs.get(target["amfi_scheme_code"])
        if nav is None:
            results[symbol] = "not in NAVAll.txt"
            logger.warning(f"{symbol}: scheme {target['amfi_scheme_code']} not found in AMFI file")
            continue
        try:
            update = decide_nav(symbol, nav, previous_bar_close(db, symbol, nav.nav_date))
            write_price(db, update)
            write_bars(db, symbol, [Bar(nav.nav_date, None, None, None, nav.nav, nav.nav, None)], AMFI)
            results[symbol] = f"NAV {nav.nav} of {nav.nav_date}"
        except Exception as e:
            logger.error(f"{symbol}: NAV refresh failed: {e}")
            results[symbol] = f"error: {e}"
    return results


def mark_stale(db, now: datetime) -> None:
    db.execute_raw(
        "UPDATE instruments SET price_status = 'stale' WHERE price_status = 'ok' AND price_as_of < :cutoff::timestamptz",
        _params(cutoff=now - STALE_AFTER),
    )
    db.execute_raw(
        "UPDATE instruments SET price_status = 'missing' WHERE current_price IS NULL OR current_price = 0"
    )


def write_snapshots(db, now: datetime) -> int:
    """One row per user for today (IST): holdings value, cost basis and cash.

    invested_value is the holdings' cost basis from the transaction ledger;
    it stays NULL for a user while any holding has no known cost.
    """
    response = db.execute_raw(
        """
        INSERT INTO portfolio_snapshots (clerk_user_id, snap_date, market_value, invested_value, cash)
        SELECT a.clerk_user_id, :snap_date::date,
               COALESCE(SUM(h.value), 0),
               CASE WHEN SUM(h.unknown_cost) = 0 OR SUM(h.unknown_cost) IS NULL THEN COALESCE(SUM(h.cost), 0) END,
               COALESCE(SUM(a.cash_balance), 0)
        FROM accounts a
        LEFT JOIN (
            SELECT p.account_id, SUM(p.quantity * i.current_price) AS value, SUM(p.cost_basis) AS cost,
                   SUM(CASE WHEN p.cost_basis IS NULL THEN 1 ELSE 0 END) AS unknown_cost
            FROM positions p JOIN instruments i ON i.symbol = p.symbol
            GROUP BY p.account_id
        ) h ON h.account_id = a.id
        GROUP BY a.clerk_user_id
        ON CONFLICT (clerk_user_id, snap_date) DO UPDATE SET
            market_value = EXCLUDED.market_value, invested_value = EXCLUDED.invested_value, cash = EXCLUDED.cash
        """,
        _params(snap_date=now.astimezone(IST).date()),
    )
    return response.get("numberOfRecordsUpdated", 0)
