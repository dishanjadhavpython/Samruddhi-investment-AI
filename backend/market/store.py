"""
Aurora access for the market pipeline, through the shared Database class
(Data API). Tables come from migrations 003 and 004.
"""

import json
from datetime import date, datetime
from typing import Dict, Iterable, List, Tuple

import pandas as pd

from series import Break

BATCH = 200  # rows per batch_execute_statement call
PAGE = 2000  # rows per read, well under the Data API's 1 MiB response limit


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
    if isinstance(value, (dict, list)):
        return {"name": name, "value": {"stringValue": json.dumps(value, separators=(",", ":"))}}
    return {"name": name, "value": {"stringValue": str(value)}}


def _params(**values) -> List[Dict]:
    return [_param(name, value) for name, value in values.items()]


def _batch(db, sql: str, parameter_sets: List[List[Dict]]) -> None:
    client = db.client
    for start in range(0, len(parameter_sets), BATCH):
        client.client.batch_execute_statement(
            resourceArn=client.cluster_arn,
            secretArn=client.secret_arn,
            database=client.database,
            sql=sql,
            parameterSets=parameter_sets[start : start + BATCH],
        )


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------

def upsert_series(db, series_id: str, points: Iterable[Tuple[date, float]], source: str) -> int:
    sql = """
        INSERT INTO market_series (series_id, obs_date, value, source)
        VALUES (:series_id, :obs_date::date, :value::numeric, :source)
        ON CONFLICT (series_id, obs_date) DO UPDATE SET value = EXCLUDED.value, source = EXCLUDED.source
    """
    parameter_sets = [
        _params(series_id=series_id, obs_date=day, value=float(value), source=source) for day, value in points
    ]
    _batch(db, sql, parameter_sets)
    return len(parameter_sets)


def load_series(db, series_id: str) -> pd.Series:
    """Every observation of one series, oldest first, read in pages."""
    dates: List[str] = []
    values: List[float] = []
    after = "1900-01-01"
    while True:
        rows = db.query_raw(
            """
            SELECT obs_date::text AS d, value::text AS v FROM market_series
            WHERE series_id = :series_id AND obs_date > :after::date
            ORDER BY obs_date LIMIT :page
            """,
            _params(series_id=series_id, after=after, page=PAGE),
        )
        dates.extend(row["d"] for row in rows)
        values.extend(float(row["v"]) for row in rows)
        if len(rows) < PAGE:
            break
        after = rows[-1]["d"]
    return pd.Series(values, index=pd.to_datetime(dates), dtype=float, name=series_id)


def series_coverage(db) -> List[Dict]:
    return db.query_raw(
        """
        SELECT series_id, COUNT(*) AS n, MIN(obs_date)::text AS first, MAX(obs_date)::text AS last
        FROM market_series GROUP BY series_id ORDER BY series_id
        """
    )


# ---------------------------------------------------------------------------
# Breaks and holidays
# ---------------------------------------------------------------------------

def register_breaks(db, breaks: List[Break]) -> None:
    """Add known breaks; an existing row (possibly edited by hand) is kept."""
    sql = """
        INSERT INTO market_series_breaks (series_id, break_date, factor, note)
        VALUES (:series_id, :break_date::date, :factor::numeric, :note)
        ON CONFLICT (series_id, break_date) DO NOTHING
    """
    _batch(db, sql, [_params(series_id=b.series_id, break_date=b.break_date, factor=b.factor, note=b.note) for b in breaks])


def load_breaks(db) -> List[Break]:
    rows = db.query_raw(
        "SELECT series_id, break_date::text AS d, factor::text AS f, note FROM market_series_breaks ORDER BY break_date"
    )
    return [Break(r["series_id"], date.fromisoformat(r["d"]), float(r["f"]), r.get("note") or "") for r in rows]


def upsert_holidays(db, holidays: Dict[date, str], exchange: str = "NSE") -> None:
    sql = """
        INSERT INTO market_holidays (trade_date, exchange, description)
        VALUES (:trade_date::date, :exchange, :description)
        ON CONFLICT (trade_date) DO UPDATE SET exchange = EXCLUDED.exchange, description = EXCLUDED.description
    """
    _batch(db, sql, [_params(trade_date=day, exchange=exchange, description=text) for day, text in sorted(holidays.items())])


# ---------------------------------------------------------------------------
# Outputs read by the API
# ---------------------------------------------------------------------------

def write_signal(db, result, method_version: str) -> None:
    db.execute_raw(
        """
        INSERT INTO market_signals (as_of, method_version, valuation_score, zone, indicators, history_stats, narrative)
        VALUES (:as_of::date, :method_version, :score::numeric, :zone, :indicators::jsonb, :history::jsonb, NULL)
        ON CONFLICT (as_of, method_version) DO UPDATE SET
            valuation_score = EXCLUDED.valuation_score, zone = EXCLUDED.zone,
            indicators = EXCLUDED.indicators, history_stats = EXCLUDED.history_stats,
            created_at = NOW()
        """,
        _params(
            as_of=result.as_of,
            method_version=method_version,
            score=result.valuation_score,
            zone=result.zone,
            indicators=result.indicators,
            history=result.history_stats,
        ),
    )


def write_chart(db, chart_id: str, method_version: str, as_of: date, payload: Dict) -> int:
    text = json.dumps(payload, separators=(",", ":"))
    db.execute_raw(
        """
        INSERT INTO market_charts (chart_id, method_version, as_of, payload)
        VALUES (:chart_id, :method_version, :as_of::date, :payload::jsonb)
        ON CONFLICT (chart_id, method_version) DO UPDATE SET
            as_of = EXCLUDED.as_of, payload = EXCLUDED.payload, updated_at = NOW()
        """,
        [
            *_params(chart_id=chart_id, method_version=method_version, as_of=as_of),
            {"name": "payload", "value": {"stringValue": text}},
        ],
    )
    return len(text)
