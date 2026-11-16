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
    assert meta.assumed_parameter_count == 29
    assert {table.table: table.rows for table in meta.inputs} == {"lbmp_da": 26280, "lbmp_rt": 26280, "gas_price": 269}


def test_run_reports_all_eight_invariants_and_implemented_ones_pass(base_scenario):
    invariants = {result.invariant_id: result for result in run(base_scenario, REPO_ROOT).meta.invariants}
    assert sorted(invariants) == [1, 2, 3, 4, 5, 6, 7, 8]
    for invariant_id in (6, 7, 8):
        assert invariants[invariant_id].status == "pass", invariants[invariant_id].detail
    for invariant_id in (1, 2, 3, 4, 5):
        assert invariants[invariant_id].status == "not_applicable"
    assert "module `dispatch` off" in invariants[3].detail  # base scenario books nothing


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
    modules = base_scenario.modules.model_copy(update={"rt_settlement": True})
    with pytest.raises(NotImplementedError, match="rt_settlement"):
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


# ------------------------------------------------------------------- milestone 1


@pytest.fixture(scope="module")
def m1_scenario():
    return load_scenario(REPO_ROOT / "config" / "scenario.m1.yaml")


@pytest.fixture(scope="module")
def m1_result(m1_scenario):
    return run(m1_scenario, REPO_ROOT)


def test_m1_january_invariants_3_4_6_7_8_pass(m1_result):
    invariants = {result.invariant_id: result for result in m1_result.meta.invariants}
    for invariant_id in (3, 4, 6, 7, 8):
        assert invariants[invariant_id].status == "pass", invariants[invariant_id].detail
    for invariant_id in (1, 2, 5):
        assert invariants[invariant_id].status == "not_applicable"


def test_m1_january_run_is_reproducible_with_a_real_ledger(m1_scenario, m1_result):
    again = run(m1_scenario, REPO_ROOT)
    assert m1_result.meta.ledger_entry_count > 0
    assert again.meta.ledger_hash == m1_result.meta.ledger_hash
    assert again.meta.run_id == m1_result.meta.run_id
    assert again.model_dump_json() == m1_result.model_dump_json()


def test_m1_january_shape(m1_result):
    meta = m1_result.meta
    assert len(m1_result.states) == len(m1_result.decisions) == len(m1_result.hour_inputs) == 31 * 24
    assert len(m1_result.offers) == 31
    assert {state.unit_id for state in m1_result.states} == {"U1"}
    running = [state for state in m1_result.states if state.committed]
    assert meta.ledger_entry_count == 3 * len(running)  # revenue, fuel, VOM per running hour
    assert set(meta.ledger_totals_usd) == {"da_energy_rev", "fuel_cost_gas", "vom"}
    assert all(state.output_mw <= state.available_mw == 553.32 for state in m1_result.states)
    assert all(state.da_schedule_mw == state.output_mw for state in m1_result.states)
    assert meta.energy_margin_usd == pytest.approx(sum(meta.ledger_totals_usd.values()), abs=0.005)


def test_m1_every_running_hour_is_in_the_money_and_every_idle_hour_is_not(m1_result):
    """Price-taker optimality, hour by hour: each cleared step earns more than its fuel + VOM."""
    offers = {(offer.unit_id, offer.local_date): offer for offer in m1_result.offers}
    for state, inputs in zip(m1_result.states, m1_result.hour_inputs, strict=True):
        offer = offers[(state.unit_id, state.ts_local.date())]
        lowest = offer.blocks[0].price_usd_per_mwh
        if state.committed:
            assert inputs.da_lbmp_usd_per_mwh > lowest
        else:
            assert inputs.da_lbmp_usd_per_mwh <= lowest


def test_m1_every_entry_traces_to_input_rows(m1_result):
    da_refs = {inputs.da_lbmp_ref for inputs in m1_result.hour_inputs}
    gas_refs = {inputs.gas_price_ref for inputs in m1_result.hour_inputs}
    for entry in m1_result.ledger:
        if entry.line == "da_energy_rev":
            assert entry.ref["lbmp_da"] in da_refs
        elif entry.line == "fuel_cost_gas":
            assert entry.ref["gas_price"] in gas_refs
        else:
            assert entry.ref == {"param": "units.U1.vom_usd_per_mwh"}
    # weekend days reuse the last published Henry Hub price: fewer distinct gas rows than days
    assert 15 <= len(gas_refs) < 31


