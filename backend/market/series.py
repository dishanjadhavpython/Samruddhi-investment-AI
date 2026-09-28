"""
Series ids, sources and reference data for the market pipeline.

Everything here is index-level. Nothing in this package reads user data or
names a security (plans/realtime-market-intelligence.md, section 2).
"""

from dataclasses import dataclass
from datetime import date

# market_series.series_id values
NIFTY50 = "NIFTY50"  # Nifty 50 price index, daily close
INDIAVIX = "INDIAVIX"  # India VIX, daily close
TRI = "NIFTY50_TRI"  # Nifty 50 Total Return Index
PE = "NIFTY50_PE"  # trailing P/E as published
PB = "NIFTY50_PB"  # P/B as published
DY = "NIFTY50_DY"  # dividend yield (%) as published

VALUATION_SERIES = (PE, PB, DY)

# Daily closes come from Yahoo in the private demo deployment. A public launch
# needs an NSE-authorised vendor (plan section 6).
YAHOO_TICKERS = {NIFTY50: "^NSEI", INDIAVIX: "^INDIAVIX"}
SOURCE_YAHOO = "Yahoo Finance (demo data)"

# Valuation and TRI history: downloaded by hand from niftyindices.com, whose
# terms forbid automated collection. Never scrape it.
SOURCE_NIFTY_INDICES = "NSE Indices (manual download)"

# Bump when indicators, zones or windows change, so every number shown can be
# traced to the method that produced it (plan section 5.5).
METHOD_VERSION = "v1-expanding"


@dataclass(frozen=True)
class Break:
    """A change of basis in a published series.

    Values dated before break_date are multiplied by factor to put them on the
    current basis (chain-linking).
    """

    series_id: str
    break_date: date
    factor: float
    note: str


# Found in the research backtests (plans/backtest-reference/breaks.py). The
# factor is the published value on the break date over the value the day before.
KNOWN_BREAKS = [
    Break(
        PE,
        date(2021, 3, 31),
        round(33.20 / 40.43, 6),
        "NSE switched Nifty 50 P/E from standalone to consolidated earnings. "
        "P/E fell 17.9% that day while the index moved about -1%.",
    ),
    Break(
        PB,
        date(2023, 9, 29),
        round(3.46 / 4.31, 6),
        "P/B fell 19.7% while the index rose 0.6%. The cause is unconfirmed.",
    ),
]

# NSE equity-segment trading holidays (weekdays only). 2026 is from NSE's
# holiday circular; 15 Jan 2026 is missing from it but the exchange was closed
# (no index close that day). Add each new year when NSE publishes its list.
NSE_HOLIDAYS = {
    date(2026, 1, 15): "Market closed (special holiday)",
    date(2026, 1, 26): "Republic Day",
    date(2026, 3, 3): "Holi",
    date(2026, 3, 26): "Shri Ram Navami",
    date(2026, 3, 31): "Shri Mahavir Jayanti",
    date(2026, 4, 3): "Good Friday",
    date(2026, 4, 14): "Dr. Baba Saheb Ambedkar Jayanti",
    date(2026, 5, 1): "Maharashtra Day",
    date(2026, 5, 28): "Bakri Id",
    date(2026, 6, 26): "Muharram",
    date(2026, 9, 14): "Ganesh Chaturthi",
    date(2026, 10, 2): "Mahatma Gandhi Jayanti",
    date(2026, 10, 20): "Dussehra",
    date(2026, 11, 10): "Diwali Balipratipada",
    date(2026, 11, 24): "Prakash Gurpurb Sri Guru Nanak Dev",
    date(2026, 12, 25): "Christmas",
}
