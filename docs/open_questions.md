# Open questions

Format: question, best assumption (what the code does today), how it would be confirmed,
first milestone affected. Status: `open` until answered; answers are recorded here.

## Build and data

**Q-001 Repo root and git** (M0, open). Folder is `PT_Risk`, brief says `roseton-ledger`.
- Assumption: build at the `PT_Risk` root; local git, one branch per milestone
  (`milestone-0`), code version = git commit. No remote.
- Confirm: owner.

**Q-002 Date range** (M0, open).
- Assumption: calendar 2025 (covers January 2025 for M1 and both DST days).
- Confirm: owner.

**Q-003 Raw files in git** (M0, open).
- Assumption: `data/raw/` ignored; `data/raw.manifest.json` (url, sha256, retrieval time)
  committed; curated parquet committed.
- Confirm: owner.

**Q-004 Energy component and congestion sign** (M0, resolved by test).
- Assumption: `energy = lbmp - loss + congestion`, congestion stored with NYISO's sign.
- Evidence: across all 15 zones on congested days this gives one energy price per hour to
  within $0.02; the opposite sign differs by more than $10/MWh. Tariff citation still to add.

**Q-005 Settlement location** (M1, open).
- Assumption: each unit settles at its own generator bus LBMP; Zone G is reference only.
- Note: both buses had identical LBMPs in every hour of 2025.
- Confirm: NYISO tariff / settlement manual.

**Q-006 RT hourly price** (M3, open).
- Assumption: NYISO's published time-weighted integrated hourly RT LBMP, not a
  recomputed average of 5-minute prices.
- Confirm: owner; NYISO settles RT at interval level, so this is a simplification.

**Q-012 Henry Hub on non-trading days** (M1, open).
- Assumption: table holds published days only; the engine will use the last published
  price on or before the gas day.
- Confirm: owner; a gas-day / weekend-strip convention could replace it.

**Q-013 EIA vintage** (M0, open).
- Assumption: EIA-860 and EIA-923 report year 2024. 2025 files are also published.
- Confirm: owner.

**Q-019 `as_of` is a UTC date** (M0, open).
- Assumption: `as_of` = UTC date of retrieval (2026-11-16 for this snapshot, which was
  2026-11-15 local).
- Confirm: owner, if local dates are preferred.

**Q-020 Energy agreement tolerance** (M0, open).
- Assumption: $0.031/MWh across locations, from rounding of three published terms.
- Confirm: owner; observed maximum in 2025 is $0.02.

**Q-022 Blank Henry Hub rows** (M0, open).
- Assumption: a dated row with no price inside the requested range is refused (build
  stops); outside the range it is ignored. One exists in history (2018-01-05).
- Confirm: owner; alternative is to treat it as an unpublished day.

## Contracts

**Q-007 Two units** (M0, open).
- Assumption: per-unit state, decision and ledger rows keyed by `unit_id`; oil inventory
  and permit hours are station-level and repeated on each unit's state.
- Confirm: owner.

**Q-008 Units in names vs the brief's column names** (M0, open).
- Assumption: table columns carry units (`lbmp_usd_per_mwh`, `price_usd_per_mmbtu`);
  `LedgerEntry.quantity` / `.price` stay generic with `quantity_unit` / `price_unit`.
  Plant leaves renamed: `gas_basis_adder_usd_per_mmbtu_by_month`,
  `oil_heat_rate_penalty_fraction`.
- Confirm: owner.

**Q-009 Money type** (M0, open).
- Assumption: `float` in the engine; ledger amounts rounded half-even to the cent at
  write; roll-ups summed in Decimal.
- Confirm: owner; alternative is Decimal throughout.

**Q-010 Provenance on every leaf** (M0, open).
- Assumption: all five fields required everywhere. Leaves that lacked `unit` or `as_of`
  in the brief were given explicit units and `as_of: 2026-11-15`; each start state and the
  CO2 factors are one leaf each.
- Confirm: owner.

**Q-011 `as_of` without the wall clock** (M0, open).
- Assumption: only `scripts/fetch_raw.py` reads the clock; a test scans `engine/` and
  `api/` for clock calls.
- Confirm: owner.

**Q-014 Run id and storage** (M0, open).
- Assumption: run id = 12 hex of hash(config hash, snapshot ids, code version, seed);
  results stored as JSON under `runs/{id}/` (ignored by git).
- Confirm: owner.

**Q-021 Invariant 8 inside `run()`** (M0, open).
- Assumption: every run executes the scenario twice and compares ledger hashes. This
  doubles engine time once dispatch exists.
- Confirm: owner; alternative is to check it only in tests and on request.

## Plant parameters

