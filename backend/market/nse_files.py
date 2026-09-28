"""
Reads Nifty 50 valuation and Total Return Index files downloaded by hand from
https://www.niftyindices.com/reports/historical-data.

NSE Indices' terms forbid automated collection, so this module only parses
files a person saved; it never fetches anything. It accepts the site's CSV
export and the JSON shape used by plans/backtest-reference/, matches columns
by name rather than position, and rejects files for any other index.
"""

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from series import DY, PB, PE, TRI

DATE_FORMATS = ("%d %b %Y", "%d-%b-%Y", "%d %b %y", "%d-%b-%y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%b %d, %Y", "%d %B %Y")

# Plausible ranges; a value outside them is a parsing problem, not data
BOUNDS = {PE: (5.0, 80.0), PB: (0.5, 15.0), DY: (0.05, 10.0), TRI: (100.0, 10_000_000.0)}

TARGET_INDEX = "NIFTY50"


class NseFileError(ValueError):
    pass


@dataclass
class ParsedFile:
    path: str
    kind: str  # "valuation" or "tri"
    rows: int = 0
    skipped: int = 0
    first: Optional[date] = None
    last: Optional[date] = None
    series: Dict[str, Dict[date, float]] = field(default_factory=dict)


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def _find(headers: Iterable[str], *patterns: str) -> Optional[str]:
    for header in headers:
        key = _key(header)
        if any(re.fullmatch(p, key) for p in patterns):
            return header
    return None


def parse_date(text: str) -> date:
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise NseFileError(f"unrecognised date {text!r}")


def parse_number(text) -> Optional[float]:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    cleaned = str(text).replace(",", "").replace("%", "").strip()
    if cleaned in ("", "-", "--", "NA", "N/A", "null"):
        return None
    return float(cleaned)


def read_records(path: Path) -> List[Dict[str, str]]:
    raw = path.read_bytes().decode("utf-8-sig", errors="replace")
    if path.suffix.lower() == ".json":
        data = json.loads(raw)
        if isinstance(data, dict):  # {"d": "[...]"} style wrappers
            data = next((v for v in data.values() if isinstance(v, (list, str))), [])
        if isinstance(data, str):
            data = json.loads(data)
        return [dict(r) for r in data]
    # Some exports carry a title line above the header row
    lines = raw.splitlines()
    start = next((i for i, line in enumerate(lines) if "date" in line.lower()), 0)
    return list(csv.DictReader(io.StringIO("\n".join(lines[start:]))))


def parse_file(path: Path) -> ParsedFile:
    records = read_records(path)
    if not records:
        raise NseFileError(f"{path.name}: no rows")
    headers = list(records[0].keys())

    date_col = _find(headers, r"date", r"historicaldate", r"indexdate")
    name_col = _find(headers, r"indexname", r"index", r"name")
    pe_col = _find(headers, r"pe", r"peratio")
    pb_col = _find(headers, r"pb", r"pbratio")
    dy_col = _find(headers, r"divyield", r"dividendyield", r"divyieldpct")
    tri_col = _find(headers, r"totalreturnsindex", r"totalreturnindex", r"totalreturnsindexvalue", r"tri")
    if not date_col:
        raise NseFileError(f"{path.name}: no date column in {headers}")

    if pe_col or pb_col:
        kind, columns = "valuation", {PE: pe_col, PB: pb_col, DY: dy_col}
    elif tri_col:
        kind, columns = "tri", {TRI: tri_col}
    else:
        raise NseFileError(
            f"{path.name}: expected P/E, P/B and Div Yield columns, or a Total Returns Index column; found {headers}"
        )

    parsed = ParsedFile(str(path), kind, series={sid: {} for sid, col in columns.items() if col})
    for record in records:
        if name_col and record.get(name_col):
            name = re.sub(r"[^A-Z0-9]", "", str(record[name_col]).upper())
            if name != TARGET_INDEX:
                raise NseFileError(f"{path.name}: this file is for {record[name_col]!r}, not NIFTY 50")
        try:
            day = parse_date(str(record[date_col]))
        except (NseFileError, KeyError, TypeError):
            parsed.skipped += 1
            continue
        kept = False
        for series_id, column in columns.items():
            if not column:
                continue
            try:
                value = parse_number(record.get(column))
            except ValueError:
                value = None
            low, high = BOUNDS[series_id]
            if value is not None and low <= value <= high:
                parsed.series[series_id][day] = value
                kept = True
        if kept:
            parsed.rows += 1
            parsed.first = min(parsed.first or day, day)
            parsed.last = max(parsed.last or day, day)
        else:
            parsed.skipped += 1
    if not parsed.rows:
        raise NseFileError(f"{path.name}: no usable rows")
    return parsed


def collect_files(inputs: Iterable[str]) -> List[Path]:
    paths: List[Path] = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            paths.extend(sorted(x for x in p.iterdir() if x.suffix.lower() in (".csv", ".json")))
        elif p.exists():
            paths.append(p)
        else:
            raise NseFileError(f"{item}: not found")
    return paths


def merge(files: List[ParsedFile]) -> Dict[str, Dict[date, float]]:
    """One {date: value} map per series; later files win on overlapping dates."""
    merged: Dict[str, Dict[date, float]] = {}
    for parsed in files:
        for series_id, points in parsed.series.items():
            merged.setdefault(series_id, {}).update(points)
    return merged
