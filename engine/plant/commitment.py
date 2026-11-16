"""Commitment solvers behind one interface: solve(days, state0, unit, solver) -> decisions.

`price_taker` is the unconstrained baseline and stays forever as the comparison: every
hour stands alone, a step runs when the DA LBMP is above its offer price, and there is no
start cost, no-load cost, minimum run time or minimum down time.

`dp` (milestone 2) is a dynamic program over (on/off, hours in state) with start cost by
thermal state, no-load cost and minimum up and down times. It plans over a horizon of up
to two local days with perfect foresight of the DA LBMP and the fuel price; only the
first day's decisions are used, and the next day is planned again from the state actually
reached (rolling horizon).

`price_taker_constrained` is the price-taker's rule made feasible: it wants to be on when
the LBMP is above its lowest one-part offer, but it obeys minimum up and down times and
pays start and no-load cost. It is the lower bound of invariant 5.

All three share one hourly margin function, so their values are comparable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from engine.contracts import CommitmentBound, DayPrices, Decision, HourPrice, Offer, PlantState
from engine.market.offer import cleared_mw, committed_dispatch_mw
from engine.plant import cost
from engine.plant.params import UnitParams

VALUE_TOLERANCE_USD = 1e-6  # a start or a shutdown must be better by more than this to be chosen
PlanDay = tuple[DayPrices, Offer]


@dataclass(frozen=True)
class HorizonHour:
    """One hour of a planning horizon: its price and the offer of its local day."""

    price: HourPrice
    offer: Offer

    @property
    def lbmp_usd_per_mwh(self) -> float:
        return self.price.da_lbmp_usd_per_mwh


def horizon_hours(days: Sequence[PlanDay]) -> list[HorizonHour]:
    """Flatten planning days into hours, checking each offer belongs to its day."""
    hours: list[HorizonHour] = []
    for prices, offer in days:
        if offer.unit_id != prices.unit_id or offer.local_date != prices.local_date:
            raise ValueError("prices and offer do not describe the same unit and day")
        hours.extend(HorizonHour(price, offer) for price in prices.hours)
    return hours


def hour_margin_usd(unit: UnitParams, offer: Offer, lbmp_usd_per_mwh: float, output_mw: float, no_load: bool) -> float:
    """Energy margin of one hour at `output_mw`, USD: revenue less fuel and VOM.

    Fuel is the true heat-rate curve integrated from 0 MW, plus no-load fuel when
    `no_load` is set. Unrounded; the ledger rounds each line to the cent.
    """
    if output_mw <= 0:
        return 0.0
    fuel_mmbtu = cost.fuel_burn_mmbtu_per_h(unit, output_mw) + (cost.no_load_fuel_mmbtu_per_h(unit) if no_load else 0.0)
    return (
        lbmp_usd_per_mwh * output_mw
        - fuel_mmbtu * offer.heat_input_multiplier * offer.fuel_price_usd_per_mmbtu
        - unit.vom_usd_per_mwh.value * output_mw
    )


def start_cost_usd(unit: UnitParams, offer: Offer, hours_offline_h: int) -> float:
    """Cost of starting after `hours_offline_h` hours off, at the offer's fuel price."""
    return cost.start_cost_usd(
        unit, cost.thermal_state(hours_offline_h, unit), offer.fuel_price_usd_per_mmbtu, offer.heat_input_multiplier
    )


def can_start(unit: UnitParams, hours_off_h: int) -> bool:
    return hours_off_h >= unit.min_down_hours.value


def can_stop(unit: UnitParams, hours_on_h: int) -> bool:
    return hours_on_h >= unit.min_up_hours.value


# ------------------------------------------------------------------ plans


