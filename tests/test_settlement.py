"""transition() and DA settlement on the hand-worked day.

Every expected dollar below was worked by hand; tests/fixtures/m1_hand_day.xlsx holds the
same arithmetic as spreadsheet formulas (open it to check).

  450 MW hour at 45.50:  revenue 450 x 45.50 = 20,475.00
                         fuel    4,725 MMBtu x 4.00 = 18,900.00
                         VOM     450 x 3.00 = 1,350.00          margin    225.00
  600 MW hour at 50.00:  revenue 600 x 50.00 = 30,000.00
                         fuel    6,345 MMBtu x 4.00 = 25,380.00
                         VOM     600 x 3.00 = 1,800.00          margin  2,820.00
  day: 8 h at 450 MW + 4 h at 600 MW; fuel 8 x 4,725 + 4 x 6,345 = 63,180 MMBtu
       revenue 283,800.00  fuel 252,720.00  VOM 18,000.00       margin 13,080.00
"""

from __future__ import annotations

import pytest

from engine.contracts import Decision
from engine.ledger import reconcile
from engine.ledger.ledger import Ledger
from engine.market import settlement
from engine.market.offer import build_offer
from engine.plant import commitment
from engine.plant.state import initial_state, transition
from engine.run import energy_margin_usd, ledger_totals_usd
from tests.conftest import HAND_DAY, HAND_GAS_USD_PER_MMBTU, OFFER_PRICE_DECIMALS, day_prices, hour_inputs_for


def run_hand_day(unit, lbmps, hours_offline_h: int = 168):
    prices = day_prices("U1", lbmps)
    offer = build_offer(unit, HAND_DAY, "gas", HAND_GAS_USD_PER_MMBTU, "hand:gas", 600.0, OFFER_PRICE_DECIMALS)
    state = initial_state(unit, prices.hours[0].ts_utc, prices.hours[0].ts_local, hours_offline_h)
    decisions = commitment.solve([(prices, offer)], state, unit)
    ledger, states, inputs = Ledger(), [], []
    for hour, decision in zip(prices.hours, decisions, strict=True):
        hour_inputs = hour_inputs_for(hour, "U1", 600.0)
        state, entries = transition(state, decision, hour_inputs, unit)
        ledger.append(entries)
        states.append(state)
        inputs.append(hour_inputs)
    return ledger, states, inputs, decisions


def amounts(entries, ts_utc) -> dict[str, float]:
    return {entry.line: entry.amount_usd for entry in entries if entry.ts_utc == ts_utc}


def test_da_revenue_formula():
    assert settlement.da_energy_mwh(450.0) == 450.0
    assert settlement.da_energy_revenue_usd(450.0, 45.50) == 20475.00
    assert settlement.da_energy_revenue_usd(0.0, 45.50) == 0.0


def test_hand_day_hour_by_hour(toy_unit, hand_lbmps):
    ledger, states, _, _ = run_hand_day(toy_unit, hand_lbmps)
    at_450, at_600, idle = states[8], states[16], states[0]

    assert amounts(ledger.entries, at_450.ts_utc) == {"da_energy_rev": 20475.00, "fuel_cost_gas": -18900.00, "vom": -1350.00}
    assert amounts(ledger.entries, at_600.ts_utc) == {"da_energy_rev": 30000.00, "fuel_cost_gas": -25380.00, "vom": -1800.00}
    assert amounts(ledger.entries, idle.ts_utc) == {}
    assert amounts(ledger.entries, states[6].ts_utc) == {}  # LBMP ties the offer: no run, nothing booked

    fuel = next(e for e in ledger.entries if e.ts_utc == at_450.ts_utc and e.line == "fuel_cost_gas")
    assert (fuel.quantity, fuel.quantity_unit, fuel.price, fuel.price_unit) == (pytest.approx(4725.0), "MMBtu", 4.00, "USD/MMBtu")
    assert fuel.ref == {"gas_price": "hand:gas", "gas_basis": "fuel.gas_basis_adder_usd_per_mmbtu_by_month"}
    revenue = next(e for e in ledger.entries if e.ts_utc == at_450.ts_utc and e.line == "da_energy_rev")
    assert (revenue.quantity, revenue.quantity_unit, revenue.price) == (450.0, "MWh", 45.50)
    assert revenue.ref == {"lbmp_da": "hand:lbmp:8"}


