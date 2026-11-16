"""Cost model: heat-rate blocks, convexification, fuel burn, marginal cost, thermal state.

Expected values are worked by hand from the toy unit (see tests/fixtures/m1_hand_day.xlsx).
"""

from __future__ import annotations

import pytest

from engine.plant import cost
from engine.plant.cost import HeatRateBlock


def ihrs(blocks: list[HeatRateBlock]) -> list[float]:
    return [round(block.incremental_heat_rate_mmbtu_per_mwh, 9) for block in blocks]


def edges(blocks: list[HeatRateBlock]) -> list[tuple[float, float]]:
    return [(block.mw_from, block.mw_to) for block in blocks]


def test_true_blocks_start_at_zero_and_end_at_pmax(toy_unit):
    blocks = cost.true_blocks(toy_unit)
    assert edges(blocks) == [(0.0, 150), (150, 300), (300, 450), (450, 600)]
    assert ihrs(blocks) == [11.4, 10.1, 10.0, 10.8]


def test_true_blocks_are_truncated_at_the_cap(toy_unit):
    assert edges(cost.true_blocks(toy_unit, cap_mw=540)) == [(0.0, 150), (150, 300), (300, 450), (450, 540)]
    assert edges(cost.true_blocks(toy_unit, cap_mw=300)) == [(0.0, 150), (150, 300)]
    assert edges(cost.true_blocks(toy_unit, cap_mw=100)) == [(0.0, 100)]
    assert cost.true_blocks(toy_unit, cap_mw=0) == []
    assert edges(cost.true_blocks(toy_unit, cap_mw=9999))[-1] == (450, 600)


def test_convexify_pools_decreasing_blocks_at_the_weighted_average(toy_unit):
    # 11.4 > 10.1 -> pool to 10.75 over 300 MW; 10.0 < 10.75 -> pool to 4725/450 = 10.5; 10.8 stays
    pooled = cost.convexify(cost.true_blocks(toy_unit))
    assert edges(pooled) == [(0.0, 450), (450, 600)]
    assert ihrs(pooled) == [10.5, 10.8]


def test_convexify_leaves_a_monotone_curve_alone_and_uses_mw_weights():
    monotone = [HeatRateBlock(0, 100, 9.0), HeatRateBlock(100, 200, 9.5), HeatRateBlock(200, 300, 9.5)]
    assert cost.convexify(monotone) == monotone
    uneven = [HeatRateBlock(0, 100, 12.0), HeatRateBlock(100, 400, 10.0)]  # (1200 + 3000) / 400
    assert ihrs(cost.convexify(uneven)) == [10.5]
    assert cost.convexify([]) == []


def test_convexified_curve_is_always_non_decreasing(real_unit):
    for cap in (None, 553.32, 300, 141):
        pooled = cost.convexify(cost.true_blocks(real_unit, cap_mw=cap))
        rates = ihrs(pooled)
        assert rates == sorted(rates)
        assert pooled[0].mw_from == 0.0


def test_fuel_burn_integrates_the_true_curve(toy_unit):
    assert cost.fuel_burn_mmbtu_per_h(toy_unit, 0) == 0
    assert cost.fuel_burn_mmbtu_per_h(toy_unit, 150) == pytest.approx(1710.0)  # 150 x 11.4
    assert cost.fuel_burn_mmbtu_per_h(toy_unit, 200) == pytest.approx(2215.0)  # + 50 x 10.1
    assert cost.fuel_burn_mmbtu_per_h(toy_unit, 450) == pytest.approx(4725.0)  # 1710 + 1515 + 1500
    assert cost.fuel_burn_mmbtu_per_h(toy_unit, 600) == pytest.approx(6345.0)  # + 150 x 10.8
    with pytest.raises(ValueError):
        cost.fuel_burn_mmbtu_per_h(toy_unit, 601)
    with pytest.raises(ValueError):
        cost.fuel_burn_mmbtu_per_h(toy_unit, -1)


def test_pooled_curve_implies_the_true_fuel_at_every_step_end(real_unit):
    pooled = cost.convexify(cost.true_blocks(real_unit, cap_mw=cost.deterministic_available_mw(real_unit)))
    running = 0.0
    for block in pooled:
        running += block.width_mw * block.incremental_heat_rate_mmbtu_per_mwh
        assert running == pytest.approx(cost.fuel_burn_mmbtu_per_h(real_unit, block.mw_to))


def test_marginal_cost_formula():
    assert cost.marginal_cost_usd_per_mwh(10.5, 4.00, 3.00) == pytest.approx(45.00)
    assert cost.marginal_cost_usd_per_mwh(10.8, 4.00, 3.00) == pytest.approx(46.20)
    # with CO2: 10 x 4 + 3 + 0.0531 x 10 x 20 = 53.62
    assert cost.marginal_cost_usd_per_mwh(10.0, 4.00, 3.00, 0.0531, 20.0) == pytest.approx(53.62)


def test_deterministic_availability_is_pmax_times_one_minus_efor(toy_unit, real_unit):
    assert cost.deterministic_available_mw(toy_unit) == 600.0
    assert cost.deterministic_available_mw(real_unit) == 553.32  # 614.8 x 0.90


@pytest.mark.parametrize("hours,expected", [(0, "hot"), (12, "hot"), (13, "warm"), (72, "warm"), (73, "cold"), (168, "cold")])
def test_thermal_state_thresholds(real_unit, hours, expected):
    assert cost.thermal_state(hours, real_unit) == expected
