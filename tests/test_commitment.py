"""Offer building and the price-taker solver, on the hand-worked day."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from engine.contracts import Offer, OfferBlock
from engine.market.offer import build_offer, cleared_mw
from engine.plant import commitment
from engine.plant.state import initial_state
from tests.conftest import HAND_DAY, HAND_GAS_USD_PER_MMBTU, OFFER_PRICE_DECIMALS, day_prices

# hours 0-5 at 40.00, 6-7 at 45.00 (a tie with the first step), 8-15 at 45.50, 16-19 at 50.00, 20-23 at 40.00
HAND_MW = [0.0] * 6 + [0.0] * 2 + [450.0] * 8 + [600.0] * 4 + [0.0] * 4


def toy_offer(unit, available_mw: float = 600.0, gas: float = HAND_GAS_USD_PER_MMBTU) -> Offer:
    return build_offer(unit, HAND_DAY, "gas", gas, "hand:gas", available_mw, OFFER_PRICE_DECIMALS)


def test_offer_is_the_convexified_step_curve(toy_unit):
    offer = toy_offer(toy_unit)
    assert [(b.mw_from, b.mw_to, b.price_usd_per_mwh) for b in offer.blocks] == [(0.0, 450, 45.00), (450, 600, 46.20)]
    assert offer.fuel == "gas" and offer.fuel_price_usd_per_mmbtu == 4.00 and offer.fuel_price_ref == "hand:gas"


def test_offer_stops_at_available_mw(toy_unit, real_unit):
    derated = toy_offer(toy_unit, available_mw=540.0)
    assert [(b.mw_from, b.mw_to) for b in derated.blocks] == [(0.0, 450), (450, 540.0)]
    real = build_offer(real_unit, HAND_DAY, "gas", 4.00, "hand:gas", 553.32, OFFER_PRICE_DECIMALS)
    assert real.blocks[-1].mw_to == 553.32 and real.blocks[0].mw_from == 0.0
    prices = [block.price_usd_per_mwh for block in real.blocks]
    assert prices == sorted(prices)
    assert toy_offer(toy_unit, available_mw=0.0).blocks == []


def test_offer_prices_scale_with_gas_and_are_rounded_to_the_cent(toy_unit):
    offer = toy_offer(toy_unit, gas=3.333)  # 10.5 x 3.333 + 3 = 37.9965 -> 38.00 ; 10.8 x 3.333 + 3 = 38.9964 -> 39.00
    assert [block.price_usd_per_mwh for block in offer.blocks] == [38.00, 39.00]


def test_offer_contract_rejects_gaps_and_decreasing_prices():
    block = dict(incremental_heat_rate_mmbtu_per_mwh=10.0)
    base = dict(unit_id="U1", local_date=HAND_DAY, fuel="gas", fuel_price_usd_per_mmbtu=4.0, fuel_price_ref="x", available_mw=600)
    with pytest.raises(ValidationError, match="contiguous"):
        Offer(**base, blocks=[OfferBlock(mw_from=10, mw_to=450, price_usd_per_mwh=45, **block)])
    with pytest.raises(ValidationError, match="non-decreasing"):
        Offer(**base, blocks=[OfferBlock(mw_from=0, mw_to=450, price_usd_per_mwh=45, **block),
                              OfferBlock(mw_from=450, mw_to=600, price_usd_per_mwh=44, **block)])
    with pytest.raises(ValidationError, match="exceeds available_mw"):
        Offer(**{**base, "available_mw": 500}, blocks=[OfferBlock(mw_from=0, mw_to=600, price_usd_per_mwh=45, **block)])


@pytest.mark.parametrize("lbmp,mw,steps", [(40.00, 0.0, 0), (45.00, 0.0, 0), (45.01, 450.0, 1), (46.20, 450.0, 1), (46.21, 600.0, 2), (-5.0, 0.0, 0)])
def test_a_step_clears_only_strictly_above_its_offer_price(toy_unit, lbmp, mw, steps):
    assert cleared_mw(toy_offer(toy_unit), lbmp) == (mw, steps)


def test_price_taker_on_the_hand_day(toy_unit, hand_lbmps):
    prices = day_prices("U1", hand_lbmps)
    state0 = initial_state(toy_unit, prices.hours[0].ts_utc, prices.hours[0].ts_local, 168)
    decisions = commitment.solve([(prices, toy_offer(toy_unit))], state0, toy_unit)
    assert [decision.target_mw for decision in decisions] == HAND_MW
    assert [decision.commit for decision in decisions] == [mw > 0 for mw in HAND_MW]
    assert all(decision.fuel == "gas" and decision.unit_id == "U1" for decision in decisions)
    assert [decision.ts_utc for decision in decisions] == [hour.ts_utc for hour in prices.hours]
    assert decisions[0].reason == "DA LBMP 40.00 <= lowest offer 45.00 $/MWh: off"
    assert decisions[6].reason == "DA LBMP 45.00 <= lowest offer 45.00 $/MWh: off"
    assert decisions[8].reason == "DA LBMP 45.50 > offer 45.00 $/MWh on 1 of 2 steps: 450.0 MW"
    assert decisions[16].reason == "DA LBMP 50.00 > offer 46.20 $/MWh on 2 of 2 steps: 600.0 MW"


def test_price_taker_has_no_memory(toy_unit, hand_lbmps):
    """The baseline ignores state: cold or just-stopped, the decisions are identical."""
    prices = day_prices("U1", hand_lbmps)
    offer = toy_offer(toy_unit)
    cold = initial_state(toy_unit, prices.hours[0].ts_utc, prices.hours[0].ts_local, 168)
    hot = initial_state(toy_unit, prices.hours[0].ts_utc, prices.hours[0].ts_local, 1)
    assert commitment.price_taker([(prices, offer)], cold, toy_unit) == commitment.price_taker([(prices, offer)], hot, toy_unit)


def test_solver_refuses_mismatched_inputs_and_unknown_solvers(toy_unit, hand_lbmps):
    prices = day_prices("U1", hand_lbmps)
    state0 = initial_state(toy_unit, prices.hours[0].ts_utc, prices.hours[0].ts_local, 168)
    with pytest.raises(ValueError, match="unknown commitment solver"):
        commitment.solve([(prices, toy_offer(toy_unit))], state0, toy_unit, solver="simplex")
    other_day = build_offer(toy_unit, date(2025, 1, 16), "gas", 4.0, "hand:gas", 600.0, OFFER_PRICE_DECIMALS)
    with pytest.raises(ValueError, match="same unit and day"):
        commitment.solve([(prices, other_day)], state0, toy_unit)
    with pytest.raises(ValueError, match="belong to the unit"):
        commitment.solve([(day_prices("U2", hand_lbmps), toy_offer(toy_unit))], state0, toy_unit)


# ------------------------------------------------------------- milestone 2: DP

import itertools  # noqa: E402
import random  # noqa: E402

from engine.plant.params import parse_plant  # noqa: E402
from tests.conftest import run_day, toy_offer_for, toy_plant_raw  # noqa: E402

PLAN_A_ON = [False] * 6 + [True] * 16 + [False] * 2  # DP optimum on the milestone 2 hand day
PLAN_B_ON = [False] * 6 + [True] * 8 + [False] * 6 + [True] * 4  # price-taker made feasible


def hand_horizon(unit, lbmps):
    return commitment.horizon_hours([(day_prices(unit.id, lbmps), toy_offer_for(unit))])


def test_three_part_offer_of_the_toy_unit(toy_unit):
    offer = toy_offer_for(toy_unit)
    assert offer.min_gen_mw == 150
    # blocks above Pmin: 10.1 then 10.0 pool to 10.05 -> 10.05 x 4 + 3 = 43.20 ; 10.8 x 4 + 3 = 46.20
    assert [(b.mw_from, b.mw_to, b.price_usd_per_mwh) for b in offer.blocks_above_min_gen] == [(150, 450, 43.20), (450, 600, 46.20)]
    assert offer.no_load_cost_usd_per_h == 1600.0
    assert offer.start_cost_usd_by_thermal_state == {"hot": 14000.0, "warm": 27000.0, "cold": 45000.0}
    below_pmin = toy_offer_for(toy_unit, available_mw=100.0)
    assert below_pmin.blocks == [] and below_pmin.blocks_above_min_gen == [] and below_pmin.min_gen_mw == 0.0


@pytest.mark.parametrize("lbmp,mw", [(40.00, 150), (43.20, 150), (43.21, 450), (46.20, 450), (46.21, 600)])
def test_committed_dispatch_is_pmin_plus_steps_strictly_in_the_money(toy_unit, lbmp, mw):
    from engine.market.offer import committed_dispatch_mw

    assert committed_dispatch_mw(toy_offer_for(toy_unit), lbmp) == mw


@pytest.mark.parametrize("lbmp,mw,margin", [(60.0, 600, 7220.0), (44.0, 450, -2050.0), (70.0, 600, 13220.0), (40.0, 150, -2890.0)])
def test_hour_margin_with_no_load_by_hand(toy_unit, lbmp, mw, margin):
    """e.g. 600 MW at 60: 36,000 - (6,345 + 400) x 4 - 1,800 = 7,220."""
    assert commitment.hour_margin_usd(toy_unit, toy_offer_for(toy_unit), lbmp, mw, no_load=True) == pytest.approx(margin)


def test_dp_on_the_hand_day_rides_through_the_dip(toy_unit, m2_lbmps):
    hours = hand_horizon(toy_unit, m2_lbmps)
    flags, value = commitment.dp_plan(toy_unit, hours, False, 168)
    assert flags == PLAN_A_ON
    # 4 x 7,220 + 6 x (-2,050) + 6 x 13,220 - 45,000 (cold start) = 50,900
    assert value == pytest.approx(50900.0)
    assert commitment.plan_value_usd(toy_unit, hours, False, 168, flags) == pytest.approx(50900.0)


def test_price_taker_with_constraints_on_the_hand_day_cycles(toy_unit, m2_lbmps):
    hours = hand_horizon(toy_unit, m2_lbmps)
    flags = commitment.price_taker_constrained_plan(toy_unit, hours, False, 168)
    assert flags == PLAN_B_ON  # held on 10-13 by minimum up, held off 16-19 by minimum down
    # (28,880 - 8,200 - 45,000) + (2 x 13,220 - 2 x 2,890 - 14,000 hot start) = -17,660
    assert commitment.plan_value_usd(toy_unit, hours, False, 168, flags) == pytest.approx(-17660.0)


def test_margin_bound_on_the_hand_day(toy_unit, m2_lbmps):
    prices = day_prices("U1", m2_lbmps)
    state0 = initial_state(toy_unit, prices.hours[0].ts_utc, prices.hours[0].ts_local, 168)
    bound = commitment.margin_bound(toy_unit, [(prices, toy_offer_for(toy_unit))], state0)
    assert bound.price_taker_constrained_value_usd == pytest.approx(-17660.0)
    assert bound.dp_value_usd == pytest.approx(50900.0)
    # no no-load: 4 x 8,820 (at 60) + 6 x 14,820 (at 70); 44 and 40 never pay -> 124,200
    assert bound.unconstrained_value_usd == pytest.approx(124200.0)
    assert bound.horizon_hours == 24


def test_plan_value_rejects_infeasible_plans(toy_unit, m2_lbmps):
    hours = hand_horizon(toy_unit, m2_lbmps)
    with pytest.raises(ValueError, match="minimum up"):
        commitment.plan_value_usd(toy_unit, hours, False, 168, [False] * 6 + [True] * 3 + [False] * 15)
    with pytest.raises(ValueError, match="minimum down"):
        commitment.plan_value_usd(toy_unit, hours, False, 2, [True] * 24)
    assert commitment.plan_value_usd(toy_unit, hours, False, 168, [False] * 24) == 0.0


def small_unit(min_up: int, min_down: int):
    """Toy unit with short run-time limits and thresholds, so short horizons exercise them."""
    raw = toy_plant_raw()
    unit = raw["units"][0]
    unit["min_up_hours"]["value"] = min_up
    unit["min_down_hours"]["value"] = min_down
    unit["start"]["hot"]["value"]["hours_offline_max_h"] = 2
    unit["start"]["warm"]["value"]["hours_offline_max_h"] = 4
    return parse_plant(raw).unit("U1")


@pytest.mark.parametrize("seed", range(12))
def test_dp_equals_exhaustive_search_on_short_horizons(seed):
    """Every feasible on/off plan of a 10-hour horizon is enumerated; the DP must match the best."""
    rng = random.Random(seed)
    unit = small_unit(min_up=rng.choice([1, 2, 3]), min_down=rng.choice([1, 2, 3]))
    lbmps = [round(rng.uniform(30, 75), 2) for _ in range(24)]
    hours = hand_horizon(unit, lbmps)[:10]
    on0, hours0 = rng.choice([(False, 1), (False, 3), (False, 9), (True, 1), (True, 5)])
    best = float("-inf")
    for plan in itertools.product([False, True], repeat=len(hours)):
        try:
            best = max(best, commitment.plan_value_usd(unit, hours, on0, hours0, plan))
        except ValueError:
            continue
    flags, value = commitment.dp_plan(unit, hours, on0, hours0)
    assert value == pytest.approx(best, abs=1e-6)
    assert commitment.plan_value_usd(unit, hours, on0, hours0, flags) == pytest.approx(best, abs=1e-6)


@pytest.mark.parametrize("seed", range(20))
def test_bounds_hold_on_random_days(toy_unit, seed):
    rng = random.Random(1000 + seed)
    lbmps = [round(rng.uniform(20, 90), 2) for _ in range(24)]
    prices = day_prices("U1", lbmps)
    hours_off = rng.choice([1, 5, 6, 12, 13, 72, 73, 168])
    state0 = initial_state(toy_unit, prices.hours[0].ts_utc, prices.hours[0].ts_local, hours_off)
    bound = commitment.margin_bound(toy_unit, [(prices, toy_offer_for(toy_unit))], state0)
    assert bound.price_taker_constrained_value_usd <= bound.dp_value_usd + 1e-6
    assert bound.dp_value_usd <= bound.unconstrained_value_usd + 1e-6


def test_dp_does_not_start_or_stop_on_a_tie(toy_unit):
    """A start that exactly breaks even is not taken; staying on at exactly zero is kept."""
    offer = toy_offer_for(toy_unit)
    breakeven = 28780 / 600  # hour margin 0 at 600 MW
    hours = commitment.horizon_hours([(day_prices("U1", [breakeven] * 24), offer)])
    assert commitment.dp_plan(toy_unit, hours, False, 168)[0] == [False] * 24
    assert commitment.dp_plan(toy_unit, hours, True, 8)[0] == [True] * 24


def test_dp_decisions_carry_reasons(toy_unit, m2_lbmps):
    _, _, _, decisions = run_day(toy_unit, m2_lbmps, "dp")
    assert [d.commit for d in decisions] == PLAN_A_ON
    assert [d.target_mw for d in decisions] == [0.0] * 6 + [600.0] * 4 + [450.0] * 6 + [600.0] * 6 + [0.0] * 2
    assert decisions[0].reason == "off: DA LBMP 40.00 $/MWh, prices ahead do not cover a cold start"
    assert decisions[6].reason == "cold start after 174 h off, start cost 45,000 $: the run that follows pays for it; 600.0 MW"
    assert decisions[7].reason == "on: hour margin 7,220 $ at 600.0 MW (DA LBMP 60.00 $/MWh)"
    assert decisions[10].reason == "on at a loss of 2,050 $ at 450.0 MW: minimum up time, hour 5 of 8"
    assert decisions[14].reason == "on at a loss of 2,050 $ at 450.0 MW: cheaper than shutting down and restarting"
    assert decisions[22].reason == "shut down after 16 h on: DA LBMP 40.00 $/MWh, prices ahead do not cover running"
    _, _, _, constrained = run_day(toy_unit, m2_lbmps, "price_taker_constrained")
    assert [d.commit for d in constrained] == PLAN_B_ON
    assert constrained[16].reason == "off: minimum down time, hour 3 of 6 (DA LBMP 70.00 $/MWh)"
    assert constrained[20].reason.startswith("hot start after 6 h off, start cost 14,000 $")


def test_second_day_changes_the_first_days_plan(toy_unit):
    """With one day in view the unit stops at the end of a thin day; with a strong next day
    in view it stays on overnight at a loss instead of paying another start."""
    # Staying on through 4 h at 42 costs 4 x 2,590 = 10,360; a hot restart costs 14,000 and
    # could not happen in time anyway (minimum down 6 h).
    thin = [40.0] * 8 + [60.0] * 14 + [42.0] * 2
    strong = [42.0] * 2 + [80.0] * 22
    day1 = (day_prices("U1", thin, date(2025, 1, 15)), toy_offer_for(toy_unit, date(2025, 1, 15)))
    day2 = (day_prices("U1", strong, date(2025, 1, 16)), toy_offer_for(toy_unit, date(2025, 1, 16)))
    state0 = initial_state(toy_unit, day1[0].hours[0].ts_utc, day1[0].hours[0].ts_local, 168)
    alone = commitment.solve([day1], state0, toy_unit, solver="dp")
    with_lookahead = commitment.solve([day1, day2], state0, toy_unit, solver="dp")
    assert len(alone) == len(with_lookahead) == 24
    assert [d.commit for d in alone][22:] == [False] * 2
    assert [d.commit for d in with_lookahead][22:] == [True] * 2
