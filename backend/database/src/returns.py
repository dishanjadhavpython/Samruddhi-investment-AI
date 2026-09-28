"""
Portfolio returns from the transaction ledger (plan section 4.3, Phase 3).

- replay(): quantity, cost basis and realised gains per holding, using the
  average-cost method brokers show as "average price"
- xirr(): annualised return on dated cash flows, in Excel's XIRR convention
  (actual days / 365), so results match a spreadsheet
- same_flows_benchmark(): what the same rupees, on the same dates, would have
  done in an index ("public market equivalent")
- value_history(): daily market value and cost basis from the ledger and
  daily closes

Pure Python with no numpy, so the API Lambda can use it. Everything here
describes the user's own holdings; nothing forecasts.
"""

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

TXN_TYPES = (
    "buy", "sell", "dividend", "split", "bonus", "deposit", "withdrawal", "fee", "interest", "opening_balance",
)
# Types that name a security
SECURITY_TYPES = {"buy", "sell", "dividend", "split", "bonus", "opening_balance"}
# Types that move money in or out of the account's cash only
CASH_TYPES = {"deposit", "withdrawal", "fee", "interest"}

# Same-day order: holdings arrive before they can be sold or pay out
DAY_ORDER = {"opening_balance": 0, "buy": 1, "bonus": 2, "split": 2, "sell": 3, "dividend": 4, "fee": 5,
              "interest": 6, "deposit": 7, "withdrawal": 8}

EPSILON = 1e-9


class LedgerError(ValueError):
    """A set of transactions that can't be true, such as selling more than was held."""


@dataclass
class Txn:
    txn_type: str
    trade_date: date
    symbol: Optional[str] = None
    quantity: float = 0.0
    price: Optional[float] = None
    amount: Optional[float] = None
    fees: float = 0.0
    id: Optional[str] = None
    account_id: Optional[str] = None
    source: str = "manual"

    @property
    def gross(self) -> Optional[float]:
        """Trade value before fees: the reported amount, else quantity × price."""
        if self.amount is not None:
            return abs(self.amount)
        if self.price is None:
            return None
        return abs(self.quantity) * self.price


def validate(txn: Txn) -> None:
    """Check one transaction on its own; raises ValueError with a message for the user."""
    t = txn.txn_type
    if t not in TXN_TYPES:
        raise ValueError(f"Unknown transaction type '{t}'.")
    if t in SECURITY_TYPES and not txn.symbol:
        raise ValueError(f"A {t.replace('_', ' ')} needs a symbol.")
    if t in {"buy", "sell", "opening_balance"} and not (txn.quantity > 0):
        raise ValueError(f"A {t.replace('_', ' ')} needs a quantity above zero.")
    if t in {"buy", "sell"} and txn.gross is None:
        raise ValueError(f"A {t} needs a price or an amount.")
    if t in {"split", "bonus"} and txn.quantity == 0:
        raise ValueError(f"A {t} needs the number of units it added (negative for a consolidation).")
    if t in {"dividend"} | CASH_TYPES and not (txn.amount is not None and txn.amount > 0):
        raise ValueError(f"A {t} needs an amount above zero.")
    for name, value in (("price", txn.price), ("fees", txn.fees)):
        if value is not None and value < 0:
            raise ValueError(f"The {name} can't be negative.")


def ordered(txns: Iterable[Txn]) -> List[Txn]:
    return sorted(txns, key=lambda t: (t.trade_date, DAY_ORDER.get(t.txn_type, 9)))


def cash_effect(txn: Txn) -> float:
    """What the transaction does to the account's cash balance."""
    t = txn.txn_type
    if t == "buy":
        return -((txn.gross or 0.0) + txn.fees)
    if t == "sell":
        return (txn.gross or 0.0) - txn.fees
    if t in {"dividend", "interest", "deposit"}:
        return txn.amount or 0.0
    if t in {"withdrawal", "fee"}:
        return -(txn.amount or 0.0)
    return 0.0


# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------


@dataclass
class Holding:
    symbol: str
    quantity: float = 0.0
    cost_basis: float = 0.0
    realised: float = 0.0
    dividends: float = 0.0
    fees: float = 0.0
    first_buy_date: Optional[date] = None
    # True while any units still held came from a lot with no known price
    unknown_cost: bool = False

    @property
    def avg_cost(self) -> Optional[float]:
        if self.unknown_cost or self.quantity <= EPSILON:
            return None
        return self.cost_basis / self.quantity

    @property
    def known_cost_basis(self) -> Optional[float]:
        return None if self.unknown_cost else self.cost_basis