def test_hand_day_totals(toy_unit, hand_lbmps):
    ledger, states, _, _ = run_hand_day(toy_unit, hand_lbmps)
    assert len(ledger) == 12 * 3
    totals = ledger_totals_usd(ledger)
    assert totals == {"da_energy_rev": 283800.00, "fuel_cost_gas": -252720.00, "vom": -18000.00}
    assert energy_margin_usd(totals) == 13080.00
    assert sum(state.output_mw for state in states) == 8 * 450 + 4 * 600
    assert {r.period: r.amount_usd for r in ledger.rollup("day") if r.line == "da_energy_rev"} == {"2025-01-15": 283800.00}


def test_hand_day_states(toy_unit, hand_lbmps):
    _, states, _, _ = run_hand_day(toy_unit, hand_lbmps, hours_offline_h=168)
    assert [state.committed for state in states] == [False] * 8 + [True] * 12 + [False] * 4
    # off: 168 before the run, so 169..176; on: 1..12; off again: 1..4
    assert [state.hours_in_state_h for state in states] == list(range(169, 177)) + list(range(1, 13)) + [1, 2, 3, 4]
    assert [state.thermal_state for state in states] == ["cold"] * 8 + ["hot"] * 12 + ["hot"] * 4
    assert all(state.fuel == ("gas" if state.committed else None) for state in states)
    assert all(state.da_schedule_mw == state.output_mw <= state.available_mw == 600.0 for state in states)
    assert all(state.oil_inventory_bbl == 0 and state.oil_permit_hours_used_ytd_h == 0 for state in states)


def test_transition_is_pure(toy_unit, hand_lbmps):
    prices = day_prices("U1", hand_lbmps)
    hour = prices.hours[8]
    state = initial_state(toy_unit, prices.hours[0].ts_utc, prices.hours[0].ts_local, 168)
    decision = Decision(ts_utc=hour.ts_utc, ts_local=hour.ts_local, unit_id="U1", commit=True, target_mw=450.0, fuel="gas", reason="test")
    before = state.model_copy(deep=True)
    first = transition(state, decision, hour_inputs_for(hour, "U1", 600.0), toy_unit)
    second = transition(state, decision, hour_inputs_for(hour, "U1", 600.0), toy_unit)
    assert first == second
    assert state == before  # the input state is not mutated


def test_transition_guard_rails(toy_unit, hand_lbmps):
    prices = day_prices("U1", hand_lbmps)
    hour, other = prices.hours[8], prices.hours[9]
    state = initial_state(toy_unit, prices.hours[0].ts_utc, prices.hours[0].ts_local, 168)
    inputs = hour_inputs_for(hour, "U1", 600.0)

    def decide(**overrides) -> Decision:
        base = dict(ts_utc=hour.ts_utc, ts_local=hour.ts_local, unit_id="U1", commit=True, target_mw=450.0, fuel="gas", reason="test")
        return Decision(**{**base, **overrides})

    with pytest.raises(ValueError, match="exceeds available"):
        transition(state, decide(target_mw=450.0), hour_inputs_for(hour, "U1", 400.0), toy_unit)
    with pytest.raises(ValueError, match="commit must be true exactly"):
        transition(state, decide(commit=False, target_mw=450.0), inputs, toy_unit)
    with pytest.raises(ValueError, match="commit must be true exactly"):
        transition(state, decide(commit=True, target_mw=0.0), inputs, toy_unit)
    with pytest.raises(ValueError, match="different hours"):
        transition(state, decide(ts_utc=other.ts_utc, ts_local=other.ts_local), inputs, toy_unit)
    with pytest.raises(ValueError, match="same unit"):
        transition(state, decide(unit_id="U2"), inputs, toy_unit)
    with pytest.raises(NotImplementedError, match="milestone 4"):
        transition(state, decide(fuel="oil"), inputs, toy_unit)


