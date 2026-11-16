"""Unit cost model: heat-rate blocks, the convexified curve, fuel burn, marginal cost.

Heat-rate curve reading (Q-016): each configured point is the incremental heat rate
(MMBtu/MWh) of the block ENDING at that output; the first block runs from 0 MW to the
first point (Pmin). The physical ("true") blocks drive fuel burn. The offer curve uses the
convexified blocks: adjacent blocks whose incremental heat rate would decrease are pooled
at their MW-weighted average, so the curve is monotone non-decreasing. At every pooled
block boundary the fuel implied by the pooled curve equals the true fuel exactly.

Milestone 2 adds no-load fuel (burned every hour the unit is on, on top of the heat-rate
curve) and start fuel and start cost by thermal state. A committed unit cannot run below
Pmin, so its dispatch above Pmin follows the blocks above Pmin, convexified on their own.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.contracts import ThermalState
from engine.plant.params import UnitParams

MW_DECIMALS = 6  # MW are rounded here so derived values (e.g. Pmax x availability) are stable


@dataclass(frozen=True)
class HeatRateBlock:
    """Output range [mw_from, mw_to] with a constant incremental heat rate (MMBtu/MWh)."""

    mw_from: float
    mw_to: float
    incremental_heat_rate_mmbtu_per_mwh: float

    @property
    def width_mw(self) -> float:
        return self.mw_to - self.mw_from


def deterministic_available_mw(unit: UnitParams) -> float:
    """Available capacity under the deterministic availability factor: Pmax x (1 - EFOR), MW.

    Used in milestones 1-2 (brief §4, Availability); replaced by seeded outage draws in
    milestone 3.
    """
    return round(unit.pmax_mw.value * (1.0 - unit.efor.value), MW_DECIMALS)


def true_blocks(unit: UnitParams, cap_mw: float | None = None) -> list[HeatRateBlock]:
    """Physical heat-rate blocks from 0 MW up to `cap_mw` (default Pmax), in output order."""
    cap = unit.pmax_mw.value if cap_mw is None else min(cap_mw, unit.pmax_mw.value)
    blocks: list[HeatRateBlock] = []
    previous_mw = 0.0
    for point in unit.heat_rate_curve.value:
        upper = min(point.output_mw, cap)
        if upper > previous_mw:
            blocks.append(HeatRateBlock(previous_mw, upper, point.incremental_heat_rate_mmbtu_per_mwh))
            previous_mw = upper
    return blocks


def convexify(blocks: list[HeatRateBlock]) -> list[HeatRateBlock]:
    """Pool adjacent blocks until incremental heat rates are non-decreasing.

    Pool-adjacent-violators with MW weights: a block cheaper than the one before it cannot
    be reached without first running the earlier block, so the two are offered together at
    their MW-weighted average heat rate.
    """
    pooled: list[HeatRateBlock] = []
    for block in blocks:
        pooled.append(block)
        while (
            len(pooled) > 1
            and pooled[-1].incremental_heat_rate_mmbtu_per_mwh < pooled[-2].incremental_heat_rate_mmbtu_per_mwh
        ):
            last, before = pooled.pop(), pooled.pop()
            fuel_mmbtu_per_h = (
                before.width_mw * before.incremental_heat_rate_mmbtu_per_mwh
                + last.width_mw * last.incremental_heat_rate_mmbtu_per_mwh
            )
            pooled.append(
                HeatRateBlock(before.mw_from, last.mw_to, fuel_mmbtu_per_h / (last.mw_to - before.mw_from))
            )
    return pooled


def fuel_burn_mmbtu_per_h(unit: UnitParams, output_mw: float) -> float:
    """Fuel burned at a steady output, MMBtu per hour: the true incremental heat rate
    integrated from 0 MW to `output_mw`. Excludes no-load and start fuel (milestone 2)."""
    if output_mw < 0 or output_mw > unit.pmax_mw.value + 1e-9:
        raise ValueError(f"{unit.id}: output {output_mw} MW is outside [0, {unit.pmax_mw.value}]")
    burn = 0.0
    for block in true_blocks(unit):
        if output_mw <= block.mw_from:
            break
        burn += (min(output_mw, block.mw_to) - block.mw_from) * block.incremental_heat_rate_mmbtu_per_mwh
    return burn


def marginal_cost_usd_per_mwh(
    incremental_heat_rate_mmbtu_per_mwh: float,
    fuel_price_usd_per_mmbtu: float,
    vom_usd_per_mwh: float,
    co2_t_per_mmbtu: float = 0.0,
    co2_price_usd_per_ton: float = 0.0,
) -> float:
    """c = IHR x P_fuel + VOM + ER x IHR x P_CO2, in $/MWh (brief §4)."""
    return (
        incremental_heat_rate_mmbtu_per_mwh * fuel_price_usd_per_mmbtu
        + vom_usd_per_mwh
        + co2_t_per_mmbtu * incremental_heat_rate_mmbtu_per_mwh * co2_price_usd_per_ton
    )


def thermal_state(hours_offline_h: int, unit: UnitParams) -> ThermalState:
    """Thermal state from hours offline, per the unit's start thresholds. 0 h (running) is hot."""
    if hours_offline_h <= unit.start.hot.value.hours_offline_max_h:
        return "hot"
    if hours_offline_h <= unit.start.warm.value.hours_offline_max_h:
        return "warm"
    return "cold"


def blocks_above_pmin(unit: UnitParams, cap_mw: float) -> list[HeatRateBlock]:
    """Convexified heat-rate blocks from Pmin up to `cap_mw`: the dispatch curve of a unit
    that is already committed. Empty when `cap_mw` does not exceed Pmin."""
    pmin = unit.pmin_mw.value
    clipped = [
        HeatRateBlock(max(block.mw_from, pmin), block.mw_to, block.incremental_heat_rate_mmbtu_per_mwh)
        for block in true_blocks(unit, cap_mw=cap_mw)
        if block.mw_to > pmin
    ]
    return convexify(clipped)


def no_load_fuel_mmbtu_per_h(unit: UnitParams) -> float:
    """Fuel burned per hour on line regardless of output, MMBtu/h."""
    return unit.no_load_mmbtu_per_hr.value


def start_spec(unit: UnitParams, state: ThermalState):
    """The StartSpec (start fuel MMBtu, other cost USD) for a start from `state`."""
    return getattr(unit.start, state).value


def start_cost_usd(unit: UnitParams, state: ThermalState, fuel_price_usd_per_mmbtu: float) -> float:
    """Cost of one start: start fuel x fuel price + other start cost, USD (brief §4)."""
    spec = start_spec(unit, state)
    return spec.start_fuel_mmbtu * fuel_price_usd_per_mmbtu + spec.start_other_cost_usd
