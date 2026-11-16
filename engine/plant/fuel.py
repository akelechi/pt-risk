"""Dual fuel (milestone 4): the plant's oil price, the daily fuel choice, and whether oil
can be burned at all.

Oil is No. 6 residual from the station tank. Its price is derived from the public New York
Harbor No. 2 index with an assumed ratio; burning it takes more heat per MWh than gas
(`oil_heat_rate_penalty_fraction`). The fuel is chosen once per local day. Oil must be
available for the whole day: enough in the tank for the worst case and enough permit
hours left; when it is not, gas is used whatever it costs.
"""

from __future__ import annotations

from datetime import date

from engine.contracts import Fuel, PlantState
from engine.plant import cost
from engine.plant.params import FuelParams, UnitParams


def oil_price_usd_per_mmbtu(no2_price_usd_per_bbl: float, fuel: FuelParams) -> float:
    """The plant's oil price, $/MMBtu: No. 2 index $/bbl x assumed residual ratio / heat content."""
    return no2_price_usd_per_bbl * fuel.oil_price_ratio_to_no2_distillate.value / fuel.oil_mmbtu_per_bbl.value


def heat_input_multiplier(burning: Fuel, fuel: FuelParams) -> float:
    """Heat needed on `burning` relative to gas: 1 on gas, 1 + penalty on oil."""
    return 1.0 + fuel.oil_heat_rate_penalty_fraction.value if burning == "oil" else 1.0


def worst_case_day_oil_bbl(unit: UnitParams, fuel: FuelParams, available_mw: float, hours_in_day: int) -> float:
    """Oil a unit could burn in one day, bbl: every hour at full available output, plus a cold start."""
    hourly_mmbtu = cost.no_load_fuel_mmbtu_per_h(unit) + cost.fuel_burn_mmbtu_per_h(unit, min(available_mw, unit.pmax_mw.value))
    total_mmbtu = (hourly_mmbtu * hours_in_day + cost.start_spec(unit, "cold").start_fuel_mmbtu) * heat_input_multiplier("oil", fuel)
    return total_mmbtu / fuel.oil_mmbtu_per_bbl.value


def oil_unavailable_reason(state: PlantState, unit: UnitParams, fuel: FuelParams, local_date: date,
                           hours_in_day: int, available_mw: float) -> str | None:
    """Why oil cannot be the day's fuel, or None when it can.

    Oil needs (1) the worst-case day's burn in the tank at the start of the day, counting a
    barge due by then, and (2) permit hours for every hour of the day.
    """
    inventory_bbl = state.oil_inventory_bbl
    if state.oil_barge_due is not None and state.oil_barge_due <= local_date:
        inventory_bbl += state.oil_barge_bbl
    needed_bbl = worst_case_day_oil_bbl(unit, fuel, available_mw, hours_in_day)
    if inventory_bbl < needed_bbl:
        return f"tank {inventory_bbl:,.0f} bbl is below a worst-case day of {needed_bbl:,.0f} bbl"
    used_h = 0.0 if state.oil_day is not None and state.oil_day.year != local_date.year else state.oil_permit_hours_used_ytd_h
    if used_h + hours_in_day > fuel.oil_permit_hours_per_year.value:
        return f"permit hours {used_h:,.0f} of {fuel.oil_permit_hours_per_year.value:,.0f} used"
    return None


def choose_fuel(gas_price_usd_per_mmbtu: float, oil_price_usd_per_mmbtu_: float, fuel: FuelParams,
                oil_unavailable: str | None) -> tuple[Fuel, str]:
    """The day's fuel and why: the cheaper per MMBtu of gas-equivalent heat, oil only if available."""
    oil_equivalent = oil_price_usd_per_mmbtu_ * heat_input_multiplier("oil", fuel)
    if oil_equivalent >= gas_price_usd_per_mmbtu:
        return "gas", f"gas {gas_price_usd_per_mmbtu:.2f} <= oil {oil_equivalent:.2f} $/MMBtu of gas-equivalent heat"
    if oil_unavailable is not None:
        return "gas", (
            f"oil {oil_equivalent:.2f} is cheaper than gas {gas_price_usd_per_mmbtu:.2f} $/MMBtu "
            f"but cannot be used: {oil_unavailable}"
        )
    return "oil", f"oil {oil_equivalent:.2f} < gas {gas_price_usd_per_mmbtu:.2f} $/MMBtu of gas-equivalent heat"