def test_invariants_3_and_4_pass_on_the_hand_day_and_catch_tampering(toy_unit, hand_lbmps):
    ledger, states, inputs, _ = run_hand_day(toy_unit, hand_lbmps)
    entries = list(ledger.entries)
    units = {"U1": toy_unit}
    cost_ok = reconcile.check_cost_identity(states, entries, inputs, units)
    revenue_ok = reconcile.check_revenue_identity(states, entries, inputs)
    assert cost_ok.status == "pass" and "252,720.00" in cost_ok.detail and "63,180.0 MMBtu" in cost_ok.detail
    assert revenue_ok.status == "pass" and "283,800.00" in revenue_ok.detail and "6,000.0 MWh" in revenue_ok.detail

    def tampered(line: str, **changes):
        index = next(i for i, e in enumerate(entries) if e.line == line)
        return entries[:index] + [entries[index].model_copy(update=changes)] + entries[index + 1 :]

    # one cent off on one hour's fuel cost
    assert reconcile.check_cost_identity(states, tampered("fuel_cost_gas", amount_usd=-18900.01), inputs, units).status == "fail"
    assert reconcile.check_revenue_identity(states, tampered("da_energy_rev", amount_usd=20475.01), inputs).status == "fail"
    # an entry dropped, and an entry booked in an idle hour
    missing_fuel = [e for e in entries if not (e.line == "fuel_cost_gas" and e.ts_utc == states[8].ts_utc)]
    assert reconcile.check_cost_identity(states, missing_fuel, inputs, units).status == "fail"
    stray = entries + [entries[0].model_copy(update={"ts_utc": states[0].ts_utc, "ts_local": states[0].ts_local})]
    assert reconcile.check_revenue_identity(states, stray, inputs).status == "fail"
    # a state whose output no longer matches what was booked
    moved = [states[8].model_copy(update={"output_mw": 300.0, "da_schedule_mw": 300.0})] + states[:8] + states[9:]
    assert reconcile.check_cost_identity(moved, entries, inputs, units).status == "fail"
    assert reconcile.check_revenue_identity(moved, entries, inputs).status == "fail"


# ------------------------------------------------------------- milestone 2
# Hand day (tests/fixtures/m2_hand_day.xlsx): 6 h at 40, 4 h at 60, 6 h at 44, 6 h at 70, 2 h at 40.
#   on at 600 MW: fuel 6,345 MMBtu x 4 = 25,380; no-load 400 x 4 = 1,600; VOM 1,800
#   on at 450 MW: fuel 4,725 x 4 = 18,900; no-load 1,600; VOM 1,350
#   on at 150 MW: fuel 1,710 x 4 = 6,840; no-load 1,600; VOM 450
#   cold start 5,000 MMBtu x 4 + 25,000 = 45,000; hot start 1,500 x 4 + 8,000 = 14,000
# Plan A (DP), on 6-21: revenue 4 x 36,000 + 6 x 19,800 + 6 x 42,000 = 514,800
#   fuel 10 x 25,380 + 6 x 18,900 = 367,200; no-load 16 x 1,600 = 25,600; VOM 26,100; start 45,000
#   energy margin 50,900
# Plan B (price-taker made feasible), on 6-13 and 20-23:
#   block 6-13: revenue 223,200; costs 115,120 + 87,400 + 45,000 = 247,520 -> uplift 24,320
#   block 20-23: 2 x 13,220 - 2 x 2,890 - 14,000 = 6,660 (still on at midnight: no uplift yet)
#   energy margin -24,320 + 6,660 = -17,660