def plan_value_usd(unit: UnitParams, hours: Sequence[HorizonHour], on0: bool, hours_in_state0_h: int,
                   on_flags: Sequence[bool]) -> float:
    """Energy margin of a commitment plan over a horizon, USD, with start and no-load cost.

    Raises if the plan breaks minimum up or down time or runs a unit that cannot run.
    """
    on, hours_in_state = on0, hours_in_state0_h
    value = 0.0
    for hour, flag in zip(hours, on_flags, strict=True):
        if flag and not on:
            if not can_start(unit, hours_in_state):
                raise ValueError(f"{hour.price.ts_utc}: start breaks minimum down time")
            value -= start_cost_usd(unit, hour.offer, hours_in_state)
        if on and not flag and not can_stop(unit, hours_in_state):
            raise ValueError(f"{hour.price.ts_utc}: shutdown breaks minimum up time")
        if flag:
            if hour.offer.min_gen_mw <= 0:
                raise ValueError(f"{hour.price.ts_utc}: unit cannot run")
            value += hour_margin_usd(unit, hour.offer, hour.lbmp_usd_per_mwh,
                                     committed_dispatch_mw(hour.offer, hour.lbmp_usd_per_mwh), no_load=True)
        hours_in_state = hours_in_state + 1 if flag == on else 1
        on = flag
    return value


def dp_plan(unit: UnitParams, hours: Sequence[HorizonHour], on0: bool, hours_in_state0_h: int) -> tuple[list[bool], float]:
    """Optimal commitment over the horizon: (on/off per hour, energy margin in USD).

    Backward induction over the state reached in the previous hour, (on, hours in state).
    Hours on are capped at the minimum up time and hours off just past the warm threshold:
    beyond those the state no longer changes what is allowed or what a start costs.
    Nothing is assumed about what happens after the horizon (terminal value 0). A start or
    a shutdown is chosen only when it is strictly better.
    """
    cap_on = max(unit.min_up_hours.value, 1)
    cap_off = max(unit.start.warm.value.hours_offline_max_h + 1, unit.min_down_hours.value, 1)

    def capped(on: bool, hours_in_state: int) -> tuple[bool, int]:
        return (on, min(hours_in_state, cap_on if on else cap_off))

    states = [(True, h) for h in range(1, cap_on + 1)] + [(False, h) for h in range(1, cap_off + 1)]
    value_after = {state: 0.0 for state in states}
    turn_on: list[dict[tuple[bool, int], bool]] = [{} for _ in hours]
    for index in range(len(hours) - 1, -1, -1):
        hour = hours[index]
        runnable = hour.offer.min_gen_mw > 0
        margin = (
            hour_margin_usd(unit, hour.offer, hour.lbmp_usd_per_mwh,
                            committed_dispatch_mw(hour.offer, hour.lbmp_usd_per_mwh), no_load=True)
            if runnable else 0.0
        )
        value_here: dict[tuple[bool, int], float] = {}
        for on, hours_in_state in states:
            value_on = value_off = None
            if on:
                if runnable:
                    value_on = margin + value_after[capped(True, hours_in_state + 1)]
                if can_stop(unit, hours_in_state) or not runnable:
                    value_off = value_after[(False, 1)]
            else:
                value_off = value_after[capped(False, hours_in_state + 1)]
                if runnable and can_start(unit, hours_in_state):
                    value_on = margin - start_cost_usd(unit, hour.offer, hours_in_state) + value_after[(True, 1)]
            if value_on is None:
                choose_on = False
            elif value_off is None:
                choose_on = True
            elif on:  # staying on is the default; shut down only if strictly better
                choose_on = value_off <= value_on + VALUE_TOLERANCE_USD
            else:  # staying off is the default; start only if strictly better
                choose_on = value_on > value_off + VALUE_TOLERANCE_USD
            turn_on[index][(on, hours_in_state)] = choose_on
            value_here[(on, hours_in_state)] = value_on if choose_on else value_off
        value_after = value_here

    flags: list[bool] = []
    state = capped(on0, hours_in_state0_h)
    total = value_after[state] if hours else 0.0
    for index in range(len(hours)):
        flag = turn_on[index][state]
        flags.append(flag)
        state = capped(flag, state[1] + 1 if flag == state[0] else 1)
    return flags, total


