"""
Reads transaction CSVs for POST /api/transactions/import.

Takes the app's own template and common broker exports. A Zerodha Console
tradebook's header is symbol,isin,trade_date,exchange,segment,series,
trade_type,auction,quantity,price,trade_id,order_id,order_execution_time,
with lower-case buy/sell (checked against open-source importers, e.g.
ananthakumaran/paisa's fixture, on 28 Sep 2026).
Headers are matched loosely, dates in the usual Indian formats are
accepted, and "₹1,23,456.50" reads as a number. Each row gets a stable
reference (the broker's trade id, or a hash of the row) so importing the same
file twice records nothing new.
"""

import csv
import hashlib
import io
import re
from datetime import date, datetime
from typing import Dict, List, Optional

from .returns import DAY_ORDER, TXN_TYPES, Txn, validate

MAX_ROWS = 2000

TEMPLATE = "date,type,symbol,quantity,price,amount,fees,reference,note\n" \
           "2024-04-01,opening_balance,NIFTYBEES,100,215.40,,,,Held before I started tracking\n" \
           "2025-01-15,buy,NIFTYBEES,20,262.10,,15.50,,\n" \
           "2025-06-10,dividend,NIFTYBEES,,,84.00,,,\n"

# Canonical field -> accepted header spellings (lower case, spaces/underscores removed)
HEADERS = {
    "date": ["date", "tradedate", "txndate", "transactiondate", "orderexecutiontime", "executiondate"],
    "type": ["type", "txntype", "tradetype", "transactiontype", "action", "side", "buysell"],
    "symbol": ["symbol", "tradingsymbol", "scrip", "ticker", "scripcode", "instrument"],
    "quantity": ["quantity", "qty", "units"],
    "price": ["price", "rate", "nav", "tradeprice", "avgprice", "averageprice"],
    "amount": ["amount", "value", "netamount", "tradevalue"],
    "fees": ["fees", "charges", "brokerage", "totalcharges"],
    "reference": ["reference", "ref", "tradeid", "externalref", "transactionid", "orderid"],
    "note": ["note", "notes", "remarks", "description"],
}

TYPES = {
    "buy": "buy", "b": "buy", "purchase": "buy", "bought": "buy", "sip": "buy",
    "sell": "sell", "s": "sell", "sale": "sell", "sold": "sell", "redemption": "sell", "redeem": "sell",
    "dividend": "dividend", "div": "dividend", "dividendpayout": "dividend",
    "split": "split", "bonus": "bonus",
    "deposit": "deposit", "credit": "deposit", "addfunds": "deposit", "fundsadded": "deposit",
    "withdrawal": "withdrawal", "withdraw": "withdrawal", "debit": "withdrawal", "payout": "withdrawal",
    "fee": "fee", "fees": "fee", "charges": "fee", "charge": "fee",
    "interest": "interest",
    "openingbalance": "opening_balance", "opening": "opening_balance",
}

DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y",
                "%Y/%m/%d", "%d.%m.%Y", "%b %d, %Y")


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def _date(text: str) -> date:
    text = text.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}[T ]", text):
        text = text[:10]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"'{text}' isn't a date I can read; use YYYY-MM-DD.")


def _number(text: str, field: str) -> Optional[float]:
    cleaned = re.sub(r"[₹,\s]|Rs\.?|INR", "", text or "", flags=re.IGNORECASE)
    if cleaned in ("", "-"):
        return None
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    try:
        return float(cleaned)
    except ValueError:
        raise ValueError(f"The {field} '{text}' isn't a number.")


def parse(text: str) -> Dict:
    """Parse CSV text into rows ready for the ledger, plus per-line errors.

    Returns {"rows": [...], "errors": [{"line", "message"}], "columns": {...}}.
    """
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    try:
        header = next(reader)
    except StopIteration:
        return {"rows": [], "errors": [{"line": 1, "message": "The file is empty."}], "columns": {}}

    columns: Dict[str, int] = {}
    for index, name in enumerate(header):
        k = _key(name)
        for field, spellings in HEADERS.items():
            if field not in columns and k in spellings:
                columns[field] = index
    missing = [f for f in ("date", "type") if f not in columns]
    if missing:
        return {
            "rows": [],
            "errors": [{"line": 1, "message": f"No {' or '.join(missing)} column. The first line must name the columns, "
                                              "for example: date,type,symbol,quantity,price,amount,fees,reference,note"}],
            "columns": columns,
        }

    rows: List[Dict] = []
    errors: List[Dict] = []
    seen: Dict[str, int] = {}
    for line, record in enumerate(reader, start=2):
        if not any(cell.strip() for cell in record):
            continue
        if len(rows) + len(errors) >= MAX_ROWS:
            errors.append({"line": line, "message": f"Only the first {MAX_ROWS} rows are read; split the file."})
            break

        def cell(field: str) -> str:
            i = columns.get(field)
            return record[i].strip() if i is not None and i < len(record) else ""

        try:
            txn_type = TYPES.get(_key(cell("type")))
            if txn_type is None:
                raise ValueError(f"'{cell('type')}' isn't a transaction type. Use one of: {', '.join(TXN_TYPES)}.")
            quantity = _number(cell("quantity"), "quantity")
            txn = Txn(
                txn_type=txn_type,
                trade_date=_date(cell("date")),
                symbol=cell("symbol").upper().removesuffix(".NS") or None,
                quantity=abs(quantity) if quantity is not None and txn_type in {"buy", "sell", "opening_balance"} else (quantity or 0.0),
                price=_number(cell("price"), "price"),
                amount=abs(a) if (a := _number(cell("amount"), "amount")) is not None else None,
                fees=abs(_number(cell("fees"), "fees") or 0.0),
            )
            if txn.txn_type in {"deposit", "withdrawal", "fee", "interest"}:
                txn.symbol = txn.symbol if txn.txn_type == "fee" else None
            if txn.trade_date > date.today():
                raise ValueError("The date is in the future.")
            validate(txn)
        except ValueError as e:
            errors.append({"line": line, "message": str(e)})
            continue

        reference = cell("reference")
        if not reference:
            basis = "|".join(str(x) for x in (txn.txn_type, txn.trade_date, txn.symbol, txn.quantity, txn.price, txn.amount, txn.fees))
            occurrence = seen.get(basis, 0)
            seen[basis] = occurrence + 1
            reference = "row:" + hashlib.sha1(f"{basis}|{occurrence}".encode()).hexdigest()[:24]
        rows.append({"line": line, "txn": txn, "external_ref": reference[:100], "note": cell("note") or None})

    # Same-day rows in ledger order, so a buy is recorded before a sale that needs it
    rows.sort(key=lambda r: (r["txn"].trade_date, DAY_ORDER.get(r["txn"].txn_type, 9)))
    return {"rows": rows, "errors": errors, "columns": {f: header[i] for f, i in columns.items()}}
