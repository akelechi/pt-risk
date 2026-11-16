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
    decisions = commitment.solve(prices, state, unit, offer)
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