def price_taker_constrained_plan(unit: UnitParams, hours: Sequence[HorizonHour], on0: bool,
                                 hours_in_state0_h: int) -> list[bool]:
    """The price-taker's rule made feasible: on when the LBMP is above the lowest one-part
    offer step, unless minimum up or down time forbids the change."""
    on, hours_in_state = on0, hours_in_state0_h
    flags: list[bool] = []
    for hour in hours:
        runnable = hour.offer.min_gen_mw > 0
        wants_on = runnable and cleared_mw(hour.offer, hour.lbmp_usd_per_mwh)[1] > 0
        if on:
            flag = runnable and (wants_on or not can_stop(unit, hours_in_state))
        else:
            flag = wants_on and can_start(unit, hours_in_state)
        flags.append(flag)
        hours_in_state = hours_in_state + 1 if flag == on else 1
        on = flag
    return flags


def unconstrained_value_usd(unit: UnitParams, hours: Sequence[HorizonHour]) -> float:
    """Best energy margin hour by hour with no start cost, no-load cost or run-time limits:
    in each hour the best of staying off and every corner of the true heat-rate curve.
    No commitment plan can beat it."""
    total = 0.0
    for hour in hours:
        corners = [block.mw_to for block in cost.true_blocks(unit, cap_mw=hour.offer.available_mw)]
        best = max(
            (hour_margin_usd(unit, hour.offer, hour.lbmp_usd_per_mwh, mw, no_load=False) for mw in corners),
            default=0.0,
        )
        total += max(0.0, best)
    return total


def margin_bound(unit: UnitParams, days: Sequence[PlanDay], state0: PlantState) -> CommitmentBound:
    """Invariant 5 for one planning problem: DP optimum, constrained price-taker, unconstrained."""
    hours = horizon_hours(days)
    _, dp_value = dp_plan(unit, hours, state0.committed, state0.hours_in_state_h)
    constrained = price_taker_constrained_plan(unit, hours, state0.committed, state0.hours_in_state_h)
    return CommitmentBound(
        unit_id=unit.id,
        local_date=days[0][0].local_date,
        horizon_hours=len(hours),
        dp_value_usd=dp_value,
        price_taker_constrained_value_usd=plan_value_usd(
            unit, hours, state0.committed, state0.hours_in_state_h, constrained
        ),
        unconstrained_value_usd=unconstrained_value_usd(unit, hours),
    )


# ------------------------------------------------------------------ decisions


def _decision(hour: HorizonHour, unit: UnitParams, target_mw: float, reason: str) -> Decision:
    return Decision(
        ts_utc=hour.price.ts_utc,
        ts_local=hour.price.ts_local,
        unit_id=unit.id,
        commit=target_mw > 0,
        target_mw=target_mw,
        fuel=hour.offer.fuel,
        reason=reason,
    )


def price_taker(days: Sequence[PlanDay], state0: PlantState, unit: UnitParams) -> list[Decision]:
    """Hour-by-hour price-taker: dispatch every one-part offer step priced below the DA LBMP.

    `state0` is unused: the baseline has no memory. Returns one Decision per hour of the
    first day.
    """
    del state0
    prices, offer = days[0]
    decisions: list[Decision] = []
    lowest = offer.blocks[0].price_usd_per_mwh if offer.blocks else None
    for hour in horizon_hours(days[:1]):
        mw, steps = cleared_mw(offer, hour.lbmp_usd_per_mwh)
        if steps:
            marginal = offer.blocks[steps - 1].price_usd_per_mwh
            reason = (
                f"DA LBMP {hour.lbmp_usd_per_mwh:.2f} > offer {marginal:.2f} $/MWh "
                f"on {steps} of {len(offer.blocks)} steps: {mw:.1f} MW"
            )
        elif lowest is None:
            reason = "nothing offered: 0 MW available"
        else:
            reason = f"DA LBMP {hour.lbmp_usd_per_mwh:.2f} <= lowest offer {lowest:.2f} $/MWh: off"
        decisions.append(_decision(hour, unit, mw, reason))
    return decisions


