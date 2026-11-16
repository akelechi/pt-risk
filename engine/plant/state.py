"""PlantState and transition(): the state machine of one unit.

`transition` is the only function that produces a new state and the only function that
creates ledger entries. It is pure and deterministic: same arguments, same result.
"""

from __future__ import annotations

from datetime import datetime

from engine.contracts import Decision, HourInputs, LedgerEntry, PlantState
from engine.ledger.ledger import round_to_cent_usd
from engine.market import settlement
from engine.plant import cost
from engine.plant.params import UnitParams

MW_TOLERANCE = 1e-6


def initial_state(unit: UnitParams, ts_utc: datetime, ts_local: datetime, hours_offline_h: int) -> PlantState:
    """State before the first hour of a run: off for `hours_offline_h`, oil fields at zero
    (dual fuel arrives in milestone 4). `ts_*` is the first hour of the run."""
    return PlantState(
        ts_utc=ts_utc,
        ts_local=ts_local,
        unit_id=unit.id,
        committed=False,
        hours_in_state_h=hours_offline_h,
        thermal_state=cost.thermal_state(hours_offline_h, unit),
        output_mw=0.0,
        fuel=None,
        oil_inventory_bbl=0.0,
        oil_permit_hours_used_ytd_h=0.0,
        available_mw=cost.deterministic_available_mw(unit),
        da_schedule_mw=0.0,
    )


def _entry(inputs: HourInputs, unit_id: str, line: str, quantity: float, quantity_unit: str,
           price: float, price_unit: str, sign: int, ref: dict[str, str]) -> LedgerEntry:
    return LedgerEntry(
        ts_utc=inputs.ts_utc,
        ts_local=inputs.ts_local,
        unit_id=unit_id,
        line=line,
        quantity=quantity,
        quantity_unit=quantity_unit,
        price=price,
        price_unit=price_unit,
        amount_usd=sign * round_to_cent_usd(quantity * price),
        ref=ref,
    )


def transition(
    state: PlantState, decision: Decision, inputs: HourInputs, unit: UnitParams
) -> tuple[PlantState, list[LedgerEntry]]:
    """Apply one hour's decision: returns the state during that hour and its ledger entries.

    Milestone 1 (gas only, DA only): actual output equals the DA schedule, which equals the
    decision's target. Booked per running hour:
      da_energy_rev  +  MWh x DA LBMP ($/MWh)
      fuel_cost_gas  -  MMBtu x gas price ($/MMBtu), MMBtu from the true heat-rate curve
      vom            -  MWh x VOM ($/MWh)
    """
    if decision.unit_id != unit.id or state.unit_id != unit.id:
        raise ValueError("state, decision and unit do not describe the same unit")
    if decision.ts_utc != inputs.ts_utc:
        raise ValueError("decision and inputs are for different hours")
    if decision.commit != (decision.target_mw > 0):
        raise ValueError("commit must be true exactly when target_mw > 0")
    if decision.target_mw > inputs.available_mw + MW_TOLERANCE:
        raise ValueError(f"target {decision.target_mw} MW exceeds available {inputs.available_mw} MW")
    if decision.commit and decision.fuel != "gas":
        raise NotImplementedError("oil dispatch arrives in milestone 4")

    same_state = decision.commit == state.committed
    hours_in_state_h = state.hours_in_state_h + 1 if same_state else 1
    hours_offline_h = 0 if decision.commit else hours_in_state_h
    output_mw = decision.target_mw

    new_state = PlantState(
        ts_utc=inputs.ts_utc,
        ts_local=inputs.ts_local,
        unit_id=unit.id,
        committed=decision.commit,
        hours_in_state_h=hours_in_state_h,
        thermal_state=cost.thermal_state(hours_offline_h, unit),
        output_mw=output_mw,
        fuel=decision.fuel if decision.commit else None,
        oil_inventory_bbl=state.oil_inventory_bbl,
        oil_permit_hours_used_ytd_h=state.oil_permit_hours_used_ytd_h,
        available_mw=inputs.available_mw,
        da_schedule_mw=output_mw,
    )

    entries: list[LedgerEntry] = []
    if decision.commit:
        energy_mwh = settlement.da_energy_mwh(output_mw)
        fuel_mmbtu = cost.fuel_burn_mmbtu_per_h(unit, output_mw) * settlement.HOUR_H
        entries.append(
            _entry(inputs, unit.id, "da_energy_rev", energy_mwh, "MWh",
                   inputs.da_lbmp_usd_per_mwh, "USD/MWh", +1, {"lbmp_da": inputs.da_lbmp_ref})
        )
        entries.append(
            _entry(inputs, unit.id, "fuel_cost_gas", fuel_mmbtu, "MMBtu",
                   inputs.gas_price_usd_per_mmbtu, "USD/MMBtu", -1, {"gas_price": inputs.gas_price_ref})
        )
        entries.append(
            _entry(inputs, unit.id, "vom", energy_mwh, "MWh",
                   unit.vom_usd_per_mwh.value, "USD/MWh", -1, {"param": f"units.{unit.id}.vom_usd_per_mwh"})
        )
    return new_state, entries
