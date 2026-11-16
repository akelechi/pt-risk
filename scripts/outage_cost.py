"""Cost of forced outages: the no-outage run's energy margin less the outage run's.

Usage:  python scripts/outage_cost.py [number_of_seeds]

Prints the cost for the seed in config/scenario.m3.yaml with the outage days behind it,
then the same cost for seeds 1..N (default 50) to show how much it depends on which days
are drawn. Reads committed scenarios and curated data only; every figure is a difference
of two engine runs.
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

from engine.run import REPO_ROOT, load_scenario, run


def outage_days(result) -> list[str]:
    return sorted({inputs.ts_local.date().isoformat() for inputs in result.hour_inputs if inputs.forced_outage})


if __name__ == "__main__":
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    scenario = load_scenario(Path(REPO_ROOT) / "config" / "scenario.m3.yaml")
    baseline = run(load_scenario(Path(REPO_ROOT) / "config" / "scenario.m3_no_outage.yaml"))
    base_margin = baseline.meta.energy_margin_usd
    result = run(scenario)
    print(f"no outages:   energy margin {base_margin:,.2f}")
    print(f"seed {scenario.seed}: energy margin {result.meta.energy_margin_usd:,.2f}, "
          f"cost of outages {base_margin - result.meta.energy_margin_usd:,.2f}, days {outage_days(result)}")
    for day in outage_days(result):
        hours = [(state, inputs) for state, inputs in zip(result.states, result.hour_inputs)
                 if inputs.forced_outage and inputs.ts_local.date().isoformat() == day]
        schedule_mwh = sum(state.da_schedule_mw for state, _ in hours)
        da_usd = sum(state.da_schedule_mw * inputs.da_lbmp_usd_per_mwh for state, inputs in hours)
        rt_usd = sum(state.da_schedule_mw * inputs.rt_lbmp_usd_per_mwh for state, inputs in hours)
        print(f"  {day}: DA schedule {schedule_mwh:,.1f} MWh, DA revenue {da_usd:,.2f}, bought back at RT for {rt_usd:,.2f}")

    costs = []
    for seed in range(1, seeds + 1):
        drawn = run(scenario.model_copy(update={"seed": seed}))
        costs.append((base_margin - drawn.meta.energy_margin_usd, len(outage_days(drawn))))
    usd = sorted(cost for cost, _ in costs)
    print(f"seeds 1..{seeds}: cost of outages mean {statistics.mean(usd):,.2f}, median {statistics.median(usd):,.2f}, "
          f"min {usd[0]:,.2f}, max {usd[-1]:,.2f}; outage days mean {statistics.mean(n for _, n in costs):.2f}")
    print(f"deterministic derate for comparison (EFOR x no-outage margin): {0.10 * base_margin:,.2f}")
