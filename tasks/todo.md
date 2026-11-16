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