def apply(holding: Holding, txn: Txn) -> None:
    t, q = txn.txn_type, txn.quantity
    if t in {"buy", "opening_balance"}:
        if txn.gross is None:
            holding.unknown_cost = True
        else:
            holding.cost_basis += txn.gross + txn.fees
        holding.fees += txn.fees
        holding.quantity += q
        if holding.first_buy_date is None or txn.trade_date < holding.first_buy_date:
            holding.first_buy_date = txn.trade_date
    elif t == "sell":
        if q > holding.quantity + EPSILON:
            raise LedgerError(
                f"The sale of {q:g} {txn.symbol} on {txn.trade_date.isoformat()} is more than the "
                f"{holding.quantity:g} units held on that date."
            )
        if not holding.unknown_cost and holding.quantity > EPSILON:
            released = holding.cost_basis * q / holding.quantity
            holding.cost_basis -= released
            holding.realised += (txn.gross or 0.0) - txn.fees - released
        holding.fees += txn.fees
        holding.quantity -= q
        if holding.quantity <= EPSILON:
            holding.quantity, holding.cost_basis, holding.unknown_cost = 0.0, 0.0, False
    elif t in {"split", "bonus"}:
        if holding.quantity + q <= EPSILON:
            raise LedgerError(f"The {t} on {txn.trade_date.isoformat()} would leave no {txn.symbol} units.")
        holding.quantity += q
    elif t == "dividend":
        holding.dividends += txn.amount or 0.0
    elif t == "fee":
        holding.fees += txn.amount or 0.0


def replay(txns: Iterable[Txn]) -> Dict[str, Holding]:
    """Holdings after every transaction, by symbol. Raises LedgerError on an impossible ledger."""
    holdings: Dict[str, Holding] = {}
    for txn in ordered(txns):
        if not txn.symbol:
            continue
        holding = holdings.setdefault(txn.symbol, Holding(txn.symbol))
        apply(holding, txn)
    return holdings


# ---------------------------------------------------------------------------
# XIRR
# ---------------------------------------------------------------------------


def _npv(rate: float, flows: Sequence[Tuple[float, float]]) -> float:
    return sum(amount / (1.0 + rate) ** years for years, amount in flows)


def _dnpv(rate: float, flows: Sequence[Tuple[float, float]]) -> float:
    return sum(-years * amount / (1.0 + rate) ** (years + 1.0) for years, amount in flows)


def xirr(cash_flows: Iterable[Tuple[date, float]], guess: float = 0.1) -> Optional[float]:
    """Annualised internal rate of return on dated flows, as Excel's XIRR.

    Money paid in is negative and money received (including today's value)
    is positive. Returns None when there is no rate: flows all one sign, or
    no root between -100% and +1,000,000%.
    """
    raw = [(d, float(a)) for d, a in cash_flows if abs(float(a)) > EPSILON]
    if not raw or not any(a < 0 for _, a in raw) or not any(a > 0 for _, a in raw):
        return None
    start = min(d for d, _ in raw)
    flows = [((d - start).days / 365.0, a) for d, a in raw]

    # Newton's method from the guess, as spreadsheets do
    rate = guess
    for _ in range(100):
        try:
            value, slope = _npv(rate, flows), _dnpv(rate, flows)
        except (OverflowError, ZeroDivisionError):
            break
        if slope == 0:
            break
        step = value / slope
        nxt = rate - step
        if nxt <= -1.0:
            nxt = (rate - 1.0) / 2.0
        if abs(nxt - rate) < 1e-12:
            rate = nxt
            if abs(_npv(rate, flows)) < 1e-6 * max(abs(a) for _, a in flows):
                return rate
            break
        rate = nxt

    # Bisection fallback on a bracket where the NPV changes sign
    lo, hi = -0.999999, 1.0
    try:
        f_lo = _npv(lo, flows)
        f_hi = _npv(hi, flows)
        while f_lo * f_hi > 0 and hi < 1e4:
            hi *= 4.0
            f_hi = _npv(hi, flows)
    except OverflowError:
        return None
    if f_lo * f_hi > 0:
        return None
    for _ in range(300):
        mid = (lo + hi) / 2.0
        f_mid = _npv(mid, flows)
        if abs(f_mid) < 1e-9 or (hi - lo) < 1e-12:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def holding_flows(txns: Iterable[Txn], exclude: Iterable[str] = ()) -> List[Tuple[date, float]]:
    """Money into and out of holdings from the investor's side: buys negative, sales and dividends positive.

    Cash-only rows (deposits, interest, account fees) are left out: this
    measures the holdings, not the cash sitting beside them.
    """
    skip = set(exclude)
    flows = []
    for txn in ordered(txns):
        if not txn.symbol or txn.symbol in skip:
            continue
        t = txn.txn_type
        if t in {"buy", "opening_balance"} and txn.gross is not None:
            flows.append((txn.trade_date, -(txn.gross + txn.fees)))
        elif t == "sell":
            flows.append((txn.trade_date, (txn.gross or 0.0) - txn.fees))
        elif t == "dividend":
            flows.append((txn.trade_date, txn.amount or 0.0))
        elif t == "fee":
            flows.append((txn.trade_date, -(txn.amount or 0.0)))
    return flows


