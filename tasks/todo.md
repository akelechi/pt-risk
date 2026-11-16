# Milestone 0 — skeleton

Plan approved 2026-11-15 (assumptions Q-001..Q-017 in docs/open_questions.md).

- [x] Repo: git, pyproject, venv, .gitignore
- [x] `engine/contracts.py` — all pydantic contracts, units in names
- [x] `config/*.yaml` — plant (provenance on every leaf), market, scenario
- [x] `engine/plant/params.py` — loader that rejects leaves without provenance
- [x] `scripts/fetch_raw.py` — download + sha256 manifest (only wall-clock read)
- [x] `engine/inputs/` — NYISO DA/RT loaders (DST explicit), EIA Henry Hub, EIA-860/923 reference
- [x] `engine/ledger/` — append-only ledger, hash, roll-ups; reconcile (invariants 6, 7, 8)
- [x] `engine/run.py` — run(scenario) → RunResult
- [x] `api/main.py` — POST /runs, GET /runs/{id}, ledger, states, /params
- [x] Tests: contracts, provenance, time integrity (23/25 h), loaders, reproducibility, API
- [x] UI shell: static flow diagram, placeholder values, assumed count, generated types
- [x] Docs: milestones/00.md, methodology.md, open_questions.md, data/README.md, screenshot

## Review

Milestone 0 complete on branch `milestone-0`.

- 70 tests green; invariants 6, 7, 8 pass on the full 2025 base scenario; 1-5 report not_applicable.
- Curated: lbmp_da 26,280 rows, lbmp_rt 26,280 rows, gas_price 269 rows, eia_plant_reference 16 rows.
- Changed from the plan: energy tolerance is $0.031 (rounding bound), not $0.011; added
  `eia_plant_code` identifier, `engine/inputs/store.py`, `engine/inputs/build.py`, `engine/version.py`,
  `scripts/export_openapi.py`.
- Not verified: light mode rendering (headless Chrome followed the dark system setting).
- New open questions: Q-018 (EIA vs brief parameters), Q-019..Q-022.


# Milestone 1 — price-taker dispatch, gas only, DA only, U1, January 2025

- [x] Config: Q-018 (EIA Pmax/Pmin), scenario.m1.yaml, initial_hours_offline_h, offer tick, gas staleness
- [x] `engine/plant/cost.py` — true blocks, convexify, fuel burn, marginal cost, thermal state
- [x] `engine/market/prices.py`, `offer.py`, `settlement.py`; `engine/plant/commitment.py` (price_taker)
- [x] `engine/plant/state.py` — initial_state, transition (only writer of entries)
- [x] `engine/run.py` — day loop; ledger totals and energy margin in run meta
- [x] Invariants 3 and 4 (recomputed from states and inputs)
- [x] API: run summaries, /flow, /hour/{ts}
- [x] Tests: hand-worked day (xlsx), cost, commitment, settlement, real January, DST days, API
- [x] UI: hour scrubber, plant on/off, live arrows; exercised in Chrome
- [x] Docs: milestones/01.md, methodology §8-§12, open questions Q-023..Q-029

## Review

- January 2025 energy margin, U1: $18,408,203.95 (Henry Hub + assumed $3 basis, Q-028 answered 2026-11-16; first cut at Henry flat was $29,328,063.66).
- Flow screen: DA price vs offer plot over the run (`ui/components/PriceStrip.tsx`), click/drag to select an hour.
- UI restyled to `docs/brand.md` tokens (`ui/styles/tokens.css`); no literal colors in components.
- 117 tests green; invariants 3, 4, 6, 7, 8 pass on the real month.
- Not done: arrow click-through panel; CO2 cost; light mode still not visually verified.

## Milestones 2-4 (owner: "lets then do till milestone 4", 2026-11-16)

Each on its own branch, in order, with tests, note, methodology, questions, screenshot.

- [x] M2 `milestone-2`: no-load, start cost by thermal state, three-part offer, DP (2-day
      rolling), price-taker with run-time limits, uplift, invariant 5, commitment timeline.
      January 2025 U1: DP 16,609,577.01 with 4 starts; baseline 18,408,203.95 with 14.
- [x] M3 `milestone-3`: RT settlement on deviations, seeded daily outages, invariants 1 and 4.
      January 2025 U1, seed 20250101: cost of outages 1,410,633.56 (one costly day of three drawn).
- [x] M4 `milestone-4`: oil price table, fuel choice, inventory, permit hours, barge, invariant 2.
      January 2025 U1: oil chosen 4 days, burned 2 (39 h), margin captured 157,835.53.

### Review (milestones 2-4)

- All eight invariants are checked and pass on the milestone 4 January run.
- Carried forward, not built: Ledger / Commitment / Parameters screens, arrow click-through,
  two-unit dual fuel, economic RT deviations, ramp rate, CO2 cost.
