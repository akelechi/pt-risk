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

    Steps cover 0 MW to `available_mw`. Step price ($/MWh) = pooled incremental heat rate
    x fuel price + VOM, rounded to `price_decimals` (the market's offer tick). CO2 cost is not included until an RGGI price table is loaded
    (Q-024). Start and no-load are not in the offer until milestone 2.
    """
    blocks = cost.convexify(cost.true_blocks(unit, cap_mw=available_mw))
    return Offer(
        unit_id=unit.id,
        local_date=local_date,
        fuel=fuel,
        fuel_price_usd_per_mmbtu=fuel_price_usd_per_mmbtu,
        fuel_price_ref=fuel_price_ref,
        available_mw=available_mw,
        blocks=[
            OfferBlock(
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
            for block in blocks
        ],
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
