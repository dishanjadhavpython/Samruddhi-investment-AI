"""
NSE cash-market session state, for the Market page header and polling.
"""

from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
OPEN = time(9, 15)
CLOSE = time(15, 30)


def session_state(now: datetime, holidays: Iterable[date]) -> Dict:
    """Whether NSE is open now, why not if it isn't, and when it next opens."""
    closed_days = set(holidays)
    local = now.astimezone(IST)
    today = local.date()

    def trading_day(day: date) -> bool:
        return day.weekday() < 5 and day not in closed_days

    if not trading_day(today):
        reason = "weekend" if today.weekday() >= 5 else "holiday"
    elif local.time() < OPEN:
        reason = "before_open"
    elif local.time() >= CLOSE:
        reason = "after_close"
    else:
        reason = None

    next_day = today if reason == "before_open" else today + timedelta(days=1)
    while not trading_day(next_day):
        next_day += timedelta(days=1)

    return {
        "state": "open" if reason is None else "closed",
        "reason": reason,
        "closes_at": datetime.combine(today, CLOSE, IST).isoformat() if reason is None else None,
        "next_open": datetime.combine(next_day, OPEN, IST).isoformat() if reason is not None else None,
        "timezone": "Asia/Kolkata",
    }
