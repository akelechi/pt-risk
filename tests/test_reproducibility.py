"""Invariant 8 and ground rule 4: a run is reproducible and records what makes it so."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from engine.run import load_scenario, run
from tests.conftest import REPO_ROOT

FORBIDDEN_CLOCK_CALLS = re.compile(r"datetime\.now|datetime\.utcnow|date\.today|time\.time\(|Timestamp\.now|Timestamp\.today")


@pytest.fixture(scope="module")
def base_scenario():
    return load_scenario(REPO_ROOT / "config" / "scenario.base.yaml")


def test_run_twice_gives_identical_ledger_hash_and_run_id(base_scenario):
    first = run(base_scenario, REPO_ROOT)
    second = run(base_scenario, REPO_ROOT)
    assert first.meta.ledger_hash == second.meta.ledger_hash
    assert first.meta.run_id == second.meta.run_id
    assert first.model_dump_json() == second.model_dump_json()


def test_run_records_what_makes_it_reproducible(base_scenario):
    meta = run(base_scenario, REPO_ROOT).meta
    assert len(meta.config_hash) == 64 and len(meta.run_id) == 12
    assert set(meta.data_snapshot_ids) == {"lbmp_da", "lbmp_rt", "gas_price"}
    assert meta.code_version and meta.seed == base_scenario.seed
    assert meta.assumed_parameter_count == 33
    assert {table.table: table.rows for table in meta.inputs} == {"lbmp_da": 26280, "lbmp_rt": 26280, "gas_price": 269}


def test_run_reports_all_eight_invariants_and_implemented_ones_pass(base_scenario):
    invariants = {result.invariant_id: result for result in run(base_scenario, REPO_ROOT).meta.invariants}
    assert sorted(invariants) == [1, 2, 3, 4, 5, 6, 7, 8]
    for invariant_id in (6, 7, 8):
        assert invariants[invariant_id].status == "pass", invariants[invariant_id].detail
    for invariant_id in (1, 2, 3, 4, 5):
        assert invariants[invariant_id].status == "not_applicable"


def test_run_id_changes_with_seed_dates_and_config(base_scenario, repo_copy: Path):
    base = run(base_scenario, repo_copy).meta
    reseeded = run(base_scenario.model_copy(update={"seed": base_scenario.seed + 1}), repo_copy).meta
    january = run(base_scenario.model_copy(update={"end_date": date(2025, 1, 31)}), repo_copy).meta
    assert len({base.run_id, reseeded.run_id, january.run_id}) == 3
    assert january.inputs[0].rows == 3 * 31 * 24

    plant_path = repo_copy / "config" / "plant.roseton.yaml"
    plant_path.write_text(plant_path.read_text().replace("value: 3.0, unit: USD/MWh", "value: 3.5, unit: USD/MWh"))
    edited = run(base_scenario, repo_copy).meta
    assert edited.config_hash != base.config_hash and edited.run_id != base.run_id


def test_one_unit_scenario_loads_only_its_bus_and_the_zone(base_scenario):
    meta = run(base_scenario.model_copy(update={"unit_ids": ["U1"]}), REPO_ROOT).meta
    assert meta.inputs[0].locations == ["HUD VL", "ROSETON___1"]
    assert {result.invariant_id: result.status for result in meta.invariants}[6] == "pass"


def test_scenario_outside_the_data_window_fails_invariant_6(base_scenario):
    meta = run(base_scenario.model_copy(update={"end_date": date(2026, 1, 31)}), REPO_ROOT).meta
    time_integrity = {result.invariant_id: result for result in meta.invariants}[6]
    assert time_integrity.status == "fail" and "scenario needs" in time_integrity.detail


def test_unimplemented_modules_and_unknown_units_are_refused(base_scenario):
    modules = base_scenario.modules.model_copy(update={"dispatch": True})
    with pytest.raises(NotImplementedError, match="dispatch"):
        run(base_scenario.model_copy(update={"modules": modules}), REPO_ROOT)
    with pytest.raises(ValueError, match="U9"):
        run(base_scenario.model_copy(update={"unit_ids": ["U9"]}), REPO_ROOT)


def test_engine_never_reads_the_wall_clock():
    """Brief §10: no datetime.now() anywhere in the engine; time comes from the scenario."""
    offenders = []
    for path in sorted((REPO_ROOT / "engine").rglob("*.py")) + sorted((REPO_ROOT / "api").rglob("*.py")):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            code = line.split("#", 1)[0]
            if FORBIDDEN_CLOCK_CALLS.search(code) and '"""' not in line:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
    assert offenders == []
