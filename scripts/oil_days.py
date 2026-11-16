"""Days on oil and the margin captured on them: the dual-fuel run against the gas-only run.

Usage:  python scripts/oil_days.py

Runs config/scenario.m4.yaml (dual fuel) and config/scenario.m3.yaml (same month and seed,
gas only) and prints, for each day the plant chose oil, both runs' energy margin and hours
on line. Every figure is read from the two runs' ledgers and states.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from engine.run import ENERGY_MARGIN_LINES, REPO_ROOT, load_scenario, run


def by_day(result) -> tuple[dict, dict]:
    margin: dict = defaultdict(Decimal)
    for entry in result.ledger:
        if entry.line in ENERGY_MARGIN_LINES:
            margin[entry.ts_local.date()] += Decimal(repr(entry.amount_usd))
    hours: dict = defaultdict(lambda: {"on": 0, "oil": 0, "outage": 0})
    for state, inputs in zip(result.states, result.hour_inputs):
        day = state.ts_local.date()
        hours[day]["on"] += int(state.committed)
        hours[day]["oil"] += int(state.fuel == "oil")
        hours[day]["outage"] += int(inputs.forced_outage)
    return margin, hours


if __name__ == "__main__":
    oil = run(load_scenario(Path(REPO_ROOT) / "config" / "scenario.m4.yaml"))
    gas = run(load_scenario(Path(REPO_ROOT) / "config" / "scenario.m3.yaml"))
    oil_margin, oil_hours = by_day(oil)
    gas_margin, gas_hours = by_day(gas)
    oil_days = [offer.local_date for offer in oil.offers if offer.fuel == "oil"]
    print("day         dual-fuel margin  h on  h oil  gas-only margin  h on  outage  oil $/MMBtu  gas $/MMBtu")
    total = Decimal("0")
    for day in oil_days:
        inputs = next(i for i in oil.hour_inputs if i.ts_local.date() == day)
        total += oil_margin[day] - gas_margin[day]
        print(f"{day}  {oil_margin[day]:>16,.2f}  {oil_hours[day]['on']:>4}  {oil_hours[day]['oil']:>5}  "
              f"{gas_margin[day]:>15,.2f}  {gas_hours[day]['on']:>4}  {'yes' if oil_hours[day]['outage'] else 'no':>6}  "
              f"{inputs.oil_price_usd_per_mmbtu:>11.3f}  {inputs.gas_price_usd_per_mmbtu:>11.2f}")
    print(f"days oil was the chosen fuel: {len(oil_days)}; days it was burned: {sum(1 for d in oil_days if oil_hours[d]['oil'])}")
    print(f"margin captured on those days: {total:,.2f}")
    print(f"month: dual fuel {oil.meta.energy_margin_usd:,.2f}, gas only {gas.meta.energy_margin_usd:,.2f}, "
          f"difference {oil.meta.energy_margin_usd - gas.meta.energy_margin_usd:,.2f}")
    burned = sum(e.quantity for e in oil.ledger if e.quantity_unit == "MMBtu" and e.ref.get("oil_price"))
    received = [(s.ts_local.date().isoformat(), round(s.oil_received_bbl, 1)) for s in oil.states if s.oil_received_bbl > 0]
    low = min(s.oil_inventory_bbl for s in oil.states)
    print(f"oil burned {burned:,.1f} MMBtu = {burned / 6.3:,.1f} bbl; lowest tank {low:,.1f} bbl; barges {received}")
    print(f"permit hours used {oil.states[-1].oil_permit_hours_used_ytd_h:.0f}; starts {oil.meta.solver_comparison[0].starts}")
