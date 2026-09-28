"""
Valuation zones for the 0-100 temperature (plan section 5.1).

Bands are right-inclusive, like pandas.cut in the research backtests: a score
of exactly 20 is "much cheaper". The displayed label uses hysteresis so it
doesn't flicker when the score hovers near a boundary.
"""

import math
from dataclasses import dataclass
from typing import Iterable, List, Optional

HYSTERESIS = 3.0


@dataclass(frozen=True)
class Zone:
    id: str
    label: str
    lo: float
    hi: float


ZONES = [
    Zone("much_cheaper", "Much cheaper than usual", 0, 20),
    Zone("cheaper", "Cheaper than usual", 20, 40),
    Zone("typical", "Typical", 40, 60),
    Zone("pricier", "Pricier than usual", 60, 80),
    Zone("much_pricier", "Much pricier than usual", 80, 100),
]

ZONES_BY_ID = {zone.id: zone for zone in ZONES}


def raw_zone(score: float) -> Zone:
    """The band a score falls in, with no hysteresis."""
    for zone in ZONES:
        if score <= zone.hi:
            return zone
    return ZONES[-1]


def zones_with_hysteresis(scores: Iterable[Optional[float]], hysteresis: float = HYSTERESIS) -> List[Optional[Zone]]:
    """The displayed zone for each score in date order.

    The label changes only once the score is more than `hysteresis` points
    outside the current band. Missing scores keep the previous label.
    """
    current: Optional[Zone] = None
    labels: List[Optional[Zone]] = []
    for score in scores:
        if score is None or (isinstance(score, float) and math.isnan(score)):
            labels.append(current)
            continue
        if current is None or score <= current.lo - hysteresis or score > current.hi + hysteresis:
            current = raw_zone(score)
        labels.append(current)
    return labels
