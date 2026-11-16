"""Build a unit's day-ahead offer: the convexified marginal-cost step curve.

The offer is a price-taker's offer: each step is offered at its marginal cost and is
cleared against the published DA LBMP by the commitment solver. The ISO's optimization is
not simulated.
"""

from __future__ import annotations

from datetime import date

from engine.contracts import Fuel, Offer, OfferBlock
from engine.plant import cost
from engine.plant.params import UnitParams


def build_offer(
    unit: UnitParams,
    local_date: date,
    fuel: Fuel,
    fuel_price_usd_per_mmbtu: float,
    fuel_price_ref: str,
    available_mw: float,
    price_decimals: int,
) -> Offer:
    """Offer for one unit and local day.

    One-part steps cover 0 MW to `available_mw`; the three-part fields give start cost by
    thermal state, no-load cost per hour and the steps above Pmin. Step price ($/MWh) =
    pooled incremental heat rate x fuel price + VOM, rounded to `price_decimals` (the
    market's offer tick). CO2 cost is not included until an RGGI price table is loaded
    (Q-024). A unit with less than Pmin available offers nothing.
    """
    can_run = available_mw >= unit.pmin_mw.value
    blocks = cost.convexify(cost.true_blocks(unit, cap_mw=available_mw)) if can_run else []
    above = cost.blocks_above_pmin(unit, available_mw) if can_run else []

    def step(block: cost.HeatRateBlock) -> OfferBlock:
        return OfferBlock(
            mw_from=block.mw_from,
            mw_to=block.mw_to,
            incremental_heat_rate_mmbtu_per_mwh=block.incremental_heat_rate_mmbtu_per_mwh,
            price_usd_per_mwh=round(
                cost.marginal_cost_usd_per_mwh(
                    block.incremental_heat_rate_mmbtu_per_mwh, fuel_price_usd_per_mmbtu, unit.vom_usd_per_mwh.value
                ),
                price_decimals,
            ),
        )

    return Offer(
        min_gen_mw=unit.pmin_mw.value if can_run else 0.0,
        blocks_above_min_gen=[step(block) for block in above],
        no_load_cost_usd_per_h=cost.no_load_fuel_mmbtu_per_h(unit) * fuel_price_usd_per_mmbtu,
        start_cost_usd_by_thermal_state={
            state: cost.start_cost_usd(unit, state, fuel_price_usd_per_mmbtu) for state in ("hot", "warm", "cold")
        },
        unit_id=unit.id,
        local_date=local_date,
        fuel=fuel,
        fuel_price_usd_per_mmbtu=fuel_price_usd_per_mmbtu,
        fuel_price_ref=fuel_price_ref,
        available_mw=available_mw,
        blocks=[step(block) for block in blocks],
    )


def cleared_mw(offer: Offer, lbmp_usd_per_mwh: float) -> tuple[float, int]:
    """MW of the offer that clears at a price, and the number of steps cleared.

    A step clears when the price is strictly above its offer price (Q-015). Steps are
    monotone, so the cleared steps are a prefix of the curve.
    """
    mw, count = 0.0, 0
    for block in offer.blocks:
        if lbmp_usd_per_mwh > block.price_usd_per_mwh:
            mw, count = block.mw_to, count + 1
        else:
            break
    return mw, count


def committed_dispatch_mw(offer: Offer, lbmp_usd_per_mwh: float) -> float:
    """Output of a unit that is on line: minimum generation plus every step above it priced
    strictly below the LBMP. 0 when the unit cannot run."""
    mw = offer.min_gen_mw
    for block in offer.blocks_above_min_gen:
        if lbmp_usd_per_mwh > block.price_usd_per_mwh:
            mw = block.mw_to
        else:
            break
    return mw