from tests.conftest import run_day  # noqa: E402


def test_m2_hand_day_dp_ledger(toy_unit, m2_lbmps):
    ledger, states, inputs, _ = run_day(toy_unit, m2_lbmps, "dp")
    totals = ledger_totals_usd(ledger)
    assert totals == {
        "da_energy_rev": 514800.00, "fuel_cost_gas": -367200.00, "no_load_cost": -25600.00,
        "start_cost": -45000.00, "vom": -26100.00,
    }
    assert energy_margin_usd(totals) == 50900.00
    start_entries = [e for e in ledger.entries if e.line == "start_cost"]
    assert [(e.quantity, e.quantity_unit, e.price, e.amount_usd) for e in start_entries] == [
        (5000.0, "MMBtu", 4.00, -20000.00), (1.0, "starts", 25000.0, -25000.00),
    ]
    assert all(e.ts_utc == states[6].ts_utc for e in start_entries)
    assert start_entries[1].ref == {"param": "units.U1.start.cold", "hours_offline_h": "174"}
    assert amounts(ledger.entries, states[10].ts_utc) == {
        "da_energy_rev": 19800.00, "fuel_cost_gas": -18900.00, "vom": -1350.00, "no_load_cost": -1600.00,
    }
    assert [s.hours_in_state_h for s in states[5:8]] == [174, 1, 2] and states[22].hours_in_state_h == 1
    assert [s.thermal_state for s in states[20:]] == ["hot"] * 4
    # block totals run while on and clear when off
    assert states[21].commitment_block_cost_usd == 463900.00 and states[21].commitment_block_da_revenue_usd == 514800.00
    assert states[22].commitment_block_cost_usd == 0.0 and states[22].commitment_block_da_revenue_usd == 0.0
    assert reconcile.check_cost_identity(states, list(ledger.entries), inputs, {"U1": toy_unit}, True, 168).status == "pass"
    assert reconcile.check_revenue_identity(states, list(ledger.entries), inputs).status == "pass"


def test_m2_hand_day_price_taker_with_constraints_books_uplift(toy_unit, m2_lbmps):
    ledger, states, inputs, _ = run_day(toy_unit, m2_lbmps, "price_taker_constrained")
    totals = ledger_totals_usd(ledger)
    assert energy_margin_usd(totals) == -17660.00
    assert totals["start_cost"] == -59000.00 and totals["uplift"] == 24320.00
    uplift = [e for e in ledger.entries if e.line == "uplift"]
    assert len(uplift) == 1 and uplift[0].ts_utc == states[14].ts_utc  # first hour after the block
    assert uplift[0].ref["block_cost_usd"] == "247520.00" and uplift[0].ref["block_da_revenue_usd"] == "223200.00"
    assert uplift[0].ref["block_hours_on_h"] == "8"
    assert reconcile.check_cost_identity(states, list(ledger.entries), inputs, {"U1": toy_unit}, True, 168).status == "pass"


def test_price_taker_baseline_books_no_start_no_load_or_uplift(toy_unit, m2_lbmps):
    ledger, _, _, _ = run_day(toy_unit, m2_lbmps, "price_taker")
    assert set(ledger_totals_usd(ledger)) == {"da_energy_rev", "fuel_cost_gas", "vom"}


