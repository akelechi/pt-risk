"""run(scenario) -> RunResult: the single entry point of the engine.

A run records what makes it reproducible: config hash, data snapshot ids, code version
and seed. Its id is derived from those four, so the same scenario on the same data and
code always has the same id. Time comes from the scenario; the wall clock is never read.

Modules implemented: `dispatch` (milestone 1: price-taker, gas only, DA only) and
`dp_commitment` (milestone 2: DP commitment with start cost, no-load and run-time limits,
plus the price-taker baselines it is compared with). A scenario that switches on any
other module is refused. With `dispatch` off the run only loads and verifies its inputs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from engine.contracts import (
    CommitmentBound,
    DayPrices,
    Decision,
    HourInputs,
    HourPrice,
    Offer,
    PlantState,
    RunMeta,
    RunResult,
    Scenario,
    SolverSummary,
    TableSummary,
)
from engine.inputs import store
from engine.ledger import reconcile
from engine.ledger.ledger import Ledger
from engine.market.offer import build_offer
from engine.market.prices import GasPrices, delivered_gas_price_usd_per_mmbtu, lbmp_row_ref
from engine.plant import commitment, cost
from engine.plant.params import Plant, flatten_leaves, parse_plant, status_counts
from engine.plant.state import initial_state, transition
from engine.version import code_version

REPO_ROOT = Path(__file__).resolve().parents[1]
HOURLY_TABLES = ("lbmp_da", "lbmp_rt")
DAILY_TABLES = ("gas_price",)
RUN_ID_LENGTH = 12
IMPLEMENTED_MODULES = {"dispatch", "dp_commitment"}
# Index the assumed basis adder is added to. Module gas_basis (milestone 5) replaces the
# adder with a published delivered index.
BASE_GAS_POINT = "HENRY"
# The DP plans over this many local days and keeps the first (brief §4: 48 h rolling, step 24 h).
PLANNING_HORIZON_DAYS = 2
# Solvers a DP run is compared with (invariant 5 and the milestone 2 numbers).
COMPARISON_SOLVERS = ("price_taker_constrained", "price_taker")
ENERGY_MARGIN_LINES = (
    "da_energy_rev",
    "rt_balancing",
    "fuel_cost_gas",
    "fuel_cost_oil",
    "start_cost",
    "no_load_cost",
    "vom",
    "emissions_cost",
)


@dataclass
class Execution:
    """Everything one pass of the state machine produces."""

    ledger: Ledger = field(default_factory=Ledger)
    states: list[PlantState] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    offers: list[Offer] = field(default_factory=list)
    hour_inputs: list[HourInputs] = field(default_factory=list)
    commitment_bounds: list[CommitmentBound] = field(default_factory=list)


def load_scenario(path: Path) -> Scenario:
    """Load a scenario YAML file."""
    return Scenario.model_validate(yaml.safe_load(Path(path).read_text()))


def canonical_hash(payload: Any) -> str:
    """sha256 of a JSON-canonical rendering (sorted keys; dates as ISO strings)."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slice_hourly(table: pd.DataFrame, scenario: Scenario, timezone: str, ptids: set[int]) -> pd.DataFrame:
    local_date = table["ts_utc"].dt.tz_convert(timezone).dt.date
    keep = (local_date >= scenario.start_date) & (local_date <= scenario.end_date)
    return table[keep & table["location_ptid"].isin(ptids)].reset_index(drop=True)


def _summary(name: str, table: pd.DataFrame, snapshot_id: str) -> TableSummary:
    if table.empty:
        return TableSummary(table=name, rows=0, first_local=None, last_local=None, locations=[], snapshot_id=snapshot_id)
    if "ts_local" in table:
        first, last = table["ts_local"].min().isoformat(), table["ts_local"].max().isoformat()
        locations = sorted(table["location"].unique().tolist())
    else:
        first, last = table["date"].min().isoformat(), table["date"].max().isoformat()
        locations = sorted(table["point"].unique().tolist())
    return TableSummary(
        table=name, rows=len(table), first_local=first, last_local=last, locations=locations, snapshot_id=snapshot_id
    )