def _decisions_from_plan(unit: UnitParams, hours: Sequence[HorizonHour], first_day_hours: int, state0: PlantState,
                         flags: Sequence[bool], why_off: str, why_start: str) -> list[Decision]:
    """Decisions for the first day of a plan, with the reason for each hour."""
    min_up, min_down = unit.min_up_hours.value, unit.min_down_hours.value
    on, hours_in_state = state0.committed, state0.hours_in_state_h
    decisions: list[Decision] = []
    for hour, flag in zip(hours[:first_day_hours], flags[:first_day_hours], strict=True):
        lbmp = hour.lbmp_usd_per_mwh
        if flag:
            mw = committed_dispatch_mw(hour.offer, lbmp)
            margin = hour_margin_usd(unit, hour.offer, lbmp, mw, no_load=True)
            if not on:
                thermal = cost.thermal_state(hours_in_state, unit)
                reason = (
                    f"{thermal} start after {hours_in_state} h off, start cost "
                    f"{start_cost_usd(unit, hour.offer, hours_in_state):,.0f} $: {why_start}; {mw:.1f} MW"
                )
            elif margin >= 0:
                reason = f"on: hour margin {margin:,.0f} $ at {mw:.1f} MW (DA LBMP {lbmp:.2f} $/MWh)"
            elif hours_in_state < min_up:
                reason = (
                    f"on at a loss of {-margin:,.0f} $ at {mw:.1f} MW: minimum up time, "
                    f"hour {hours_in_state + 1} of {min_up}"
                )
            else:
                reason = f"on at a loss of {-margin:,.0f} $ at {mw:.1f} MW: {why_off}"
        else:
            mw = 0.0
            if hour.offer.min_gen_mw <= 0:
                reason = "nothing offered: less than Pmin available"
            elif on:
                reason = f"shut down after {hours_in_state} h on: DA LBMP {lbmp:.2f} $/MWh, prices ahead do not cover running"
            elif hours_in_state < min_down:
                reason = f"off: minimum down time, hour {hours_in_state + 1} of {min_down} (DA LBMP {lbmp:.2f} $/MWh)"
            else:
                thermal = cost.thermal_state(hours_in_state, unit)
                reason = f"off: DA LBMP {lbmp:.2f} $/MWh, prices ahead do not cover a {thermal} start"
        decisions.append(_decision(hour, unit, mw, reason))
        hours_in_state = hours_in_state + 1 if flag == on else 1
        on = flag
    return decisions


def dp(days: Sequence[PlanDay], state0: PlantState, unit: UnitParams) -> list[Decision]:
    """Optimal commitment over the horizon `days`; decisions for the first day only."""
    hours = horizon_hours(days)
    flags, _ = dp_plan(unit, hours, state0.committed, state0.hours_in_state_h)
    return _decisions_from_plan(
        unit, hours, len(days[0][0].hours), state0, flags,
        why_off="cheaper than shutting down and restarting",
        why_start="the run that follows pays for it",
    )


def price_taker_constrained(days: Sequence[PlanDay], state0: PlantState, unit: UnitParams) -> list[Decision]:
    """The price-taker's rule under minimum up and down times; decisions for the first day."""
    hours = horizon_hours(days[:1])
    flags = price_taker_constrained_plan(unit, hours, state0.committed, state0.hours_in_state_h)
    return _decisions_from_plan(
        unit, hours, len(hours), state0, flags,
        why_off="LBMP is above the lowest offer step, which leaves out no-load cost",
        why_start="LBMP is above the lowest offer",
    )


SOLVERS = {"price_taker": price_taker, "price_taker_constrained": price_taker_constrained, "dp": dp}
# Solvers that pay start and no-load cost and obey run-time limits.
COMMITMENT_COST_SOLVERS = frozenset({"price_taker_constrained", "dp"})


def solve(days: Sequence[PlanDay], state0: PlantState, unit: UnitParams, solver: str = "price_taker") -> list[Decision]:
    """Run the named commitment solver. `days` is the planning horizon, first day first;
    the result is one Decision per hour of the first day."""
    if solver not in SOLVERS:
        raise ValueError(f"unknown commitment solver {solver!r}; have {sorted(SOLVERS)}")
    if not days or any(prices.unit_id != unit.id for prices, _ in days):
        raise ValueError("planning days must be non-empty and belong to the unit")
    horizon_hours(days)  # validates that each offer matches its day
    return SOLVERS[solver](days, state0, unit)
