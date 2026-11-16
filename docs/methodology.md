# Methodology

Kept current; rules are written here before the numbers that depend on them. Each rule
names the open question that could change it.

## 1. Scope

A commercial model of one plant as a price-taker against published NYISO LBMPs. The ISO's
optimization is not simulated. Public data only.

## 2. Time

* Hourly records are **hour-beginning**, stored as `ts_utc` (UTC) and `ts_local`
  (America/New_York with its UTC offset). Both name the same instant.
* NYISO stamps rows in naive local prevailing time. On the spring-forward day the 02:00
  hour is absent (23 hours). On the fall-back day 01:00 appears twice (25 hours) with no
  marker; the loader reads **file order**: first occurrence EDT, second EST.
* No hour is dropped or duplicated silently. A table is refused if any local day does not
  have the 23/24/25 hours the timezone rules call for, if a `ts_utc` repeats for a
  location, if a stamp falls inside the spring gap, or if a day is missing inside the
  covered range.
* Local day, month and year boundaries (roll-ups, settlement periods) follow `ts_local`.
* The engine never reads the wall clock. Time comes from the scenario. Retrieval times are
  written by `scripts/fetch_raw.py` into `data/raw.manifest.json` and read from there.

## 3. Market inputs

### 3.1 LBMP (`lbmp_da`, `lbmp_rt`)