def _day_prices(unit_id: str, unit_rows: pd.DataFrame) -> list[DayPrices]:
    """Group one unit's DA LBMP rows (sorted by ts_utc) into local days."""
    days: list[DayPrices] = []
    for local_date, rows in unit_rows.groupby(unit_rows["ts_local"].dt.date, sort=True):
        hours = [
            HourPrice(
                ts_utc=row.ts_utc.to_pydatetime(),
                ts_local=row.ts_local.to_pydatetime(),
                da_lbmp_usd_per_mwh=float(row.lbmp_usd_per_mwh),
                da_lbmp_ref=lbmp_row_ref(row.source_id, int(row.location_ptid), row.ts_utc),
            )
            for row in rows.itertuples(index=False)
        ]
        days.append(DayPrices(unit_id=unit_id, local_date=local_date, hours=hours))
    return days


def solver_of(scenario: Scenario) -> str:
    """The commitment solver a scenario's modules select."""
    return "dp" if scenario.modules.dp_commitment else "price_taker"


def _execute(
    scenario: Scenario, plant: Plant, market_raw: dict, inputs: dict[str, pd.DataFrame], solver: str | None = None
) -> Execution:
    """Run the state machine over the scenario window, unit by unit, day by day, hour by hour.

    Per unit and local day: delivered gas price for the day (index + assumed basis) -> offer
    -> commitment solver -> one transition per hour. The solver sees the day and, when the
    window has one, the next day (perfect foresight); only the first day's decisions are
    used. Ledger entries come only from `transition`. `solver` overrides the scenario's
    own solver, for the comparison runs.
    """
    switched_on = {name for name, on in scenario.modules.model_dump().items() if on}
    not_implemented = sorted(switched_on - IMPLEMENTED_MODULES)
    if not_implemented:
        raise NotImplementedError(f"modules not implemented yet: {not_implemented}")
    if "dp_commitment" in switched_on and "dispatch" not in switched_on:
        raise ValueError("module dp_commitment needs module dispatch")
    execution = Execution()
    if "dispatch" not in switched_on:
        return execution
    solver = solver or solver_of(scenario)
    commitment_costs = solver in commitment.COMMITMENT_COST_SOLVERS

    gas = GasPrices(inputs["gas_price"], BASE_GAS_POINT, market_raw["gas_price_max_staleness_days"])
    basis_adder_by_month = plant.fuel.gas_basis_adder_usd_per_mmbtu_by_month.value
    ptid_of_unit = {item["unit_id"]: item["ptid"] for item in market_raw["locations"] if item.get("unit_id")}
    lbmp_da = inputs["lbmp_da"]

    for unit_id in scenario.unit_ids:
        unit = plant.unit(unit_id)
        if unit_id not in ptid_of_unit:
            raise ValueError(f"market config has no pricing location for unit {unit_id}")
        unit_rows = lbmp_da[lbmp_da["location_ptid"] == ptid_of_unit[unit_id]].sort_values("ts_utc")
        days = _day_prices(unit_id, unit_rows)
        if not days:
            raise ValueError(f"no DA LBMP rows for unit {unit_id} in the scenario window")
        available_mw = cost.deterministic_available_mw(unit)
        first_hour = days[0].hours[0]
        state = initial_state(unit, first_hour.ts_utc, first_hour.ts_local, scenario.initial_hours_offline_h)

        gas_of_day = []
        offers = []
        for day in days:
            gas_index_price, gas_ref = gas.on(day.local_date)
            gas_price, gas_basis_adder = delivered_gas_price_usd_per_mmbtu(
                gas_index_price, basis_adder_by_month, day.local_date
            )
            gas_of_day.append((gas_price, gas_index_price, gas_basis_adder, gas_ref))
            offers.append(
                build_offer(unit, day.local_date, "gas", gas_price, gas_ref, available_mw, market_raw["offer_price_decimals"])
            )

        for index, day in enumerate(days):
            gas_price, gas_index_price, gas_basis_adder, gas_ref = gas_of_day[index]
            horizon = list(zip(days[index : index + PLANNING_HORIZON_DAYS], offers[index : index + PLANNING_HORIZON_DAYS]))
            decisions = commitment.solve(horizon, state, unit, solver=solver)
            if solver == "dp":
                execution.commitment_bounds.append(commitment.margin_bound(unit, horizon, state))
            execution.offers.append(offers[index])
            for hour, decision in zip(day.hours, decisions, strict=True):
                hour_inputs = HourInputs(
                    ts_utc=hour.ts_utc,
                    ts_local=hour.ts_local,
                    unit_id=unit_id,
                    da_lbmp_usd_per_mwh=hour.da_lbmp_usd_per_mwh,
                    da_lbmp_ref=hour.da_lbmp_ref,
                    gas_price_usd_per_mmbtu=gas_price,
                    gas_index_price_usd_per_mmbtu=gas_index_price,
                    gas_basis_adder_usd_per_mmbtu=gas_basis_adder,
                    gas_price_ref=gas_ref,
                    available_mw=available_mw,
                )
                state, entries = transition(state, decision, hour_inputs, unit, commitment_costs=commitment_costs)
                execution.ledger.append(entries)
                execution.states.append(state)
                execution.decisions.append(decision)
                execution.hour_inputs.append(hour_inputs)
    return execution


