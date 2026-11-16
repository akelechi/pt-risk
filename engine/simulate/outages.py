"""Seeded forced-outage draws (milestone 3).

One Bernoulli draw per unit and local day: with probability `p` the unit is unavailable
for the whole day. Each draw is seeded by (scenario seed, the unit's position in the plant
config, the calendar day), so a day's outcome does not depend on the scenario window or on
the order in which days are visited.
"""

from __future__ import annotations

from datetime import date

import numpy as np


def forced_outage(seed: int, unit_position: int, local_date: date, probability: float) -> bool:
    """True when the unit is on forced outage for the whole of `local_date`."""
    if not 0.0 <= probability <= 1.0:
        raise ValueError(f"outage probability {probability} is not in [0, 1]")
    generator = np.random.default_rng([seed, unit_position, local_date.toordinal()])
    return bool(generator.random() < probability)