# ---------------------------------------------------------------------------
# Price series helpers
# ---------------------------------------------------------------------------


@dataclass
class Series:
    """A sorted daily series with "last value on or before" lookup."""

    dates: List[date] = field(default_factory=list)
    values: List[float] = field(default_factory=list)

    @classmethod
    def of(cls, points: Iterable[Tuple[date, float]]) -> "Series":
        clean = sorted((d, float(v)) for d, v in points if v is not None and float(v) > 0)
        return cls([d for d, _ in clean], [v for _, v in clean])

    def __bool__(self) -> bool:
        return bool(self.dates)

    def at(self, day: date) -> Optional[float]:
        i = bisect_right(self.dates, day)
        return self.values[i - 1] if i else None

    @property
    def first(self) -> Optional[date]:
        return self.dates[0] if self.dates else None

    @property
    def last(self) -> Optional[date]:
        return self.dates[-1] if self.dates else None


# ---------------------------------------------------------------------------
# Benchmark on the same cash flows
# ---------------------------------------------------------------------------


def same_flows_benchmark(flows: Sequence[Tuple[date, float]], index: Series, end: date) -> Optional[Dict]:
    """Invest and withdraw the same rupees on the same dates in the index.

    Returns the index units' value at `end` and the XIRR of the same flows
    ending in that value, or None when the index doesn't cover a flow date.
    """
    if not flows or not index:
        return None
    units = 0.0
    for day, amount in sorted(flows):
        level = index.at(day)
        if level is None:
            return None
        units -= amount / level
    end_level = index.at(end)
    if end_level is None:
        return None
    value = units * end_level
    return {
        "value": value,
        "xirr": xirr(list(flows) + [(end, value)]) if value > 0 else None,
        "units": units,
        "end_level": end_level,
    }


def benchmark_path(flows: Sequence[Tuple[date, float]], index: Series, days: Sequence[date]) -> List[Optional[float]]:
    """Value of the same-flows index holding on each day (None before the first flow)."""
    ordered_flows = sorted(flows)
    out, units, i = [], 0.0, 0
    for day in days:
        while i < len(ordered_flows) and ordered_flows[i][0] <= day:
            level = index.at(ordered_flows[i][0])
            if level is None:
                return [None] * len(days)
            units -= ordered_flows[i][1] / level
            i += 1
        level = index.at(day)
        out.append(units * level if i and level is not None else None)
    return out


# ---------------------------------------------------------------------------
# Value history
# ---------------------------------------------------------------------------


def value_history(txns: Sequence[Txn], prices: Dict[str, Series], days: Sequence[date]) -> List[Dict]:
    """Market value and cost basis of the holdings at each day's close.

    Symbols without a close on or before a day are left out of that day's
    value and cost alike, so the two stay comparable.
    """
    events = ordered([t for t in txns if t.symbol])
    holdings: Dict[str, Holding] = {}
    out, i = [], 0
    for day in days:
        while i < len(events) and events[i].trade_date <= day:
            apply(holdings.setdefault(events[i].symbol, Holding(events[i].symbol)), events[i])
            i += 1
        value = cost = 0.0
        priced = False
        for symbol, h in holdings.items():
            if h.quantity <= EPSILON or h.unknown_cost:
                continue
            close = prices.get(symbol, Series()).at(day)
            if close is None:
                continue
            value += h.quantity * close
            cost += h.cost_basis
            priced = True
        out.append({"d": day, "value": value if priced else None, "invested": cost if priced else None})
    return out
