"""Invariants from brief §5. Each check returns an `InvariantResult`.

Milestone 0 implements 6 (time integrity), 7 (provenance) and 8 (reproducibility).
Invariants 1-5 need dispatch and settlement; until their milestone they report
`not_applicable` with the milestone that will switch them on. They never report `pass`
for something that was not checked.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Iterable

import pandas as pd

from engine.contracts import CommitmentBound, HourInputs, InvariantResult, LedgerEntry, PlantState
from engine.inputs.timeutil import time_integrity_problems
from engine.ledger.ledger import round_to_cent_usd
from engine.plant import cost
from engine.plant import fuel as fuel_rules
from engine.plant.params import FuelParams, UnitParams, provenance_problems

INVARIANT_NAMES = {
    1: "Energy balance",
    2: "Fuel balance",
    3: "Cost identity",
    4: "Revenue identity",
    5: "Margin bound",
    6: "Time integrity",
    7: "Provenance",
    8: "Reproducibility",
}
PENDING_MILESTONE = {1: 3, 2: 4, 3: 1, 4: 1, 5: 2}
_MAX_PROBLEMS_SHOWN = 5
HALF_CENT_USD = 0.005 + 1e-9
EXACT_CENT_TOLERANCE_USD = 0.001  # two sums of whole cents either agree or differ by a cent or more
FUEL_SIDE_LINES = ("fuel_cost_gas", "fuel_cost_oil", "start_cost", "no_load_cost")
ENERGY_REVENUE_LINES = ("da_energy_rev", "rt_balancing")


def _result(invariant_id: int, problems: list[str], ok_detail: str) -> InvariantResult:
    if problems:
        shown = "; ".join(problems[:_MAX_PROBLEMS_SHOWN])
        more = f" (+{len(problems) - _MAX_PROBLEMS_SHOWN} more)" if len(problems) > _MAX_PROBLEMS_SHOWN else ""
        return InvariantResult(
            invariant_id=invariant_id, name=INVARIANT_NAMES[invariant_id], status="fail", detail=shown + more
        )
    return InvariantResult(
        invariant_id=invariant_id, name=INVARIANT_NAMES[invariant_id], status="pass", detail=ok_detail
    )


def pending(invariant_id: int) -> InvariantResult:
    """An invariant whose engine module does not exist yet."""
    return InvariantResult(
        invariant_id=invariant_id,
        name=INVARIANT_NAMES[invariant_id],
        status="not_applicable",
        detail=f"not checked: needs milestone {PENDING_MILESTONE[invariant_id]}",
    )


def module_off(invariant_id: int, module: str) -> InvariantResult:
    """An invariant with nothing to check because the scenario switched its module off."""
    return InvariantResult(
        invariant_id=invariant_id,
        name=INVARIANT_NAMES[invariant_id],
        status="not_applicable",
        detail=f"not checked: scenario has module `{module}` off, nothing is booked",
    )


def _booked_by_hour(entries: Iterable[LedgerEntry], lines: tuple[str, ...]) -> dict[tuple[str, Any], list[float]]:
    booked: dict[tuple[str, Any], list[float]] = defaultdict(list)
    for entry in entries:
        if entry.line in lines:
            booked[(entry.unit_id, entry.ts_utc)].append(entry.amount_usd)
    return booked


def _expected_fuel(
    state: PlantState,
    before: PlantState | None,
    unit: UnitParams,
    commitment_costs: bool,
    initial_hours_offline_h: int,
    fuel: FuelParams | None,
) -> tuple[list[float], float, bool]:
    """What one hour should have burned, from its state alone: (MMBtu components, other
    start cost in USD, whether the unit started). Components are curve fuel, then no-load,
    then start fuel; on oil each is multiplied by 1 + the heat-rate penalty."""
    multiplier = fuel_rules.heat_input_multiplier("oil", fuel) if state.fuel == "oil" and fuel is not None else 1.0
    components = [cost.fuel_burn_mmbtu_per_h(unit, state.output_mw) * multiplier]
    other_usd, started = 0.0, False
    if commitment_costs and state.committed:
        components.append(cost.no_load_fuel_mmbtu_per_h(unit) * multiplier)
        was_on = before.committed if before is not None else False
        if not was_on:
            hours_offline_h = before.hours_in_state_h if before is not None else initial_hours_offline_h
            spec = cost.start_spec(unit, cost.thermal_state(hours_offline_h, unit))
            components.append(spec.start_fuel_mmbtu * multiplier)
            other_usd, started = spec.start_other_cost_usd, True
    return components, other_usd, started


def check_cost_identity(
    states: list[PlantState],
    entries: list[LedgerEntry],
    hour_inputs: list[HourInputs],
    units: dict[str, UnitParams],
    commitment_costs: bool = False,
    initial_hours_offline_h: int = 0,
    fuel: FuelParams | None = None,
) -> InvariantResult:
    """Invariant 3: fuel_cost_* + start_cost + no_load_cost = MMBtu x price by fuel, to the cent.

    Recomputed independently of the ledger. MMBtu per hour = the state's output through
    the true heat-rate curve; with `commitment_costs`, plus no-load fuel in every hour on
    line and start fuel in the hour of a start; on oil, all multiplied by 1 + the oil
    heat-rate penalty. The price is the hour's gas or oil price according to the fuel the
    state burned. The other (non-fuel) start cost is added per start. A start is an
    off-to-on change between consecutive states of a unit; its thermal state follows the
    hours offline before it (`initial_hours_offline_h` before the first hour of the run).
    """
    gas_price = {(item.unit_id, item.ts_utc): item.gas_price_usd_per_mmbtu for item in hour_inputs}
    oil_price = {(item.unit_id, item.ts_utc): item.oil_price_usd_per_mmbtu for item in hour_inputs}
    booked = _booked_by_hour(entries, FUEL_SIDE_LINES)
    problems: list[str] = []
    total_mmbtu = 0.0
    total_usd = 0.0
    starts = 0
    previous: dict[str, PlantState] = {}
    for state in states:
        key = (state.unit_id, state.ts_utc)
        unit = units[state.unit_id]
        amounts = booked.pop(key, [])
        before = previous.get(state.unit_id)
        previous[state.unit_id] = state
        price = oil_price[key] if state.fuel == "oil" else gas_price[key]
        if state.fuel == "oil" and (price is None or fuel is None):
            problems.append(f"{state.unit_id} {state.ts_utc}: running on oil without an oil price")
            continue
        # Each component is a separate ledger line rounded to the cent, so the expected
        # total is the sum of the rounded components and must match exactly.
        components_mmbtu, other_start_usd, started = _expected_fuel(
            state, before, unit, commitment_costs, initial_hours_offline_h, fuel
        )
        other_usd = round_to_cent_usd(other_start_usd)
        starts += int(started)
        mmbtu = sum(components_mmbtu)
        expected_usd = -(sum(round_to_cent_usd(part * price) for part in components_mmbtu) + other_usd)
        if abs(sum(amounts) - expected_usd) > EXACT_CENT_TOLERANCE_USD:
            problems.append(
                f"{state.unit_id} {state.ts_utc}: booked {sum(amounts):.2f}, "
                f"MMBtu x price + other start cost = {expected_usd:.2f} "
                f"({mmbtu:.3f} MMBtu x {price:.4f} + {other_usd:.2f})"
            )
        total_mmbtu += mmbtu
        total_usd += sum(amounts)
    for unit_id, ts_utc in booked:
        problems.append(f"{unit_id} {ts_utc}: fuel-side entries booked in an hour with no state")
    with_starts = f" incl. no-load and {starts} starts" if commitment_costs else ""
    return _result(
        3,
        problems,
        f"{len(states)} unit-hours: fuel-side cost {total_usd:,.2f} USD on {total_mmbtu:,.1f} MMBtu{with_starts}, "
        "each hour to the cent",
    )


def check_fuel_balance(
    states: list[PlantState],
    entries: list[LedgerEntry],
    hour_inputs: list[HourInputs],
    units: dict[str, UnitParams],
    fuel: FuelParams,
    commitment_costs: bool,
    initial_hours_offline_h: int,
    initial_oil_inventory_bbl: float,
) -> InvariantResult:
    """Invariant 2: MMBtu burned = sum(IHR x MWh) + no-load hours x no-load + start fuel;
    oil bbl drawn = oil MMBtu / heat content; inventory never negative; permit hours never
    exceeded.

    Per hour: the MMBtu the state should have burned (recomputed from output, on/off and
    the start before it) must equal the MMBtu booked on the fuel-side ledger lines, on the
    line of the fuel the state burned. The tank must move by exactly deliveries less oil
    MMBtu / heat content, stay between 0 and its capacity, and permit hours must rise by
    one in each hour on oil and never pass the yearly limit. One unit (station tank).
    """
    del hour_inputs  # prices are not part of the fuel balance
    booked: dict[tuple[str, Any], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for entry in entries:
        if entry.line in FUEL_SIDE_LINES and entry.quantity_unit == "MMBtu":
            booked[(entry.unit_id, entry.ts_utc)][entry.line] += entry.quantity
    problems: list[str] = []
    totals = {"gas": 0.0, "oil": 0.0}
    oil_hours = 0
    received_bbl = 0.0
    previous: dict[str, PlantState] = {}
    for state in states:
        key = (state.unit_id, state.ts_utc)
        before = previous.get(state.unit_id)
        previous[state.unit_id] = state
        where = f"{state.unit_id} {state.ts_utc}"
        expected = sum(_expected_fuel(state, before, units[state.unit_id], commitment_costs, initial_hours_offline_h, fuel)[0])
        lines = booked.pop(key, {})
        ledger_mmbtu = sum(lines.values())
        if abs(ledger_mmbtu - expected) > 1e-6:
            problems.append(f"{where}: ledger {ledger_mmbtu:.3f} MMBtu, state implies {expected:.3f}")
        wrong_line = "fuel_cost_gas" if state.fuel == "oil" else "fuel_cost_oil"
        if lines.get(wrong_line, 0.0) > 0:
            problems.append(f"{where}: burning {state.fuel} but {wrong_line} is booked")
        on_oil = state.fuel == "oil"
        oil_mmbtu = expected if on_oil else 0.0
        if state.fuel is not None:
            totals[state.fuel] += expected
        inventory_before = before.oil_inventory_bbl if before is not None else initial_oil_inventory_bbl
        permit_before = before.oil_permit_hours_used_ytd_h if before is not None else 0.0
        if before is not None and before.ts_local.year != state.ts_local.year:
            permit_before = 0.0
        implied_inventory = inventory_before + state.oil_received_bbl - oil_mmbtu / fuel.oil_mmbtu_per_bbl.value
        if abs(state.oil_inventory_bbl - implied_inventory) > 1e-6:
            problems.append(f"{where}: tank {state.oil_inventory_bbl:.3f} bbl, balance implies {implied_inventory:.3f}")
        if state.oil_inventory_bbl < 0 or state.oil_inventory_bbl > fuel.oil_tank_capacity_bbl.value + 1e-6:
            problems.append(f"{where}: tank {state.oil_inventory_bbl:.1f} bbl is outside 0..capacity")
        if abs(state.oil_permit_hours_used_ytd_h - (permit_before + (1.0 if on_oil else 0.0))) > 1e-9:
            problems.append(f"{where}: permit hours {state.oil_permit_hours_used_ytd_h}, expected {permit_before + on_oil}")
        if state.oil_permit_hours_used_ytd_h > fuel.oil_permit_hours_per_year.value + 1e-9:
            problems.append(f"{where}: permit hours {state.oil_permit_hours_used_ytd_h} exceed the yearly limit")
        oil_hours += int(on_oil)
        received_bbl += state.oil_received_bbl
    for unit_id, ts_utc in booked:
        problems.append(f"{unit_id} {ts_utc}: fuel booked in an hour with no state")
    final_bbl = states[-1].oil_inventory_bbl if states else initial_oil_inventory_bbl
    return _result(
        2,
        problems,
        f"{len(states)} unit-hours: gas {totals['gas']:,.1f} MMBtu, oil {totals['oil']:,.1f} MMBtu = "
        f"{totals['oil'] / fuel.oil_mmbtu_per_bbl.value:,.1f} bbl over {oil_hours} permit hours; tank "
        f"{initial_oil_inventory_bbl:,.1f} + {received_bbl:,.1f} received - burn = {final_bbl:,.1f} bbl",
    )


def check_margin_bound(bounds: list[CommitmentBound]) -> InvariantResult:
    """Invariant 5: on every planning day, price-taker-with-constraints <= DP <= unconstrained.

    All three are values of the same planning problem (same horizon, starting state and
    prices), so the ordering is a property of the solver, not of the month.
    """
    tolerance_usd = 0.01
    problems: list[str] = []
    for bound in bounds:
        where = f"{bound.unit_id} {bound.local_date}"
        if bound.dp_value_usd < bound.price_taker_constrained_value_usd - tolerance_usd:
            problems.append(
                f"{where}: DP {bound.dp_value_usd:,.2f} < price-taker with constraints "
                f"{bound.price_taker_constrained_value_usd:,.2f}"
            )
        if bound.dp_value_usd > bound.unconstrained_value_usd + tolerance_usd:
            problems.append(
                f"{where}: DP {bound.dp_value_usd:,.2f} > unconstrained {bound.unconstrained_value_usd:,.2f}"
            )
    if not bounds:
        problems.append("no planning days were checked")
    return _result(
        5,
        problems,
        f"{len(bounds)} unit-days: price-taker with constraints <= DP <= unconstrained on every planning horizon",
    )


def check_energy_balance(
    states: list[PlantState], entries: list[LedgerEntry], hour_inputs: list[HourInputs]
) -> InvariantResult:
    """Invariant 1: sum of actual MW = sum of (DA schedule + deviation); the deviation line
    is RT balancing / RT price in every hour.

    Deviation is read two ways and must agree: from the states (output less schedule) and
    from the ledger (the MWh on `rt_balancing` entries, and their dollars divided by the
    RT LBMP). An hour with no deviation must carry no `rt_balancing` entry.
    """
    rt_lbmp = {(item.unit_id, item.ts_utc): item.rt_lbmp_usd_per_mwh for item in hour_inputs}
    booked: dict[tuple[str, Any], list[LedgerEntry]] = defaultdict(list)
    for entry in entries:
        if entry.line == "rt_balancing":
            booked[(entry.unit_id, entry.ts_utc)].append(entry)
    problems: list[str] = []
    total_actual = total_schedule = total_deviation = 0.0
    hours_with_deviation = 0
    for state in states:
        key = (state.unit_id, state.ts_utc)
        hour_entries = booked.pop(key, [])
        deviation_mw = state.output_mw - state.da_schedule_mw
        ledger_mwh = sum(entry.quantity for entry in hour_entries)
        if abs(ledger_mwh - deviation_mw) > 1e-6:
            problems.append(f"{state.unit_id} {state.ts_utc}: deviation {deviation_mw} MW, ledger {ledger_mwh} MWh")
        price = rt_lbmp[key]
        if hour_entries and price is None:
            problems.append(f"{state.unit_id} {state.ts_utc}: RT balancing booked without an RT LBMP")
        elif hour_entries:
            expected_usd = round_to_cent_usd(deviation_mw * price)
            if abs(sum(entry.amount_usd for entry in hour_entries) - expected_usd) > EXACT_CENT_TOLERANCE_USD:
                problems.append(
                    f"{state.unit_id} {state.ts_utc}: RT balancing {sum(e.amount_usd for e in hour_entries):.2f}, "
                    f"deviation x RT LBMP = {expected_usd:.2f}"
                )
            hours_with_deviation += 1
        total_actual += state.output_mw
        total_schedule += state.da_schedule_mw
        total_deviation += ledger_mwh
    for unit_id, ts_utc in booked:
        problems.append(f"{unit_id} {ts_utc}: RT balancing booked in an hour with no state")
    if abs(total_actual - (total_schedule + total_deviation)) > 1e-6 * max(len(states), 1):
        problems.append(f"sum actual {total_actual} != sum schedule {total_schedule} + deviation {total_deviation}")
    return _result(
        1,
        problems,
        f"{len(states)} unit-hours: actual {total_actual:,.1f} MWh = DA schedule {total_schedule:,.1f} "
        f"+ deviation {total_deviation:,.1f} over {hours_with_deviation} hours",
    )


def check_revenue_identity(
    states: list[PlantState], entries: list[LedgerEntry], hour_inputs: list[HourInputs]
) -> InvariantResult:
    """Invariant 4: energy revenue = da_mw x da_lbmp + (actual - da) x rt_lbmp, per hour, per unit.

    Recomputed from states and input prices. Each term is its own ledger line rounded to
    the cent, so the expected total is the sum of the rounded terms and must match exactly.
    A deviation in a run with no RT price is a failure.
    """
    da_lbmp = {(item.unit_id, item.ts_utc): item.da_lbmp_usd_per_mwh for item in hour_inputs}
    rt_lbmp = {(item.unit_id, item.ts_utc): item.rt_lbmp_usd_per_mwh for item in hour_inputs}
    booked = _booked_by_hour(entries, ENERGY_REVENUE_LINES)
    problems: list[str] = []
    total_usd = 0.0
    total_mwh = 0.0
    for state in states:
        key = (state.unit_id, state.ts_utc)
        amounts = booked.pop(key, [])
        deviation_mw = state.output_mw - state.da_schedule_mw
        expected_usd = round_to_cent_usd(state.da_schedule_mw * da_lbmp[key])
        if abs(deviation_mw) > 1e-9:
            if rt_lbmp[key] is None:
                problems.append(f"{state.unit_id} {state.ts_utc}: deviation {deviation_mw} MW but RT is not settled")
                continue
            expected_usd += round_to_cent_usd(deviation_mw * rt_lbmp[key])
        if abs(sum(amounts) - expected_usd) > EXACT_CENT_TOLERANCE_USD:
            problems.append(
                f"{state.unit_id} {state.ts_utc}: booked {sum(amounts):.2f}, "
                f"da_mw x da_lbmp + deviation x rt_lbmp = {expected_usd:.2f} "
                f"({state.da_schedule_mw} MW x {da_lbmp[key]}, {deviation_mw} MW x {rt_lbmp[key]})"
            )
        total_usd += sum(amounts)
        total_mwh += state.output_mw
    for unit_id, ts_utc in booked:
        problems.append(f"{unit_id} {ts_utc}: energy revenue booked in an hour with no state")
    return _result(
        4,
        problems,
        f"{len(states)} unit-hours: energy revenue {total_usd:,.2f} USD on {total_mwh:,.1f} MWh, each hour to the cent",
    )


def check_time_integrity(
    hourly_tables: dict[str, pd.DataFrame],
    timezone: str,
    start_date: date,
    end_date: date,
    expected_ptids: set[int],
) -> InvariantResult:
    """Invariant 6: every local day has 23/24/25 hours matching DST; no duplicate ts_utc.

    Also requires each table to cover exactly [start_date, end_date] for every expected
    location, so a silently short table cannot pass.
    """
    problems: list[str] = []
    days = 0
    hours = 0
    for name, table in hourly_tables.items():
        problems.extend(f"{name}: {problem}" for problem in time_integrity_problems(table, timezone))
        present = set(table["location_ptid"].unique()) if not table.empty else set()
        for ptid in sorted(expected_ptids - present):
            problems.append(f"{name}: no rows for PTID {ptid}")
        if table.empty:
            continue
        local_date = table["ts_utc"].dt.tz_convert(timezone).dt.date
        for ptid, dates in local_date.groupby(table["location_ptid"]):
            if dates.min() != start_date or dates.max() != end_date:
                problems.append(
                    f"{name}: PTID {ptid} covers {dates.min()}..{dates.max()}, "
                    f"scenario needs {start_date}..{end_date}"
                )
        days += int(local_date.groupby(table["location_ptid"]).nunique().sum())
        hours += len(table)
    return _result(
        6,
        problems,
        f"{hours} hourly rows over {days} location-days in {len(hourly_tables)} tables; "
        "all days 23/24/25 h per DST, no duplicate ts_utc",
    )


def check_provenance(plant_raw: Any, leaf_count: int, assumed_count: int) -> InvariantResult:
    """Invariant 7: no plant parameter without status and source (all five fields)."""
    return _result(
        7,
        provenance_problems(plant_raw),
        f"{leaf_count} parameter leaves all carry value/unit/status/source/as_of; {assumed_count} assumed",
    )


def check_reproducibility(first_ledger_hash: str, second_ledger_hash: str, entry_count: int) -> InvariantResult:
    """Invariant 8: executing the scenario twice gives an identical ledger hash."""
    problems = (
        []
        if first_ledger_hash == second_ledger_hash
        else [f"ledger hash differs between two executions: {first_ledger_hash} vs {second_ledger_hash}"]
    )
    return _result(8, problems, f"two executions, identical ledger hash over {entry_count} entries")
