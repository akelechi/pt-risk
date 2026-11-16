"""run(scenario) -> RunResult: the single entry point of the engine.

A run records what makes it reproducible: config hash, data snapshot ids, code version
and seed. Its id is derived from those four, so the same scenario on the same data and
code always has the same id. Time comes from the scenario; the wall clock is never read.

Milestone 0: all modules are off, so the ledger is empty and there are no states. The run
still loads and verifies its inputs and evaluates invariants 6, 7 and 8.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from engine.contracts import PlantState, RunMeta, RunResult, Scenario, TableSummary
from engine.inputs import store
from engine.ledger import reconcile
from engine.ledger.ledger import Ledger
from engine.plant.params import flatten_leaves, parse_plant, status_counts
from engine.version import code_version

REPO_ROOT = Path(__file__).resolve().parents[1]
HOURLY_TABLES = ("lbmp_da", "lbmp_rt")
DAILY_TABLES = ("gas_price",)
RUN_ID_LENGTH = 12


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


def _execute(scenario: Scenario, inputs: dict[str, pd.DataFrame]) -> tuple[Ledger, list[PlantState]]:
    """Run the state machine over the scenario window.

    Milestone 0: no module is implemented, so nothing is dispatched and nothing is booked.
    A scenario that switches a module on is refused rather than silently ignored.
    """
    switched_on = [name for name, on in scenario.modules.model_dump().items() if on]
    if switched_on:
        raise NotImplementedError(f"modules not implemented yet: {switched_on}")
    return Ledger(), []


def run(scenario: Scenario, root: Path = REPO_ROOT) -> RunResult:
    """Execute a scenario and return its ledger, states and metadata."""
    root = Path(root)
    market_raw = yaml.safe_load((root / scenario.market_config).read_text())
    plant_raw = yaml.safe_load((root / scenario.plant_config).read_text())
    plant = parse_plant(plant_raw)
    timezone = market_raw["timezone"]

    unknown_units = [unit_id for unit_id in scenario.unit_ids if unit_id not in {u.id for u in plant.units}]
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

    ledger, states = _execute(scenario, inputs)
    ledger_again, _ = _execute(scenario, inputs)
    ledger_hash = ledger.content_hash()

    leaves = flatten_leaves(plant)
    assumed_count = status_counts(plant)["assumed"]
    invariants = [reconcile.pending(invariant_id) for invariant_id in (1, 2, 3, 4, 5)]
    invariants.append(
        reconcile.check_time_integrity(
            {name: inputs[name] for name in HOURLY_TABLES},
            timezone,
            scenario.start_date,
            scenario.end_date,
            ptids,
        )
    )
    invariants.append(reconcile.check_provenance(plant_raw, len(leaves), assumed_count))
    invariants.append(reconcile.check_reproducibility(ledger_hash, ledger_again.content_hash(), len(ledger)))

    config_hash = canonical_hash(
        {"scenario": scenario.model_dump(mode="json"), "plant": plant_raw, "market": market_raw}
    )
    version = code_version(root)
    run_id = canonical_hash(
        {"config_hash": config_hash, "data_snapshot_ids": snapshot_ids, "code_version": version, "seed": scenario.seed}
    )[:RUN_ID_LENGTH]

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
    )
    return RunResult(meta=meta, ledger=list(ledger.entries), states=states)


if __name__ == "__main__":
    result = run(load_scenario(REPO_ROOT / "config" / "scenario.base.yaml"))
    print(result.meta.model_dump_json(indent=2))