def solver_summary(solver: str, execution: Execution) -> SolverSummary:
    """One solver's outcome over the window, read from its ledger and states."""
    totals = ledger_totals_usd(execution.ledger)
    return SolverSummary(
        solver=solver,
        energy_margin_usd=energy_margin_usd(totals),
        uplift_usd=totals.get("uplift", 0.0),
        starts=count_starts(execution.states),
        hours_on=sum(1 for state in execution.states if state.committed),
        output_mwh=sum(state.output_mw for state in execution.states),
    )


def count_starts(states: list[PlantState]) -> int:
    """Off-to-on transitions per unit; every unit begins a run off."""
    starts = 0
    previous: dict[str, bool] = {}
    for state in states:
        if state.committed and not previous.get(state.unit_id, False):
            starts += 1
        previous[state.unit_id] = state.committed
    return starts


def ledger_totals_usd(ledger: Ledger) -> dict[str, float]:
    """Sum of amount_usd by ledger line, exact to the cent (a view over the entries)."""
    totals: dict[str, Decimal] = {}
    for entry in ledger.entries:
        totals[entry.line] = totals.get(entry.line, Decimal("0")) + Decimal(repr(entry.amount_usd))
    return {line: float(total) for line, total in sorted(totals.items())}


def energy_margin_usd(totals_usd: dict[str, float]) -> float:
    """Energy margin: energy revenue (DA + RT) less fuel, start, no-load, VOM and emissions."""
    return float(sum(Decimal(repr(totals_usd.get(line, 0.0))) for line in ENERGY_MARGIN_LINES))