def test_invariant_3_catches_start_and_no_load_tampering(toy_unit, m2_lbmps):
    ledger, states, inputs, _ = run_day(toy_unit, m2_lbmps, "dp")
    entries, units = list(ledger.entries), {"U1": toy_unit}

    def check(changed):
        return reconcile.check_cost_identity(states, changed, inputs, units, True, 168).status

    without_other_start = [e for e in entries if not (e.line == "start_cost" and e.quantity_unit == "starts")]
    assert check(without_other_start) == "fail"
    no_load_index = next(i for i, e in enumerate(entries) if e.line == "no_load_cost")
    one_cent = entries[:no_load_index] + [entries[no_load_index].model_copy(update={"amount_usd": -1600.01})] + entries[no_load_index + 1:]
    assert check(one_cent) == "fail"
    # the same ledger read as if the unit had been off only 5 h before the start: a hot
    # start would have been the right size, so the booked cold start no longer matches
    warm_history = states[:5] + [states[5].model_copy(update={"hours_in_state_h": 5})] + states[6:]
    assert reconcile.check_cost_identity(warm_history, entries, inputs, units, True, 168).status == "fail"
    # and read without commitment costs, the no-load and start lines are unexplained
    assert reconcile.check_cost_identity(states, entries, inputs, units, False, 168).status == "fail"


def test_invariant_5_fails_when_the_ordering_breaks():
    from datetime import date

    from engine.contracts import CommitmentBound

    def bound(dp_value, constrained, unconstrained):
        return CommitmentBound(unit_id="U1", local_date=date(2025, 1, 15), horizon_hours=24, dp_value_usd=dp_value,
                               price_taker_constrained_value_usd=constrained, unconstrained_value_usd=unconstrained)

    assert reconcile.check_margin_bound([bound(50900.0, -17660.0, 124200.0)]).status == "pass"
    assert reconcile.check_margin_bound([bound(50900.0, 50900.02, 124200.0)]).status == "fail"
    assert reconcile.check_margin_bound([bound(124200.02, -17660.0, 124200.0)]).status == "fail"
    assert reconcile.check_margin_bound([]).status == "fail"


# ------------------------------------------------------------- milestone 3
# The milestone 2 hand day under the DP plan (on 6-21), with a forced outage in hours 16
# and 17. RT LBMP is 90 in hour 16 and 50 in hour 17 (80 elsewhere, unused).
#   hours 16-17: DA schedule 600 MW stands: DA revenue 42,000 each
#                nothing delivered: RT balancing -600 x 90 = -54,000 and -600 x 50 = -30,000
#                no fuel, no-load or VOM
#   hour 18:     back on after 2 h off: hot start 1,500 x 4 + 8,000 = 14,000
#   day energy margin = 50,900 (no outage) + 2 x 28,780 (costs not incurred) - 84,000 - 14,000 = 10,460
#   the block cut short at hour 16 had cost 291,220 against DA revenue 262,800; it is not
#   made whole, because the unit's own outage ended it

M3_RT = [80.0] * 16 + [90.0, 50.0] + [80.0] * 6
M3_OUT = frozenset({16, 17})


def test_actual_output_follows_what_is_available(toy_unit):
    from engine.plant.state import actual_output_mw

    assert actual_output_mw(450.0, 600.0, toy_unit) == 450.0
    assert actual_output_mw(600.0, 300.0, toy_unit) == 300.0  # derated but above Pmin
    assert actual_output_mw(600.0, 100.0, toy_unit) == 0.0  # less than Pmin: cannot run
    assert actual_output_mw(600.0, 0.0, toy_unit) == 0.0
    assert settlement.rt_deviation_mwh(0.0, 600.0) == -600.0
    assert settlement.rt_balancing_usd(0.0, 600.0, 90.0) == -54000.0
    assert settlement.rt_balancing_usd(600.0, 600.0, 90.0) == 0.0