@pytest.mark.parametrize("day,hours", [(date(2025, 3, 9), 23), (date(2025, 11, 2), 25)])
def test_dispatch_on_dst_days_has_one_state_per_real_hour(m1_scenario, day, hours):
    result = run(m1_scenario.model_copy(update={"start_date": day, "end_date": day}), REPO_ROOT)
    assert len(result.states) == hours
    assert len({state.ts_utc for state in result.states}) == hours
    assert {r.invariant_id: r.status for r in result.meta.invariants}[4] == "pass"


def test_two_units_dispatch_independently(m1_scenario):
    both = run(m1_scenario.model_copy(update={"unit_ids": ["U1", "U2"], "end_date": date(2025, 1, 7)}), REPO_ROOT)
    assert len(both.states) == 2 * 7 * 24
    assert {r.invariant_id: r.status for r in both.meta.invariants}[3] == "pass"
    by_unit = {unit: max(s.available_mw for s in both.states if s.unit_id == unit) for unit in ("U1", "U2")}
    assert by_unit == {"U1": 553.32, "U2": 546.93}


def test_m1_gas_is_henry_plus_the_assumed_monthly_basis(m1_result):
    """Q-028: delivered gas = Henry Hub + the config's assumed adder for the month (3 in January)."""
    assert m1_result.hour_inputs
    for inputs in m1_result.hour_inputs:
        assert inputs.gas_basis_adder_usd_per_mmbtu == 3.0
        assert inputs.gas_price_usd_per_mmbtu == pytest.approx(inputs.gas_index_price_usd_per_mmbtu + 3.0, abs=1e-9)


# ------------------------------------------------------------------- milestone 2


@pytest.fixture(scope="module")
def m2_result():
    return run(load_scenario(REPO_ROOT / "config" / "scenario.m2.yaml"), REPO_ROOT)


def test_m2_january_invariants_3_4_5_6_7_8_pass(m2_result):
    invariants = {result.invariant_id: result for result in m2_result.meta.invariants}
    for invariant_id in (3, 4, 5, 6, 7, 8):
        assert invariants[invariant_id].status == "pass", invariants[invariant_id].detail
    for invariant_id in (1, 2):
        assert invariants[invariant_id].status == "not_applicable"
    assert len(m2_result.commitment_bounds) == 31


def test_m2_run_time_limits_hold_in_january(m2_result, real_unit):
    """Every on-block lasts at least the minimum up time and every off-block the minimum down time."""
    blocks: list[tuple[bool, int]] = []
    for state in m2_result.states:
        if blocks and blocks[-1][0] == state.committed:
            blocks[-1] = (state.committed, blocks[-1][1] + 1)
        else:
            blocks.append((state.committed, 1))
    for committed, length in blocks[1:-1]:  # the first and last block are cut by the window
        assert length >= (real_unit.min_up_hours.value if committed else real_unit.min_down_hours.value)
    assert all(state.output_mw == 0 or state.output_mw >= real_unit.pmin_mw.value for state in m2_result.states)


def test_m2_solver_comparison(m2_result, m1_result):
    by_solver = {summary.solver: summary for summary in m2_result.meta.solver_comparison}
    assert list(by_solver) == ["dp", "price_taker_constrained", "price_taker"]
    assert m2_result.meta.solver == "dp" and by_solver["dp"].energy_margin_usd == m2_result.meta.energy_margin_usd
    # the price-taker baseline inside a DP run is the milestone 1 run, to the cent
    assert by_solver["price_taker"].energy_margin_usd == m1_result.meta.energy_margin_usd
    assert by_solver["price_taker"].starts == 14
    # the DP starts less often than either price-taker and beats the feasible one over the month
    assert by_solver["dp"].starts < by_solver["price_taker_constrained"].starts < by_solver["price_taker"].starts
    assert by_solver["dp"].energy_margin_usd > by_solver["price_taker_constrained"].energy_margin_usd
    assert by_solver["dp"].energy_margin_usd < by_solver["price_taker"].energy_margin_usd
    starts_in_ledger = sum(e.quantity for e in m2_result.ledger if e.line == "start_cost" and e.quantity_unit == "starts")
    assert starts_in_ledger == by_solver["dp"].starts
    assert set(m2_result.comparison_output_mw) == {"price_taker_constrained", "price_taker"}
    assert all(len(series) == len(m2_result.states) for series in m2_result.comparison_output_mw.values())


def test_m1_baseline_is_unchanged_by_milestone_2(m1_result):
    assert m1_result.meta.solver == "price_taker"
    assert m1_result.meta.energy_margin_usd == 18408203.95
    assert [summary.solver for summary in m1_result.meta.solver_comparison] == ["price_taker"]
    assert m1_result.commitment_bounds == [] and m1_result.comparison_output_mw == {}