def run(scenario: Scenario, root: Path = REPO_ROOT) -> RunResult:
    """Execute a scenario and return its ledger, states and metadata."""
    root = Path(root)
    market_raw = yaml.safe_load((root / scenario.market_config).read_text())
    plant_raw = yaml.safe_load((root / scenario.plant_config).read_text())
    plant = parse_plant(plant_raw)
    timezone = market_raw["timezone"]
    units = {unit.id: unit for unit in plant.units}

    unknown_units = [unit_id for unit_id in scenario.unit_ids if unit_id not in units]
    if unknown_units:
        raise ValueError(f"scenario names units not in the plant config: {unknown_units}")
    ptids = {
        item["ptid"]
        for item in market_raw["locations"]
        if item.get("unit_id") in scenario.unit_ids or item["type"] == "zone"
    }

    inputs: dict[str, pd.DataFrame] = {}
    snapshot_ids: dict[str, str] = {}
    for name in HOURLY_TABLES:
        table, snapshot_ids[name] = store.read_table(root, name)
        inputs[name] = _slice_hourly(table, scenario, timezone, ptids)
    for name in DAILY_TABLES:
        table, snapshot_ids[name] = store.read_table(root, name)
        inputs[name] = table[table["date"] <= scenario.end_date].reset_index(drop=True)

    execution = _execute(scenario, plant, market_raw, inputs)
    execution_again = _execute(scenario, plant, market_raw, inputs)
    ledger = execution.ledger
    ledger_hash = ledger.content_hash()
    entries = list(ledger.entries)

    leaves = flatten_leaves(plant)
    assumed_count = status_counts(plant)["assumed"]
    dispatching = scenario.modules.dispatch
    solver = solver_of(scenario)
    commitment_costs = solver in commitment.COMMITMENT_COST_SOLVERS
    comparisons = (
        {name: _execute(scenario, plant, market_raw, inputs, solver=name) for name in COMPARISON_SOLVERS}
        if solver == "dp"
        else {}
    )
    invariants = [
        reconcile.pending(1),
        reconcile.pending(2),
        reconcile.check_cost_identity(
            execution.states, entries, execution.hour_inputs, units, commitment_costs, scenario.initial_hours_offline_h
        )
        if dispatching
        else reconcile.module_off(3, "dispatch"),
        reconcile.check_revenue_identity(execution.states, entries, execution.hour_inputs)
        if dispatching
        else reconcile.module_off(4, "dispatch"),
        reconcile.check_margin_bound(execution.commitment_bounds)
        if solver == "dp"
        else reconcile.module_off(5, "dp_commitment"),
        reconcile.check_time_integrity(
            {name: inputs[name] for name in HOURLY_TABLES},
            timezone,
            scenario.start_date,
            scenario.end_date,
            ptids,
        ),
        reconcile.check_provenance(plant_raw, len(leaves), assumed_count),
        reconcile.check_reproducibility(ledger_hash, execution_again.ledger.content_hash(), len(ledger)),
    ]

    config_hash = canonical_hash(
        {"scenario": scenario.model_dump(mode="json"), "plant": plant_raw, "market": market_raw}
    )
    version = code_version(root)
    run_id = canonical_hash(
        {"config_hash": config_hash, "data_snapshot_ids": snapshot_ids, "code_version": version, "seed": scenario.seed}
    )[:RUN_ID_LENGTH]
    totals = ledger_totals_usd(ledger)

    meta = RunMeta(
        run_id=run_id,
        scenario=scenario,
        config_hash=config_hash,
        data_snapshot_ids=snapshot_ids,
        code_version=version,
        seed=scenario.seed,
        ledger_hash=ledger_hash,
        ledger_entry_count=len(ledger),
        inputs=[_summary(name, inputs[name], snapshot_ids[name]) for name in (*HOURLY_TABLES, *DAILY_TABLES)],
        invariants=invariants,
        assumed_parameter_count=assumed_count,
        ledger_totals_usd=totals,
        energy_margin_usd=energy_margin_usd(totals),
        solver=solver,
        solver_comparison=(
            [solver_summary(solver, execution), *(solver_summary(name, run_) for name, run_ in comparisons.items())]
            if dispatching
            else []
        ),
    )
    return RunResult(
        meta=meta,
        ledger=entries,
        states=execution.states,
        decisions=execution.decisions,
        offers=execution.offers,
        hour_inputs=execution.hour_inputs,
        commitment_bounds=execution.commitment_bounds,
        comparison_output_mw={name: [state.output_mw for state in run_.states] for name, run_ in comparisons.items()},
    )


if __name__ == "__main__":
    import sys

    scenario_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "config" / "scenario.base.yaml"
    print(run(load_scenario(scenario_path)).meta.model_dump_json(indent=2))
