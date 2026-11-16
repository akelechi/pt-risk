"""PlantState and transition(): the state machine of one unit.

`transition` is the only function that produces a new state and the only function that
creates ledger entries. It is pure and deterministic: same arguments, same result.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from engine.contracts import Decision, HourInputs, LedgerEntry, PlantState
from engine.ledger.ledger import round_to_cent_usd
from engine.market import settlement
from engine.plant import cost
from engine.plant import fuel as fuel_rules
from engine.plant.params import FuelParams, UnitParams

# Config leaf behind the basis part of the delivered gas price (ledger `ref`).
GAS_BASIS_PARAM = "fuel.gas_basis_adder_usd_per_mmbtu_by_month"
OIL_RATIO_PARAM = "fuel.oil_price_ratio_to_no2_distillate"
OIL_PENALTY_PARAM = "fuel.oil_heat_rate_penalty_fraction"

MW_TOLERANCE = 1e-6


def initial_state(unit: UnitParams, ts_utc: datetime, ts_local: datetime, hours_offline_h: int,
                  available_mw: float | None = None, oil_inventory_bbl: float = 0.0) -> PlantState:
    """State before the first hour of a run: off for `hours_offline_h`, with
    `oil_inventory_bbl` in the tank and no permit hours used. `ts_*` is the first hour."""
    return PlantState(
        ts_utc=ts_utc,
        ts_local=ts_local,
        unit_id=unit.id,
        committed=False,
        hours_in_state_h=hours_offline_h,
        thermal_state=cost.thermal_state(hours_offline_h, unit),
        output_mw=0.0,
        fuel=None,
        oil_inventory_bbl=oil_inventory_bbl,
        oil_permit_hours_used_ytd_h=0.0,
        available_mw=cost.deterministic_available_mw(unit) if available_mw is None else available_mw,
        da_schedule_mw=0.0,
    )


def _entry(inputs: HourInputs, unit_id: str, line: str, quantity: float, quantity_unit: str,
           price: float, price_unit: str, sign: int, ref: dict[str, str]) -> LedgerEntry:
    return LedgerEntry(
        ts_utc=inputs.ts_utc,
        ts_local=inputs.ts_local,
        unit_id=unit_id,
        line=line,
        quantity=quantity,
        quantity_unit=quantity_unit,
        price=price,
        price_unit=price_unit,
        amount_usd=sign * round_to_cent_usd(quantity * price),
        ref=ref,
    )


def actual_output_mw(target_mw: float, available_mw: float, unit: UnitParams) -> float:
    """Output actually delivered against a DA schedule of `target_mw`, MW.

    The schedule when it is available; the available capacity when that is short but at
    least Pmin; nothing when less than Pmin is available (the unit cannot run).
    """
    if target_mw <= available_mw + MW_TOLERANCE:
        return target_mw
    return available_mw if available_mw >= unit.pmin_mw.value else 0.0


def start_of_day_oil(state: PlantState, local_date, fuel: FuelParams) -> tuple[float, float, float, object, float]:
    """Oil logistics applied once at the first hour of a local day.

    Returns (inventory bbl, received bbl, permit hours used, barge due date, barge bbl):
    permit hours reset when the calendar year changes; a barge due by today is unloaded;
    then, if the tank is below target and nothing is on order, a barge for the difference
    is ordered to arrive `barge_lead_days` later.
    """
    inventory, permit_h = state.oil_inventory_bbl, state.oil_permit_hours_used_ytd_h
    barge_due, barge_bbl, received = state.oil_barge_due, state.oil_barge_bbl, 0.0
    if state.oil_day is not None and state.oil_day.year != local_date.year:
        permit_h = 0.0
    if barge_due is not None and barge_due <= local_date:
        received = min(barge_bbl, fuel.oil_tank_capacity_bbl.value - inventory)
        inventory += received
        barge_due, barge_bbl = None, 0.0
    target = fuel.oil_target_inventory_bbl.value
    if barge_due is None and inventory < target:
        barge_due = local_date + timedelta(days=fuel.barge_lead_days.value)
        barge_bbl = target - inventory
    return inventory, received, permit_h, barge_due, barge_bbl


def transition(
    state: PlantState, decision: Decision, inputs: HourInputs, unit: UnitParams, commitment_costs: bool = False,
    fuel: FuelParams | None = None,
) -> tuple[PlantState, list[LedgerEntry]]:
    """Apply one hour's decision: returns the state during that hour and its ledger entries.

    The decision is the day-ahead schedule. Actual output equals it unless capacity is
    short in real time (a forced outage), in which case the shortfall is a deviation
    settled at the RT LBMP. Booked:
      da_energy_rev  +  DA schedule MWh x DA LBMP, whenever there is a schedule
      rt_balancing   +- (actual - schedule) MWh x RT LBMP, when they differ
      fuel_cost_gas  -  MMBtu x gas price, MMBtu from the true heat-rate curve at actual output
      vom            -  actual MWh x VOM
    With `commitment_costs` (every solver except the price-taker baseline), also:
      no_load_cost   -  no-load MMBtu x gas price, every hour on line
      start_cost     -  in the hour the unit comes on line: start fuel MMBtu x gas price,
                        and 1 start x other start cost, by thermal state before the start
      uplift         +  in the first hour after a commitment block ends, when the block's
                        costs exceeded its DA revenue (simplified make-whole, brief §4)
    State follows what physically happened: a unit on forced outage is off.

    With `fuel` (dual fuel on) the decision may burn oil: every MMBtu is multiplied by
    1 + the oil heat-rate penalty, priced at the plant's oil price and booked on
    `fuel_cost_oil` (no-load and start fuel likewise, on their own lines); the tank is
    drawn down by MMBtu / heat content and one permit hour is used per hour on oil. The
    start-of-day oil step (barge, reorder, permit year) runs in the first hour of each day.
    """
    if decision.unit_id != unit.id or state.unit_id != unit.id:
        raise ValueError("state, decision and unit do not describe the same unit")
    if decision.ts_utc != inputs.ts_utc:
        raise ValueError("decision and inputs are for different hours")
    if decision.commit != (decision.target_mw > 0):
        raise ValueError("commit must be true exactly when target_mw > 0")
    if decision.target_mw > inputs.available_mw + MW_TOLERANCE and not inputs.forced_outage:
        raise ValueError(f"target {decision.target_mw} MW exceeds available {inputs.available_mw} MW")
    if decision.commit and decision.fuel == "oil" and (fuel is None or inputs.oil_price_usd_per_mmbtu is None):
        raise ValueError("an oil decision needs the fuel parameters and an oil price")

    da_schedule_mw = decision.target_mw
    output_mw = actual_output_mw(da_schedule_mw, inputs.available_mw, unit)
    deviation_mw = output_mw - da_schedule_mw
    if abs(deviation_mw) > MW_TOLERANCE and inputs.rt_lbmp_usd_per_mwh is None:
        raise ValueError("a deviation from the DA schedule needs an RT LBMP to settle against")
    on_line = output_mw > 0
    same_state = on_line == state.committed
    hours_in_state_h = state.hours_in_state_h + 1 if same_state else 1
    hours_offline_h = 0 if on_line else hours_in_state_h
    started = on_line and not state.committed
    stopped = state.committed and not on_line
    gas_ref = {"gas_price": inputs.gas_price_ref, "gas_basis": GAS_BASIS_PARAM}
    on_oil = on_line and decision.fuel == "oil"
    if on_oil:
        heat_multiplier = fuel_rules.heat_input_multiplier("oil", fuel)
        fuel_price, fuel_line = inputs.oil_price_usd_per_mmbtu, "fuel_cost_oil"
        fuel_ref = {"oil_price": inputs.oil_price_ref or "", "oil_ratio": OIL_RATIO_PARAM, "oil_penalty": OIL_PENALTY_PARAM}
    else:
        heat_multiplier, fuel_price, fuel_line, fuel_ref = 1.0, inputs.gas_price_usd_per_mmbtu, "fuel_cost_gas", gas_ref

    oil_inventory_bbl, oil_received_bbl = state.oil_inventory_bbl, 0.0
    oil_permit_h, barge_due, barge_bbl, oil_day = (
        state.oil_permit_hours_used_ytd_h, state.oil_barge_due, state.oil_barge_bbl, state.oil_day
    )
    if fuel is not None and oil_day != inputs.ts_local.date():
        oil_day = inputs.ts_local.date()
        oil_inventory_bbl, oil_received_bbl, oil_permit_h, barge_due, barge_bbl = start_of_day_oil(state, oil_day, fuel)

    entries: list[LedgerEntry] = []
    if da_schedule_mw > 0:
        entries.append(
            _entry(inputs, unit.id, "da_energy_rev", settlement.da_energy_mwh(da_schedule_mw), "MWh",
                   inputs.da_lbmp_usd_per_mwh, "USD/MWh", +1, {"lbmp_da": inputs.da_lbmp_ref})
        )
    if abs(deviation_mw) > MW_TOLERANCE:
        entries.append(
            _entry(inputs, unit.id, "rt_balancing", settlement.rt_deviation_mwh(output_mw, da_schedule_mw), "MWh",
                   inputs.rt_lbmp_usd_per_mwh, "USD/MWh", +1,
                   {"lbmp_rt": inputs.rt_lbmp_ref or "", "cause": "forced outage" if inputs.forced_outage else "deviation"})
        )
    if on_line:
        energy_mwh = settlement.da_energy_mwh(output_mw)
        fuel_mmbtu = cost.fuel_burn_mmbtu_per_h(unit, output_mw) * heat_multiplier * settlement.HOUR_H
        entries.append(_entry(inputs, unit.id, fuel_line, fuel_mmbtu, "MMBtu", fuel_price, "USD/MMBtu", -1, fuel_ref))
        entries.append(
            _entry(inputs, unit.id, "vom", energy_mwh, "MWh",
                   unit.vom_usd_per_mwh.value, "USD/MWh", -1, {"param": f"units.{unit.id}.vom_usd_per_mwh"})
        )
        if commitment_costs:
            entries.append(
                _entry(inputs, unit.id, "no_load_cost",
                       cost.no_load_fuel_mmbtu_per_h(unit) * heat_multiplier * settlement.HOUR_H, "MMBtu",
                       fuel_price, "USD/MMBtu", -1, {**fuel_ref, "param": f"units.{unit.id}.no_load_mmbtu_per_hr"})
            )
        if commitment_costs and started:
            thermal = cost.thermal_state(state.hours_in_state_h, unit)
            spec = cost.start_spec(unit, thermal)
            start_ref = {"param": f"units.{unit.id}.start.{thermal}", "hours_offline_h": str(state.hours_in_state_h)}
            entries.append(
                _entry(inputs, unit.id, "start_cost", spec.start_fuel_mmbtu * heat_multiplier, "MMBtu",
                       fuel_price, "USD/MMBtu", -1, {**fuel_ref, **start_ref})
            )
            entries.append(
                _entry(inputs, unit.id, "start_cost", 1.0, "starts", spec.start_other_cost_usd, "USD/start", -1, start_ref)
            )
    if on_oil:
        burned_bbl = sum(e.quantity for e in entries if e.quantity_unit == "MMBtu") / fuel.oil_mmbtu_per_bbl.value
        if burned_bbl > oil_inventory_bbl + 1e-6:
            raise ValueError(f"oil burn {burned_bbl:.1f} bbl exceeds the tank's {oil_inventory_bbl:.1f} bbl")
        oil_inventory_bbl = max(0.0, oil_inventory_bbl - burned_bbl)
        oil_permit_h += settlement.HOUR_H
        if oil_permit_h > fuel.oil_permit_hours_per_year.value + 1e-9:
            raise ValueError("oil permit hours for the year are exceeded")

    # Commitment block totals (start to shutdown), kept in cents so they do not drift.
    # Only hours actually run count: costs incurred and the DA revenue of those hours.
    if on_line:
        carried_cost = 0.0 if started else state.commitment_block_cost_usd
        carried_revenue = 0.0 if started else state.commitment_block_da_revenue_usd
        cost_lines = ("fuel_cost_gas", "fuel_cost_oil", "vom", "no_load_cost", "start_cost")
        block_cost_usd = round(carried_cost - sum(e.amount_usd for e in entries if e.line in cost_lines), 2)
        block_revenue_usd = round(carried_revenue + sum(e.amount_usd for e in entries if e.line == "da_energy_rev"), 2)
    else:
        block_cost_usd = block_revenue_usd = 0.0
    # A block cut short by the unit's own forced outage is not made whole.
    if commitment_costs and stopped and not inputs.forced_outage:
        shortfall_usd = round(state.commitment_block_cost_usd - state.commitment_block_da_revenue_usd, 2)
        if shortfall_usd > 0:
            entries.append(
                LedgerEntry(
                    ts_utc=inputs.ts_utc, ts_local=inputs.ts_local, unit_id=unit.id, line="uplift",
                    quantity=shortfall_usd, quantity_unit="USD", price=None, price_unit=None, amount_usd=shortfall_usd,
                    ref={
                        "rule": "simplified make-whole: block costs less block DA revenue, floored at 0",
                        "block_hours_on_h": str(state.hours_in_state_h),
                        "block_cost_usd": f"{state.commitment_block_cost_usd:.2f}",
                        "block_da_revenue_usd": f"{state.commitment_block_da_revenue_usd:.2f}",
                    },
                )
            )

    new_state = PlantState(
        ts_utc=inputs.ts_utc,
        ts_local=inputs.ts_local,
        unit_id=unit.id,
        committed=on_line,
        hours_in_state_h=hours_in_state_h,
        thermal_state=cost.thermal_state(hours_offline_h, unit),
        output_mw=output_mw,
        fuel=decision.fuel if on_line else None,
        oil_inventory_bbl=oil_inventory_bbl,
        oil_permit_hours_used_ytd_h=oil_permit_h,
        oil_day=oil_day,
        oil_received_bbl=oil_received_bbl,
        oil_barge_due=barge_due,
        oil_barge_bbl=barge_bbl,
        available_mw=inputs.available_mw,
        da_schedule_mw=da_schedule_mw,
        commitment_block_cost_usd=block_cost_usd,
        commitment_block_da_revenue_usd=block_revenue_usd,
    )
    return new_state, entries
