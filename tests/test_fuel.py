"""Dual fuel (milestone 4): oil price, fuel choice, burning oil, the tank, permit hours, barges.

Hand figures, toy unit (Pmin 150, Pmax 600, fuel at 600 MW 6,345 MMBtu/h, no-load 400):
  No. 2 index 2.40 $/gal = 100.80 $/bbl; x 0.70 / 6.3 MMBtu/bbl = 11.20 $/MMBtu of oil
  oil needs 1.03 x the heat: 11.20 x 1.03 = 11.536 $/MMBtu of gas-equivalent heat
  600 MW hour on oil: fuel 6,345 x 1.03 = 6,535.35 MMBtu x 11.20 = 73,195.92
                      no-load 400 x 1.03 = 412 MMBtu x 11.20 = 4,614.40
                      tank: (6,535.35 + 412) / 6.3 = 1,102.754 bbl; one permit hour
  cold start on oil:  5,000 x 1.03 = 5,150 MMBtu x 11.20 = 57,680.00, plus 25,000 other
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from engine.contracts import Decision, HourInputs
from engine.ledger import reconcile
from engine.ledger.ledger import Ledger
from engine.market.offer import build_offer
from engine.plant import fuel as fuel_rules
from engine.plant.params import parse_plant
from engine.plant.state import initial_state, start_of_day_oil, transition
from engine.run import REPO_ROOT, energy_margin_usd, ledger_totals_usd, load_scenario, run
from tests.conftest import OFFER_PRICE_DECIMALS, toy_plant_raw

NY = ZoneInfo("America/New_York")
OIL_USD_PER_MMBTU = 11.20
GAS_USD_PER_MMBTU = 13.00


@pytest.fixture(scope="module")
def toy_plant():
    return parse_plant(toy_plant_raw())


def hour_at(day: date, hour: int) -> tuple[datetime, datetime]:
    local = datetime(day.year, day.month, day.day, hour, tzinfo=NY)
    return local.astimezone(ZoneInfo("UTC")), local


def oil_inputs(day: date, hour: int, lbmp: float = 130.0) -> HourInputs:
    ts_utc, ts_local = hour_at(day, hour)
    return HourInputs(
        ts_utc=ts_utc, ts_local=ts_local, unit_id="U1", da_lbmp_usd_per_mwh=lbmp, da_lbmp_ref="hand:lbmp",
        gas_price_usd_per_mmbtu=GAS_USD_PER_MMBTU, gas_index_price_usd_per_mmbtu=GAS_USD_PER_MMBTU,
        gas_basis_adder_usd_per_mmbtu=0.0, gas_price_ref="hand:gas", available_mw=600.0,
        oil_price_usd_per_mmbtu=OIL_USD_PER_MMBTU, oil_index_price_usd_per_bbl=100.80, oil_price_ref="hand:oil",
    )


def decide(inputs: HourInputs, mw: float, fuel: str = "oil") -> Decision:
    return Decision(ts_utc=inputs.ts_utc, ts_local=inputs.ts_local, unit_id="U1", commit=mw > 0, target_mw=mw,
                    fuel=fuel, reason="hand")


def run_hours(toy_plant, plan: list[tuple[float, str]], inventory_bbl: float = 250000.0, day: date = date(2025, 1, 17)):
    """Settle consecutive hours from midnight of `day`: plan = [(MW, fuel), ...]."""
    unit = toy_plant.unit("U1")
    ts_utc, ts_local = hour_at(day, 0)
    state = initial_state(unit, ts_utc, ts_local, 168, 600.0, inventory_bbl)
    ledger, states, inputs_list = Ledger(), [], []
    for index, (mw, fuel) in enumerate(plan):
        inputs = oil_inputs(day + timedelta(days=index // 24), index % 24)
        state, entries = transition(state, decide(inputs, mw, fuel), inputs, unit, commitment_costs=True, fuel=toy_plant.fuel)
        ledger.append(entries)
        states.append(state)
        inputs_list.append(inputs)
    return ledger, states, inputs_list


def test_oil_price_and_heat_penalty_by_hand(toy_plant):
    assert fuel_rules.oil_price_usd_per_mmbtu(100.80, toy_plant.fuel) == pytest.approx(11.20)
    assert fuel_rules.heat_input_multiplier("oil", toy_plant.fuel) == 1.03
    assert fuel_rules.heat_input_multiplier("gas", toy_plant.fuel) == 1.0


def test_fuel_choice_is_the_cheaper_heat_if_oil_is_available(toy_plant):
    assert fuel_rules.choose_fuel(13.00, 11.20, toy_plant.fuel, None)[0] == "oil"  # 11.536 < 13.00
    assert fuel_rules.choose_fuel(11.50, 11.20, toy_plant.fuel, None)[0] == "gas"  # penalty makes oil dearer
    assert fuel_rules.choose_fuel(11.536, 11.20, toy_plant.fuel, None)[0] == "gas"  # a tie stays on gas
    fuel, why = fuel_rules.choose_fuel(13.00, 11.20, toy_plant.fuel, "tank 10 bbl is below a worst-case day of 27,000 bbl")
    assert fuel == "gas" and "cannot be used: tank 10 bbl" in why


def test_oil_needs_a_worst_case_day_in_the_tank_and_permit_hours(toy_plant):
    unit, fuel = toy_plant.unit("U1"), toy_plant.fuel
    # (6,345 + 400) x 24 + 5,000 cold start = 166,880 MMBtu x 1.03 / 6.3 = 27,283.56 bbl
    assert fuel_rules.worst_case_day_oil_bbl(unit, fuel, 600.0, 24) == pytest.approx(27283.5556, abs=1e-3)
    ts_utc, ts_local = hour_at(date(2025, 1, 17), 0)
    today = date(2025, 1, 17)

    def reason(**changes):
        state = initial_state(unit, ts_utc, ts_local, 168, 600.0, 250000.0).model_copy(update=changes)
        return fuel_rules.oil_unavailable_reason(state, unit, fuel, today, 24, 600.0)

    assert reason() is None
    assert "below a worst-case day" in reason(oil_inventory_bbl=27000.0)
    # a barge due today counts; one due tomorrow does not
    assert reason(oil_inventory_bbl=27000.0, oil_barge_due=today, oil_barge_bbl=1000.0) is None
    assert reason(oil_inventory_bbl=27000.0, oil_barge_due=today + timedelta(days=1), oil_barge_bbl=1000.0) is not None
    assert reason(oil_permit_hours_used_ytd_h=696.0, oil_day=today) is None  # 696 + 24 = 720
    assert "permit hours 697 of 720" in reason(oil_permit_hours_used_ytd_h=697.0, oil_day=today)
    # hours used last year do not count against this year
    assert reason(oil_permit_hours_used_ytd_h=720.0, oil_day=date(2024, 12, 31)) is None


def test_offer_on_oil_carries_the_penalty(toy_plant):
    offer = build_offer(toy_plant.unit("U1"), date(2025, 1, 17), "oil", OIL_USD_PER_MMBTU, "hand:oil", 600.0,
                        OFFER_PRICE_DECIMALS, 1.03, "oil is cheaper")
    # 10.5 x 1.03 x 11.20 + 3 = 124.128 ; 10.8 x 1.03 x 11.20 + 3 = 127.5888
    assert [block.price_usd_per_mwh for block in offer.blocks] == [124.13, 127.59]
    assert offer.heat_input_multiplier == 1.03 and offer.fuel == "oil"
    assert offer.no_load_cost_usd_per_h == pytest.approx(4614.40)
    assert offer.start_cost_usd_by_thermal_state["cold"] == pytest.approx(82680.00)


def test_hours_on_oil_by_hand(toy_plant):
    ledger, states, inputs = run_hours(toy_plant, [(600.0, "oil"), (600.0, "oil"), (0.0, "oil")])
    entries = list(ledger.entries)
    first = {(e.line, e.quantity_unit): e for e in entries if e.ts_utc == states[0].ts_utc}
    assert first[("fuel_cost_oil", "MMBtu")].quantity == pytest.approx(6535.35)
    assert first[("fuel_cost_oil", "MMBtu")].amount_usd == -73195.92
    assert first[("no_load_cost", "MMBtu")].amount_usd == -4614.40
    assert first[("start_cost", "MMBtu")].amount_usd == -57680.00 and first[("start_cost", "starts")].amount_usd == -25000.00
    assert first[("fuel_cost_oil", "MMBtu")].ref == {
        "oil_price": "hand:oil", "oil_ratio": "fuel.oil_price_ratio_to_no2_distillate",
        "oil_penalty": "fuel.oil_heat_rate_penalty_fraction",
    }
    assert "fuel_cost_gas" not in ledger_totals_usd(ledger)
    # tank: hour 1 burns (6,535.35 + 412 + 5,150) / 6.3 = 1,920.214 bbl, hour 2 burns 1,102.754 bbl
    assert states[0].oil_inventory_bbl == pytest.approx(250000 - 1920.2143, abs=1e-3)
    assert states[1].oil_inventory_bbl == pytest.approx(250000 - 1920.2143 - 1102.7540, abs=1e-3)
    assert states[2].oil_inventory_bbl == states[1].oil_inventory_bbl
    assert [s.oil_permit_hours_used_ytd_h for s in states] == [1.0, 2.0, 2.0]
    assert [s.fuel for s in states] == ["oil", "oil", None]
    units = {"U1": toy_plant.unit("U1")}
    balance = reconcile.check_fuel_balance(states, entries, inputs, units, toy_plant.fuel, True, 168, 250000.0)
    assert balance.status == "pass" and "over 2 permit hours" in balance.detail
    assert reconcile.check_cost_identity(states, entries, inputs, units, True, 168, toy_plant.fuel).status == "pass"


def test_gas_hours_leave_the_tank_alone(toy_plant):
    ledger, states, inputs = run_hours(toy_plant, [(600.0, "gas"), (600.0, "gas")])
    assert all(s.oil_inventory_bbl == 250000.0 and s.oil_permit_hours_used_ytd_h == 0.0 for s in states)
    assert set(ledger_totals_usd(ledger)) == {"da_energy_rev", "fuel_cost_gas", "no_load_cost", "start_cost", "vom"}
    units = {"U1": toy_plant.unit("U1")}
    assert reconcile.check_fuel_balance(states, list(ledger.entries), inputs, units, toy_plant.fuel, True, 168, 250000.0).status == "pass"


def test_invariant_2_catches_tank_permit_and_fuel_line_tampering(toy_plant):
    ledger, states, inputs = run_hours(toy_plant, [(600.0, "oil"), (600.0, "oil"), (0.0, "oil")])
    entries, units = list(ledger.entries), {"U1": toy_plant.unit("U1")}

    def check(changed_states=states, changed_entries=entries, initial=250000.0):
        return reconcile.check_fuel_balance(changed_states, changed_entries, inputs, units, toy_plant.fuel, True, 168, initial).status

    assert check() == "pass"
    tank_off = [states[0], states[1].model_copy(update={"oil_inventory_bbl": states[1].oil_inventory_bbl + 1.0}), states[2]]
    assert check(changed_states=tank_off) == "fail"
    permit_off = [states[0], states[1].model_copy(update={"oil_permit_hours_used_ytd_h": 1.0}), states[2]]
    assert check(changed_states=permit_off) == "fail"
    assert check(initial=249999.0) == "fail"
    index = next(i for i, e in enumerate(entries) if e.line == "fuel_cost_oil")
    on_gas_line = entries[:index] + [entries[index].model_copy(update={"line": "fuel_cost_gas"})] + entries[index + 1:]
    assert check(changed_entries=on_gas_line) == "fail"
    less_fuel = entries[:index] + [entries[index].model_copy(update={"quantity": 6535.0, "amount_usd": -73192.00})] + entries[index + 1:]
    assert check(changed_entries=less_fuel) == "fail"


def test_the_tank_cannot_go_negative_and_the_permit_cannot_be_passed(toy_plant):
    with pytest.raises(ValueError, match="exceeds the tank"):
        run_hours(toy_plant, [(600.0, "oil")], inventory_bbl=1000.0)
    unit = toy_plant.unit("U1")
    inputs = oil_inputs(date(2025, 1, 17), 0)
    spent = initial_state(unit, inputs.ts_utc, inputs.ts_local, 168, 600.0, 250000.0).model_copy(
        update={"oil_permit_hours_used_ytd_h": 720.0, "oil_day": date(2025, 1, 17)}
    )
    with pytest.raises(ValueError, match="permit hours"):
        transition(spent, decide(inputs, 600.0), inputs, unit, commitment_costs=True, fuel=toy_plant.fuel)
    with pytest.raises(ValueError, match="needs the fuel parameters"):
        transition(spent, decide(inputs, 600.0), inputs, unit, commitment_costs=True)


def test_barge_is_ordered_below_target_and_arrives_after_the_lead_time(toy_plant):
    unit, fuel = toy_plant.unit("U1"), toy_plant.fuel
    ts_utc, ts_local = hour_at(date(2025, 1, 17), 0)
    full = initial_state(unit, ts_utc, ts_local, 168, 600.0, 250000.0)
    # at target: nothing ordered
    assert start_of_day_oil(full, date(2025, 1, 17), fuel) == (250000.0, 0.0, 0.0, None, 0.0)
    # 30,000 bbl below target: a barge for the difference, 5 days out
    low = full.model_copy(update={"oil_inventory_bbl": 220000.0, "oil_day": date(2025, 1, 17)})
    assert start_of_day_oil(low, date(2025, 1, 18), fuel) == (220000.0, 0.0, 0.0, date(2025, 1, 23), 30000.0)
    # while it is on its way nothing more is ordered, even though the tank keeps falling
    waiting = low.model_copy(update={"oil_inventory_bbl": 200000.0, "oil_barge_due": date(2025, 1, 23), "oil_barge_bbl": 30000.0})
    assert start_of_day_oil(waiting, date(2025, 1, 20), fuel) == (200000.0, 0.0, 0.0, date(2025, 1, 23), 30000.0)
    # it arrives; the tank is still 20,000 below target, so the next barge is ordered the same morning
    assert start_of_day_oil(waiting, date(2025, 1, 23), fuel) == (230000.0, 30000.0, 0.0, date(2025, 1, 28), 20000.0)
    # the permit year resets on 1 January
    spent = full.model_copy(update={"oil_permit_hours_used_ytd_h": 500.0, "oil_day": date(2024, 12, 31)})
    assert start_of_day_oil(spent, date(2025, 1, 1), fuel)[2] == 0.0


def test_barge_delivery_shows_up_in_the_state_and_the_balance(toy_plant):
    """Burn on day 1, idle for six days: the barge ordered on day 2 lands on day 7."""
    plan = [(600.0, "oil")] * 24 + [(0.0, "gas")] * (24 * 6)
    ledger, states, inputs = run_hours(toy_plant, plan)
    burned = 250000.0 - states[23].oil_inventory_bbl
    assert burned == pytest.approx((6535.35 + 412) * 24 / 6.3 + 5150 / 6.3, abs=1e-3)
    assert states[24].oil_barge_due == date(2025, 1, 23) and states[24].oil_barge_bbl == pytest.approx(burned)
    received = [(s.ts_local.date(), s.oil_received_bbl) for s in states if s.oil_received_bbl > 0]
    assert received == [(date(2025, 1, 23), pytest.approx(burned))]
    assert states[-1].oil_inventory_bbl == pytest.approx(250000.0)
    units = {"U1": toy_plant.unit("U1")}
    assert reconcile.check_fuel_balance(states, list(ledger.entries), inputs, units, toy_plant.fuel, True, 168, 250000.0).status == "pass"


# ------------------------------------------------------------------- January 2025


@pytest.fixture(scope="module")
def m4_result():
    return run(load_scenario(REPO_ROOT / "config" / "scenario.m4.yaml"), REPO_ROOT)


@pytest.fixture(scope="module")
def m3_result():
    return run(load_scenario(REPO_ROOT / "config" / "scenario.m3.yaml"), REPO_ROOT)


def test_m4_january_all_eight_invariants_pass(m4_result):
    for invariant in m4_result.meta.invariants:
        assert invariant.status == "pass", f"{invariant.invariant_id}: {invariant.detail}"
    assert set(m4_result.meta.data_snapshot_ids) == {"lbmp_da", "lbmp_rt", "gas_price", "oil_price"}


def test_m4_oil_is_chosen_only_when_it_is_cheaper_and_only_burned_on_those_days(m4_result):
    oil_days = [offer.local_date for offer in m4_result.offers if offer.fuel == "oil"]
    assert oil_days == [date(2025, 1, 17), date(2025, 1, 18), date(2025, 1, 19), date(2025, 1, 20)]
    for offer in m4_result.offers:
        assert offer.fuel_reason.startswith("oil" if offer.fuel == "oil" else "gas")
    for state, inputs in zip(m4_result.states, m4_result.hour_inputs, strict=True):
        if state.fuel == "oil":
            assert state.ts_local.date() in oil_days
            assert inputs.oil_price_usd_per_mmbtu * 1.03 < inputs.gas_price_usd_per_mmbtu
        assert 0 <= state.oil_inventory_bbl <= 1_000_000 and state.oil_permit_hours_used_ytd_h <= 720
    assert sum(1 for state in m4_result.states if state.fuel == "oil") == m4_result.states[-1].oil_permit_hours_used_ytd_h
    oil_refs = {inputs.oil_price_ref for inputs in m4_result.hour_inputs}
    assert all(e.ref["oil_price"] in oil_refs for e in m4_result.ledger if e.line == "fuel_cost_oil")


def test_m4_oil_adds_margin_over_the_gas_only_month(m4_result, m3_result):
    assert m3_result.meta.energy_margin_usd == 17171764.91  # milestone 3, unchanged
    assert m4_result.meta.energy_margin_usd > m3_result.meta.energy_margin_usd
    assert "fuel_cost_oil" in m4_result.meta.ledger_totals_usd and "fuel_cost_oil" not in m3_result.meta.ledger_totals_usd
    assert all(inputs.oil_price_usd_per_mmbtu is None for inputs in m3_result.hour_inputs)
    assert set(m3_result.meta.data_snapshot_ids) == {"lbmp_da", "lbmp_rt", "gas_price"}


def test_dual_fuel_is_refused_for_two_units_and_an_overfull_tank():
    scenario = load_scenario(REPO_ROOT / "config" / "scenario.m4.yaml")
    with pytest.raises(NotImplementedError, match="one unit"):
        run(scenario.model_copy(update={"unit_ids": ["U1", "U2"]}), REPO_ROOT)
    with pytest.raises(ValueError, match="exceeds the tank capacity"):
        run(scenario.model_copy(update={"initial_oil_inventory_bbl": 2_000_000.0}), REPO_ROOT)


def test_an_empty_tank_keeps_the_plant_on_gas(m4_result):
    scenario = load_scenario(REPO_ROOT / "config" / "scenario.m4.yaml")
    dry = run(scenario.model_copy(update={"initial_oil_inventory_bbl": 0.0}), REPO_ROOT)
    assert all(invariant.status == "pass" for invariant in dry.meta.invariants)
    # the barge ordered on 1 January lands on the 6th, well before oil is wanted
    assert [offer.fuel for offer in dry.offers].count("oil") == 4
    never = run(scenario.model_copy(update={"initial_oil_inventory_bbl": 0.0, "end_date": date(2025, 1, 4)}), REPO_ROOT)
    assert all(offer.fuel == "gas" for offer in never.offers)
    assert energy_margin_usd(never.meta.ledger_totals_usd) == never.meta.energy_margin_usd
