# Milestone 0 — skeleton

Plan approved 2026-11-15 (assumptions Q-001..Q-017 in docs/open_questions.md).

- [ ] Repo: git, pyproject, venv, .gitignore
- [ ] `engine/contracts.py` — all pydantic contracts, units in names
- [ ] `config/*.yaml` — plant (provenance on every leaf), market, scenario
- [ ] `engine/plant/params.py` — loader that rejects leaves without provenance
- [ ] `scripts/fetch_raw.py` — download + sha256 manifest (only wall-clock read)
- [ ] `engine/inputs/` — NYISO DA/RT loaders (DST explicit), EIA Henry Hub, EIA-860/923 reference
- [ ] `engine/ledger/` — append-only ledger, hash, roll-ups; reconcile (invariants 6, 7, 8)
- [ ] `engine/run.py` — run(scenario) → RunResult
- [ ] `api/main.py` — POST /runs, GET /runs/{id}, ledger, states, /params
- [ ] Tests: contracts, provenance, time integrity (23/25 h), loaders, reproducibility, API
- [ ] UI shell: static flow diagram, placeholder values, assumed count, generated types
- [ ] Docs: milestones/00.md, methodology.md, open_questions.md, data/README.md, screenshot

## Review

(filled in at the end of the milestone)
