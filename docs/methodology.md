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
* Delivered basis is not loaded. It is an `assumed` monthly adder in the plant config
  until milestone 5.

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

Implemented: 6 (time integrity, including exact coverage of the scenario window for every
location), 7 (provenance), 8 (reproducibility). Invariants 1-5 report `not_applicable`
until their milestone; they never report `pass` for something that was not checked.

## 8. Not yet written (rules land here before their milestone's numbers)

Marginal cost and offer curve (M1), commitment (M2), RT settlement and outages (M3), dual
fuel (M4), delivered gas (M5), capacity (M6), hedges (M7), simulation (M8), attribution (M9).
