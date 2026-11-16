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
    decisions = commitment.solve(prices, state0, toy_unit, toy_offer(toy_unit))
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
    assert commitment.price_taker(prices, cold, toy_unit, offer) == commitment.price_taker(prices, hot, toy_unit, offer)


def test_solver_refuses_mismatched_inputs_and_unknown_solvers(toy_unit, hand_lbmps):
    prices = day_prices("U1", hand_lbmps)
    state0 = initial_state(toy_unit, prices.hours[0].ts_utc, prices.hours[0].ts_local, 168)
    with pytest.raises(ValueError, match="unknown commitment solver"):
        commitment.solve(prices, state0, toy_unit, toy_offer(toy_unit), solver="dp")
    other_day = build_offer(toy_unit, date(2025, 1, 16), "gas", 4.0, "hand:gas", 600.0, OFFER_PRICE_DECIMALS)
    with pytest.raises(ValueError, match="same unit and day"):
        commitment.solve(prices, state0, toy_unit, other_day)
    with pytest.raises(ValueError, match="same unit and day"):
        commitment.solve(day_prices("U2", hand_lbmps), state0, toy_unit, toy_offer(toy_unit))