def test_m3_hand_day_outage_is_bought_back_at_rt(toy_unit, m2_lbmps):
    ledger, states, inputs, decisions = run_day(toy_unit, m2_lbmps, "dp", rt_lbmps=M3_RT, outage_hours=M3_OUT)
    entries = list(ledger.entries)
    assert amounts(entries, states[16].ts_utc) == {"da_energy_rev": 42000.00, "rt_balancing": -54000.00}
    assert amounts(entries, states[17].ts_utc) == {"da_energy_rev": 42000.00, "rt_balancing": -30000.00}
    rt = [e for e in entries if e.line == "rt_balancing"]
    assert [(e.quantity, e.price) for e in rt] == [(-600.0, 90.0), (-600.0, 50.0)]
    assert rt[0].ref == {"lbmp_rt": "hand:rt", "cause": "forced outage"}
    # the plan still says on; the state says what happened
    assert decisions[16].commit and decisions[16].target_mw == 600.0
    assert (states[16].committed, states[16].output_mw, states[16].da_schedule_mw, states[16].available_mw) == (False, 0.0, 600.0, 0.0)
    assert [s.hours_in_state_h for s in states[15:19]] == [10, 1, 2, 1]
    assert sum(e.amount_usd for e in entries if e.line == "start_cost" and e.ts_utc == states[18].ts_utc) == -14000.00
    totals = ledger_totals_usd(ledger)
    assert totals["rt_balancing"] == -84000.00 and totals["start_cost"] == -59000.00
    assert "uplift" not in totals
    assert energy_margin_usd(totals) == 10460.00
    units = {"U1": toy_unit}
    balance = reconcile.check_energy_balance(states, entries, inputs)
    assert balance.status == "pass" and "deviation -1,200.0 over 2 hours" in balance.detail
    assert reconcile.check_revenue_identity(states, entries, inputs).status == "pass"
    assert reconcile.check_cost_identity(states, entries, inputs, units, True, 168).status == "pass"


def test_invariants_1_and_4_catch_rt_tampering(toy_unit, m2_lbmps):
    ledger, states, inputs, _ = run_day(toy_unit, m2_lbmps, "dp", rt_lbmps=M3_RT, outage_hours=M3_OUT)
    entries = list(ledger.entries)
    index = next(i for i, e in enumerate(entries) if e.line == "rt_balancing")

    def both(changed):
        return (reconcile.check_energy_balance(states, changed, inputs).status,
                reconcile.check_revenue_identity(states, changed, inputs).status)

    one_cent = entries[:index] + [entries[index].model_copy(update={"amount_usd": -54000.01})] + entries[index + 1:]
    assert both(one_cent) == ("fail", "fail")
    dropped = entries[:index] + entries[index + 1:]
    assert both(dropped) == ("fail", "fail")
    stray = entries + [entries[index].model_copy(update={"ts_utc": states[8].ts_utc, "ts_local": states[8].ts_local})]
    assert both(stray) == ("fail", "fail")
    # a state that claims it delivered while the ledger bought everything back
    delivered = states[:16] + [states[16].model_copy(update={"output_mw": 600.0})] + states[17:]
    assert reconcile.check_energy_balance(delivered, entries, inputs).status == "fail"


def test_a_deviation_cannot_be_settled_without_an_rt_price(toy_unit, m2_lbmps):
    with pytest.raises(ValueError, match="needs an RT LBMP"):
        run_day(toy_unit, m2_lbmps, "dp", outage_hours=M3_OUT)


def test_no_outage_means_no_rt_entries(toy_unit, m2_lbmps):
    ledger, states, inputs, _ = run_day(toy_unit, m2_lbmps, "dp", rt_lbmps=M3_RT)
    assert "rt_balancing" not in ledger_totals_usd(ledger)
    assert energy_margin_usd(ledger_totals_usd(ledger)) == 50900.00
    assert reconcile.check_energy_balance(states, list(ledger.entries), inputs).status == "pass"


def test_price_taker_with_limits_block_ended_by_outage_gets_no_uplift(toy_unit, m2_lbmps):
    """Plan B's first block (6-13) loses 24,320 and is made whole when it ends by plan;
    if an outage ends it instead, it is not."""
    ledger, _, _, _ = run_day(toy_unit, m2_lbmps, "price_taker_constrained", rt_lbmps=M3_RT, outage_hours=frozenset({12, 13}))
    assert "uplift" not in ledger_totals_usd(ledger)
