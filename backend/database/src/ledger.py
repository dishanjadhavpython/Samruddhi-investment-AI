"""
The transaction ledger and the positions derived from it.

Every write goes through here, so the rules live in one place:
- A holding's quantity, average cost and cost basis are recomputed from its
  ledger rows after every change (positions is a cache of the ledger).
- A change that would make the ledger impossible (selling more than was held)
  is refused before anything is written.
- Cash moves only when the caller asks, and never below zero. Each row keeps
  the cash it moved, so edits and deletes undo exactly that.
- A holding entered the old way (a quantity, no history) gets an
  opening_balance row valued at that day's close, which the user can edit.
"""

from datetime import date
from typing import Dict, List, Optional

from .returns import EPSILON, LedgerError, Txn, cash_effect, replay, validate


class LedgerConflict(ValueError):
    """The change is valid on its own but clashes with what is already recorded."""


def to_txn(row: Dict) -> Txn:
    return Txn(
        txn_type=row["txn_type"],
        trade_date=date.fromisoformat(str(row["trade_date"])[:10]),
        symbol=row.get("symbol"),
        quantity=float(row.get("quantity") or 0.0),
        price=float(row["price"]) if row.get("price") is not None else None,
        amount=float(row["amount"]) if row.get("amount") is not None else None,
        fees=float(row.get("fees") or 0.0),
        id=row.get("id"),
        account_id=row.get("account_id"),
        source=row.get("source") or "manual",
    )


def _check(rows: List[Txn]) -> None:
    try:
        replay(rows)
    except LedgerError as e:
        raise LedgerConflict(str(e)) from e


def sync_position(db, account_id: str, symbol: str) -> Optional[Dict]:
    """Rewrite one holding from its ledger rows; deletes it when nothing is left."""
    rows = [to_txn(r) for r in db.transactions.for_holding(account_id, symbol)]
    holding = replay(rows).get(symbol)
    if holding is None or holding.quantity <= EPSILON:
        db.positions.delete_holding(account_id, symbol)
        return None
    db.positions.set_from_ledger(account_id, symbol, holding.quantity, holding.avg_cost,
                                 holding.known_cost_basis, holding.first_buy_date)
    return {"symbol": symbol, "quantity": holding.quantity, "avg_cost": holding.avg_cost,
            "cost_basis": holding.known_cost_basis}


def _move_cash(db, account_id: str, delta: float, what: str) -> None:
    if abs(delta) < 0.005:
        return
    if db.accounts.adjust_cash(account_id, delta) is None:
        raise LedgerConflict(
            f"{what} needs ₹{abs(delta):,.2f} of the account's cash, which is more than it holds. "
            "Record a deposit first, or don't take it from the account's cash."
        )


def add(db, account_id: str, txn: Txn, *, update_cash: bool = False, source: str = "manual",
        external_ref: Optional[str] = None, note: Optional[str] = None) -> Optional[str]:
    """Record one transaction. Returns its id, or None if external_ref was already imported."""
    validate(txn)
    if txn.symbol:
        _check([to_txn(r) for r in db.transactions.for_holding(account_id, txn.symbol)] + [txn])
    effect = cash_effect(txn) if update_cash else 0.0
    _move_cash(db, account_id, effect, f"This {txn.txn_type.replace('_', ' ')}")
    try:
        txn_id = db.transactions.insert_row(account_id, {
            "txn_type": txn.txn_type, "trade_date": txn.trade_date, "symbol": txn.symbol,
            "quantity": txn.quantity if txn.symbol else None, "price": txn.price, "amount": txn.amount,
            "fees": txn.fees, "cash_effect": effect, "source": source, "external_ref": external_ref, "note": note,
        })
    except Exception:
        _move_cash(db, account_id, -effect, "Undoing the cash change")
        raise
    if txn_id is None:
        # Already imported: put the cash back
        _move_cash(db, account_id, -effect, "Undoing the cash change")
        return None
    if txn.symbol:
        sync_position(db, account_id, txn.symbol)
    return txn_id


def import_rows(db, account_id: str, rows: List[Dict], *, update_cash: bool = False, source: str = "csv") -> Dict:
    """Record many parsed CSV rows ({line, txn, external_ref, note}) in a few database calls.

    Rows already imported (same reference) are skipped. Rows that would make
    a holding's ledger impossible are refused one by one with their line
    number; the rest go in. Cash moves once, by the total, and only if the
    account can cover it, otherwise nothing is recorded.
    """
    known = db.transactions.refs(account_id, source)
    fresh, duplicates = [], 0
    for row in rows:
        if row["external_ref"] in known:
            duplicates += 1
        else:
            known.add(row["external_ref"])
            fresh.append(row)

    accepted, errors = [], []
    by_symbol: Dict[Optional[str], List[Dict]] = {}
    for row in fresh:
        by_symbol.setdefault(row["txn"].symbol, []).append(row)
    for symbol, group in by_symbol.items():
        if symbol is None:
            accepted += group
            continue
        existing = [to_txn(r) for r in db.transactions.for_holding(account_id, symbol)]
        try:
            replay(existing + [r["txn"] for r in group])
            accepted += group
            continue
        except LedgerError:
            pass
        # Keep every row that fits; refuse the ones that don't, in date order
        kept: List[Txn] = []
        for row in group:
            try:
                replay(existing + kept + [row["txn"]])
                kept.append(row["txn"])
                accepted.append(row)
            except LedgerError as e:
                errors.append({"line": row["line"], "message": str(e)})

    effects = [cash_effect(r["txn"]) if update_cash else 0.0 for r in accepted]
    if accepted:
        _move_cash(db, account_id, sum(effects), "These transactions together")
        db.transactions.insert_many(account_id, [
            {
                "txn_type": r["txn"].txn_type, "trade_date": r["txn"].trade_date, "symbol": r["txn"].symbol,
                "quantity": r["txn"].quantity if r["txn"].symbol else None, "price": r["txn"].price,
                "amount": r["txn"].amount, "fees": r["txn"].fees, "cash_effect": effect, "source": source,
                "external_ref": r["external_ref"], "note": r.get("note"),
            }
            for r, effect in zip(accepted, effects)
        ])
        for symbol in sorted({r["txn"].symbol for r in accepted if r["txn"].symbol}):
            sync_position(db, account_id, symbol)
    return {"imported": len(accepted), "duplicates": duplicates, "errors": sorted(errors, key=lambda e: e["line"])}


