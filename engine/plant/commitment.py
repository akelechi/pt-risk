"""Commitment solvers behind one interface: solve(prices, state0, unit, offer) -> decisions.

`price_taker` is the unconstrained baseline and stays forever as the comparison: every
hour stands alone, a step runs when the DA LBMP is above its offer price, and there is no
start cost, minimum run time or minimum down time. `dp` arrives in milestone 2.
"""

from __future__ import annotations

from typing import Callable

from engine.contracts import DayPrices, Decision, Offer, PlantState
from engine.market.offer import cleared_mw
from engine.plant.params import UnitParams

Solver = Callable[[DayPrices, PlantState, UnitParams, Offer], list[Decision]]


def price_taker(prices: DayPrices, state0: PlantState, unit: UnitParams, offer: Offer) -> list[Decision]:
    """Hour-by-hour price-taker: dispatch every offer step priced below the DA LBMP.

    `state0` is unused: the baseline has no memory. Returns one Decision per hour of the day.
    """
    del state0
    if prices.unit_id != unit.id or offer.unit_id != unit.id or offer.local_date != prices.local_date:
        raise ValueError("prices, offer and unit do not describe the same unit and day")
    decisions: list[Decision] = []
    lowest = offer.blocks[0].price_usd_per_mwh if offer.blocks else None
    for hour in prices.hours:
        mw, steps = cleared_mw(offer, hour.da_lbmp_usd_per_mwh)
        if steps:
            marginal = offer.blocks[steps - 1].price_usd_per_mwh
            reason = (
                f"DA LBMP {hour.da_lbmp_usd_per_mwh:.2f} > offer {marginal:.2f} $/MWh "
                f"on {steps} of {len(offer.blocks)} steps: {mw:.1f} MW"
            )
        elif lowest is None:
            reason = "nothing offered: 0 MW available"
        else:
            reason = f"DA LBMP {hour.da_lbmp_usd_per_mwh:.2f} <= lowest offer {lowest:.2f} $/MWh: off"
        decisions.append(
            Decision(
                ts_utc=hour.ts_utc,
                ts_local=hour.ts_local,
                unit_id=unit.id,
                commit=steps > 0,
                target_mw=mw,
                fuel=offer.fuel,
                reason=reason,
            )
        )
    return decisions


SOLVERS: dict[str, Solver] = {"price_taker": price_taker}


def solve(prices: DayPrices, state0: PlantState, unit: UnitParams, offer: Offer, solver: str = "price_taker") -> list[Decision]:
    """Run the named commitment solver for one unit and day."""
    if solver not in SOLVERS:
        raise ValueError(f"unknown commitment solver {solver!r}; have {sorted(SOLVERS)}")
    return SOLVERS[solver](prices, state0, unit, offer)