**Q-018 EIA values vs the brief's placeholders** (M1, answered 2026-11-15, partly open).
- Answer applied: `pmax_mw` = EIA net summer capacity (614.8 / 607.7) and `pmin_mw` = 140,
  status `public`; heat-rate break points moved to 140 and Pmax.
- Still open: the heat-rate LEVEL. Kept at the brief's values (`assumed`), because the
  EIA annual average overstates full-load heat rate. Re-levelling to 11.68 lowers the
  January 2025 margin by $1.82M (see docs/milestones/01.md). Owner to confirm which.
- Also open: summer (614.8) vs winter (613.2) capacity for winter months.
- Finding: EIA-860 2024 reports nameplate 621 MW per unit, net summer capacity
  614.8 MW (U1) / 607.7 MW (U2), minimum load 140 MW. EIA-923 2024 implies an annual
  average heat rate of 11.68 MMBtu/MWh (2,763,532 MMBtu / 236,658 MWh). The config holds
  the brief's 600 MW, 150 MW and a curve levelled at ~10.5.
- Assumption: config unchanged, still `assumed`.
- Proposal: set `pmax_mw` to EIA net summer capacity and `pmin_mw` to 140 with status
  `public`, and re-level the heat-rate curve so its average matches 11.68. Note that an
  annual average at a ~2% capacity factor includes many starts and low-load hours, so it
  overstates the full-load heat rate.
- Confirm: owner.

**All other `assumed` leaves** (33 of 36). Each would be confirmed as follows:
- Heat-rate curve, no-load, start fuel and cost, min up/down, ramp, VOM, EFOR: plant
  operating data or NYISO reference levels; EPA CAMPD hourly heat input and gross load is
  a public cross-check for heat rate and starts.
- Gas point, basis adder, transport demand charge: the plant's gas supply arrangement;
  public pipeline index data if available (M5).
- Oil tank capacity, permit hours, barge lead time: Title V air permit and plant records.
- UCAP: NYISO ICAP/UCAP reports. Fixed O&M: owner.

## Engine rules (not yet built)

**Q-015 Price-taker rule double-counts VOM** (M1, answered 2026-11-15: run if `price > c`). The brief says run if
`price > c + VOM`, but `c` already includes VOM.
- Assumption: run if `price > c`.
- Confirm: owner.

**Q-016 Heat-rate curve interpretation** (M1, answered 2026-11-15: block-end steps, convexified). The example points are non-monotone.
- Assumption: each point is the incremental heat rate of the block ending at that output;
  the 150 MW point prices the Pmin block; the curve is convexified in `cost.py`.
- Confirm: owner.

**Q-017 UI ordering inside a milestone** (M0, resolved by practice).
- Engine, loaders and API were built and tested first; the UI shell was added last.

## Raised in milestone 1

**Q-023 Gas day** (M1, open).
- Assumption: the gas day is the local calendar day; every hour of a local day uses that
  day's price.
- Confirm: owner; the NAESB gas day runs 9:00 to 9:00 Central, and weekend gas trades as
  a strip on Friday.

**Q-024 CO2 cost** (M1, open). The marginal-cost formula has a CO2 term, but no milestone
loads an RGGI price table.
- Assumption: CO2 price is zero; no `emissions_cost` is booked and offers exclude it.
- Proposal: load RGGI auction clearing prices with milestone 5 or 6.
- Confirm: owner.

**Q-025 Deterministic availability** (M1, open).
- Assumption: available MW = Pmax x (1 - EFOR) in every hour (553.32 MW for U1); the
  offer curve is truncated there. Removing the derate adds $3.2M to January.
- Confirm: owner; alternative is full Pmax until outages are drawn in milestone 3.

**Q-026 Initial state** (M1, open).
- Assumption: each unit starts the run off, 168 hours offline (cold); set per scenario.
  No effect until start costs exist (milestone 2).
- Confirm: owner.

**Q-027 Offer price tick** (M1, open).
- Assumption: offer step prices are rounded to $0.01/MWh, so a tie with the LBMP is well
  defined and does not depend on floating-point noise.
- Confirm: NYISO bid rules.

**Q-028 Fuel price before milestone 5** (M1, open).
- Assumption: delivered gas = Henry Hub flat while module `gas_basis` is off; the config's
  assumed monthly basis adder is NOT applied yet.
- Consequence: the January margin is far above anything plausible (see milestone note).
- Confirm: owner; alternative is to apply the assumed adder from milestone 1.

**Q-029 Run result size** (M1, open).
- Assumption: a stored run keeps states, decisions, hourly inputs and offers as JSON.
  One unit-month is about 1.5 MB; a two-unit year would be roughly 35 MB.
- Confirm: owner; alternative is parquet per run before longer runs are stored.