EDITABLE = ("trade_date", "quantity", "price", "amount", "fees", "note")


def edit(db, row: Dict, changes: Dict) -> None:
    """Change the date, quantity, price, amount, fees or note of a recorded row.

    Rows that moved cash keep doing so, by the new amount.
    """
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise ValueError(f"These fields can't be changed: {', '.join(sorted(unknown))}.")
    merged = {**row, **{k: v for k, v in changes.items()}}
    new = to_txn(merged)
    validate(new)
    account_id, symbol = row["account_id"], row.get("symbol")
    if symbol:
        others = [to_txn(r) for r in db.transactions.for_holding(account_id, symbol) if r["id"] != row["id"]]
        _check(others + [new])

    old_effect = float(row.get("cash_effect") or 0.0)
    new_effect = cash_effect(new) if abs(old_effect) >= 0.005 else 0.0
    _move_cash(db, account_id, new_effect - old_effect, "This change")

    fields: Dict = {"cash_effect": round(new_effect, 2)}
    for key in EDITABLE:
        if key in changes:
            fields[key] = changes[key]
    # A system-written opening balance the user has corrected is theirs now
    if row.get("source") == "system":
        fields["source"] = "manual"
    db.transactions.update_row(row["id"], _db_values(fields))
    if symbol:
        sync_position(db, account_id, symbol)


def remove(db, row: Dict) -> None:
    account_id, symbol = row["account_id"], row.get("symbol")
    if symbol:
        others = [to_txn(r) for r in db.transactions.for_holding(account_id, symbol) if r["id"] != row["id"]]
        _check(others)
    _move_cash(db, account_id, -float(row.get("cash_effect") or 0.0), "Deleting this row")
    db.transactions.delete(row["id"])
    if symbol:
        sync_position(db, account_id, symbol)


def _db_values(fields: Dict) -> Dict:
    """Numbers as Decimal-friendly strings so the Data API client casts them to numeric."""
    from decimal import Decimal

    out = {}
    for key, value in fields.items():
        if isinstance(value, float):
            out[key] = Decimal(repr(value))
        elif isinstance(value, int) and key != "note":
            out[key] = Decimal(value)
        else:
            out[key] = value
    return out


def opening_price(db, symbol: str, day: date) -> Optional[float]:
    """That day's close (or the last one before it), else the instrument's current price."""
    close = db.prices.close_on_or_before(symbol, day)
    if close:
        return close
    instrument = db.instruments.find_by_symbol(symbol)
    price = instrument.get("current_price") if instrument else None
    return float(price) if price not in (None, "") and float(price) > 0 else None


OPENING_NOTE = ("Opening balance from the holding you entered, valued at that day's close. "
                "Change the date and price if you know when and at what price you bought.")


def set_quantity(db, account_id: str, symbol: str, quantity: float, day: Optional[date] = None) -> None:
    """Set a holding to an absolute quantity the old way (Accounts page, test data).

    Allowed while the holding has only an opening balance, which is created or
    resized. Once buys or sells are recorded, quantity changes only through them.
    """
    if not quantity > 0:
        raise ValueError("Quantity must be above zero.")
    rows = db.transactions.for_holding(account_id, symbol)
    history = [r for r in rows if r["txn_type"] != "opening_balance"]
    if history:
        raise LedgerConflict(
            f"{symbol} has recorded transactions in this account, so its quantity comes from them. "
            "Record a buy or sell to change it."
        )
    opening = [r for r in rows if r["txn_type"] == "opening_balance"]
    if opening:
        row = opening[0]
        changes: Dict = {"quantity": float(quantity)}
        if row.get("price") is not None:
            changes["amount"] = None
        db.transactions.update_row(row["id"], _db_values(changes))
        for extra in opening[1:]:
            db.transactions.delete(extra["id"])
    else:
        day = day or date.today()
        db.transactions.insert_row(account_id, {
            "txn_type": "opening_balance", "trade_date": day, "symbol": symbol, "quantity": float(quantity),
            "price": opening_price(db, symbol, day), "source": "system", "note": OPENING_NOTE,
        })
    sync_position(db, account_id, symbol)


def remove_holding(db, account_id: str, symbol: str) -> None:
    """Stop tracking a holding: its ledger rows go too (cash they moved stays moved)."""
    db.transactions.delete_holding(account_id, symbol)
    db.positions.delete_holding(account_id, symbol)