* Source: NYISO monthly archives of daily CSVs: `damlbmp` (day-ahead) and `rtlbmp`
  (real-time, NYISO's time-weighted integrated hourly price), generator and zonal files.
* Locations: the two Roseton generator buses and Zone G (`HUD VL`). Each unit is intended
  to settle at its own bus; the zone is kept for reference and later hedges (Q-005).
* RT hourly price is NYISO's published integrated hourly figure, not an average recomputed
  from 5-minute files (Q-006).
* **Energy component.** NYISO publishes LBMP, marginal cost of losses and marginal cost of
  congestion, but no energy component. In NYISO's sign convention
  `LBMP = energy + losses - congestion`, so `energy = lbmp - loss + congestion`, rounded to
  the cent. `congestion_usd_per_mwh` is stored with the published sign (Q-004).
* **Check.** The energy price is system-wide, so it must agree across locations in each
  hour. The loader enforces agreement within $0.031/MWh: three published terms each
  rounded to +/-$0.005, at two locations, bound the difference at $0.03.

### 3.2 Gas (`gas_price`)

* Source: EIA Henry Hub daily spot (`RNGWHHDd.xls`), $/MMBtu.
* The curated table holds **published trading days only**. No price is invented for
  weekends or holidays in the table. From milestone 1 the engine will apply the last
  published price on or before each gas day (Q-012); the table keeps 31 days before the
  window so the first days of the window have one.
* Delivered basis is not loaded. Until milestone 5 it is an `assumed` monthly adder in
  the plant config, added to Henry Hub for every gas day (Q-028).

### 3.3 EIA plant reference (`eia_plant_reference`)

EIA-860 generator capacities and EIA-923 annual fuel and generation for plant code 8006,
kept as public evidence for plant parameters. Nothing in the engine reads it as an input.
The configured plant code is verified against the EIA plant name at build time.

## 4. Provenance

* Every plant parameter is a leaf with `value`, `unit`, `status` (`public`, `assumed`,
  `confirmed`), `source`, `as_of`. A leaf missing any of the five, an empty field, a bare
  value outside a leaf, or an unknown key is a build error.
* Every curated row carries `as_of` (UTC retrieval date of its raw file) and `source_id`
  (first 16 hex of the raw file's sha256).
* A curated table's **snapshot id** is a hash of its content. A run records the snapshot
  ids it used, and the store refuses a file whose content no longer matches the manifest.

## 5. Runs and reproducibility

* A run records: config hash (scenario + plant config + market config), data snapshot
  ids, code version (git commit, `+dirty` if tracked files differ), and seed.
* The run id is the first 12 hex of the hash of those four. Same scenario, data and code
  give the same id.
* Invariant 8 is evaluated inside `run()` by executing the scenario twice and comparing
  ledger hashes (Q-021).
* A scenario that switches on a module that is not implemented is refused, not ignored.

## 6. Ledger

* Append-only entries, one per unit x hour x line. Signed: revenue positive, cost negative.
* `amount_usd` is rounded to the cent, half-even, when the entry is written; when a price
  is given, `|amount| = |quantity x price|` to the cent (Q-009).
* Daily and monthly figures are views over the entries, by local period. Nothing is stored
  twice.

## 7. Invariants

Milestone 0: 6 (time integrity, including exact coverage of the scenario window for every
location), 7 (provenance), 8 (reproducibility). Invariants 1-5 report `not_applicable`
until their milestone; they never report `pass` for something that was not checked.

## 8. Cost model (milestone 1)

* **Heat-rate curve.** Each configured point is the incremental heat rate of the block
  ending at that output; the first block runs from 0 MW to Pmin (Q-016). Fuel burned at a
  steady output is that curve integrated from 0 MW. No-load and start fuel are not yet
  included (milestone 2).
* **Offer curve.** The physical blocks are truncated at available MW and convexified:
  adjacent blocks whose heat rate would fall are pooled at their MW-weighted average, so
  offer steps are non-decreasing. At every step boundary the pooled curve implies exactly
  the physical fuel.
* **Step price** = pooled incremental heat rate x fuel price + VOM, rounded to the cent
  (Q-027). CO2 cost is zero until an RGGI price table is loaded (Q-024).
* **Fuel price** = Henry Hub + the plant config's assumed basis adder for the gas day's
  calendar month, while module `gas_basis` is off (Q-028, answered 2026-11-16). Hourly
  inputs keep the index price, the adder and their sum; the sum is what offers and fuel
  cost use. Module `gas_basis` (milestone 5) replaces the adder with a published
  delivered index. The gas day is
  the local calendar day (Q-023); a day with no published price uses the last published
  price on or before it, at most 7 days old (Q-012).
* **Availability** = Pmax x (1 - EFOR) in every hour (Q-025), until seeded outages in
  milestone 3.

## 9. Commitment (milestone 1)

* `price_taker`, the baseline kept forever: each hour stands alone; an offer step runs
  when the DA LBMP is **strictly above** its price (Q-015). No start cost, no minimum run
  or down time, no memory of state.
* One offer per unit and local day; one decision per real hour (23, 24 or 25).

## 10. Settlement (milestone 1: DA only)

* Actual output = DA schedule = the solver's target. `da_energy_rev = da_mw x 1 h x
  da_lbmp` at the unit's own bus (Q-005).
* Booked per running hour: `da_energy_rev` (+), `fuel_cost_gas` (-, MMBtu x delivered gas price),
  `vom` (-, MWh x VOM). Nothing is booked in an idle hour.
* **Energy margin** = `da_energy_rev + rt_balancing + fuel_cost_* + start_cost +
  no_load_cost + vom + emissions_cost` (costs are negative entries).

## 11. State (milestone 1)

* Each unit starts the run off, having been offline `initial_hours_offline_h` (Q-026).
* `hours_in_state_h` counts hours on or hours off; `thermal_state` is hot while running
  and follows the start thresholds by hours offline otherwise. It has no cost effect yet.
* `transition(state, decision, inputs, unit)` is the only function that produces a state
  or a ledger entry.

## 12. Invariants implemented

3 (cost identity) and 4 (revenue identity) are recomputed from states and input prices,
not from the ledger entries' own quantity and price, and compared per unit-hour to the
cent. 6, 7, 8 as before; 8 now covers a non-empty ledger. 1, 2, 5 report `not_applicable`.

## 13. Start, no-load and commitment (milestone 2)

* **No-load fuel** is burned every hour the unit is on line, on top of the heat-rate curve:
  fuel per hour = no-load MMBtu + the curve integrated from 0 MW to the output.
* **Start cost** = start fuel x fuel price + other start cost, by thermal state: hot,
  warm or cold according to the hours offline before the start (0 h is hot).
* **Three-part offer.** Besides the one-part curve of §8, the offer carries start cost by
  thermal state, no-load cost per hour, minimum generation (Pmin) and the steps above
  Pmin, convexified on their own. A unit with less than Pmin available offers nothing.
* **Dispatch of a committed unit** = Pmin plus every step above Pmin priced strictly below
  the DA LBMP. A committed unit cannot run below Pmin.
* **Solvers.** Module `dp_commitment` selects the solver behind the ledger:
  * `price_taker` (off): §9, unchanged. It books no start or no-load cost and obeys no
    run-time limit. It is the baseline kept forever.
  * `dp` (on): dynamic program over (on/off, hours in state), with start cost by thermal
    state, no-load, minimum up and down times, and the dispatch rule above. It plans two
    local days with perfect foresight of the DA LBMP and the fuel price, keeps the first
    day, and plans again the next day from the state actually reached. Nothing is
    assumed after the horizon (terminal value 0); on the last day of the window the
    horizon is one day (Q-032, Q-033). A start or a shutdown is chosen only when it is
    strictly better. Ramp rate is not modelled (Q-031).
  * `price_taker_constrained`: the price-taker's rule made feasible. It wants to be on
    when the LBMP is above its lowest one-part offer step, but obeys minimum up and down
    times and pays start and no-load cost. Every DP run also executes this solver and
    the baseline, for comparison.
* **Booked** with any solver except the baseline: `no_load_cost` each hour on line;
  `start_cost` in the hour of a start, as two entries (start fuel MMBtu x fuel price, and
  1 start x other start cost).
* **Uplift (simplified make-whole, Q-030).** A commitment block runs from a start to the
  shutdown. In the first hour after it ends, `uplift = max(0, block costs - block DA
  revenue)` is booked, costs being fuel, no-load, VOM and start cost. A block still
  running when the window ends is not settled. Uplift is not part of the energy margin
  and the DP does not optimise for it.
* **Invariant 3** now expects, per hour, the sum of each fuel-side component rounded to
  the cent (curve fuel, no-load, start fuel, other start cost), recomputed from states.
* **Invariant 5** is checked on every planning day as three values of one planning
  problem (same horizon, starting state and prices): price-taker with constraints <= DP
  <= unconstrained. "Unconstrained" is the best of staying off and every corner of the
  true heat-rate curve in each hour, with no start cost, no-load or run-time limit. It
  equals the price-taker baseline up to the offer tick. Both orderings are properties of
  the solver, so a failure means the DP is wrong, not that the month was unusual.

## 14. Not yet written (rules land here before their milestone's numbers)

RT settlement and outages (M3), dual
fuel (M4), delivered gas (M5), capacity (M6), hedges (M7), simulation (M8), attribution (M9).
