# Roseton Ledger — build brief for Claude Code

You are building **a per-plant commercial model** of a dual-fuel steam generating station (Roseton, NYISO Zone G) as a state machine plus a ledger, with a UI that shows the flow of offers, bids, prices, dispatch and cash **with live values on the arrows**. The engine is the product. The UI exists to make the engine legible. This file is the contract; read it fully before writing code, and re-read the "Invariants" section before every commit.

This is not a digital twin of the physics. It is a model of the plant as a commercial object: every state variable that turns a price into a dollar, every decision that changes that state, and every cash line that results.

---

## 0. Ground rules

1. **Engine first, UI second, always.** No UI feature is started until the engine behind it has a passing test. The UI reads the ledger; it never computes revenue.
2. **One source of truth per fact.** Market inputs, plant parameters and decisions live in three separate places (see §3). Nothing is hard-coded in code that belongs in config or data.
3. **Every parameter carries provenance.** Each plant parameter has `value`, `unit`, `status ∈ {public, assumed, confirmed}`, `source`, `as_of`. The UI shows status as a badge. A parameter without a source is a build error.
4. **Reproducible to the dollar.** Every run records: config hash, input data snapshot ids, code version, random seed. Re-running a saved run must reproduce its ledger exactly (`tests/test_reproducibility.py`).
5. **Public data only.** NYISO public LBMPs, EIA Henry Hub, EIA-860/923, published auction results. No vendor feeds, no employer data. If a number is not public, it is `assumed` and flagged.
6. **Increments ship whole.** Each milestone (§6) ends with: engine tests green, ledger reconciles (§5), one UI view updated, a `docs/milestones/NN.md` note stating what changed in the numbers and why. Do not start milestone N+1 with milestone N's tests red.
7. **Small, typed, boring code.** Python 3.12, `pydantic` models for every data contract, `pandas`/`numpy` for series, no clever metaprogramming. Functions over classes except for the state machine and the ledger. Docstrings state units.
8. **Units in names.** `price_usd_per_mwh`, `heat_rate_mmbtu_per_mwh`, `oil_inventory_bbl`, `start_cost_usd`. Never bare `price`.
9. **Ask before inventing.** If a rule of the market is unclear, write the question in `docs/open_questions.md` with your best assumption and proceed; do not silently decide.

---

## 1. What the system models

```
MARKET INPUTS                PLANT (state machine)                 LEDGER
─────────────                ─────────────────────                 ──────
DA LBMP (node/zone, hourly)  commitment state (off/on, hrs)        DA energy revenue
RT LBMP (hourly)             thermal state (hot/warm/cold)         RT balancing (±)
delivered gas $/MMBtu        output MW, fuel in use                uplift / make-whole
oil $/MMBtu, inventory       oil inventory bbl, permit hours       capacity revenue / penalties
capacity price $/kW-mo       availability / derate                 ancillary revenue
RGGI $/t, forwards as-of     DA schedule (binding)                 fuel cost by fuel
weather (HDD/CDD)            hedge positions                       transport demand charge
                                                                   emissions cost, VOM
          ┌──────────── DECISIONS (daily → hourly) ───────────┐   starts (count, $)
          │ DA offer → schedule (commitment solver)           │   hedge settlements
          │ fuel choice · RT deviation · nominations          │   collateral posted
          └───────────────────────────────────────────────────┘   fixed costs (monthly)
```

The DA market is modeled as **a price-taker clearing**: the plant's offer is cleared against the published DA LBMP (we do not simulate the ISO's SCUC). The UI draws the market as a node with offers arriving from the plant and bids arriving from load-serving entities, with the published LBMP as the market's output; the engine treats the LBMP as exogenous.

---

## 2. Repository layout

```
roseton-ledger/
├── CLAUDE.md                     ← this file
├── pyproject.toml
├── config/
│   ├── plant.roseton.yaml        ← plant parameters with provenance (§3.2)
│   ├── market.nyiso.yaml         ← settlement rules, blocks, caps, time zone
│   └── scenario.base.yaml        ← which inputs, which modules on, seed
├── data/
│   ├── raw/                      ← downloaded public files, never edited
│   ├── curated/                  ← parquet, one table per §3.1 contract, with as_of
│   └── README.md                 ← every file: source URL, license, retrieval date
├── engine/
│   ├── contracts.py              ← pydantic models: every table and record type
│   ├── inputs/                   ← loaders → curated tables (nyiso.py, eia.py, curves.py)
│   ├── plant/
│   │   ├── params.py             ← typed Plant with provenance
│   │   ├── cost.py               ← marginal cost curve, start/no-load by state, fuel choice
│   │   ├── state.py              ← PlantState + transition()
│   │   └── commitment.py         ← commitment solvers: price_taker(), dp()
│   ├── market/
│   │   ├── offer.py              ← build_offer(plant, prices, date) → Offer
│   │   └── settlement.py         ← settle_hour(): DA, RT, uplift, capacity, penalties
│   ├── hedges/                   ← book.py (positions), value.py (MTM), settle.py
│   ├── ledger/
│   │   ├── ledger.py             ← append-only hourly entries → monthly roll-ups
│   │   └── reconcile.py          ← identities (§5)
│   ├── simulate/                 ← price paths (milestone 8+), outage draws
│   ├── attribution/              ← bridge between two runs (milestone 9)
│   └── run.py                    ← run(scenario) → RunResult (ledger, states, meta)
├── api/                          ← FastAPI: /runs, /runs/{id}/ledger, /runs/{id}/hour/{t}
├── ui/                           ← Next.js app (§7)
├── tests/
│   ├── test_cost.py  test_commitment.py  test_settlement.py  test_reconcile.py
│   ├── test_reproducibility.py   test_contracts.py
│   └── fixtures/                 ← tiny hand-computed cases (one day, known answers)
└── docs/
    ├── milestones/               ← NN.md per milestone: what changed, numbers before/after
    ├── open_questions.md
    └── methodology.md            ← kept current; written before numbers, not after
```

---

## 3. Data contracts

### 3.1 Market inputs (curated tables; all with `as_of` and `source_id`)

| table | grain | columns |
|---|---|---|
| `lbmp_da` | hour × location | `ts_local`, `location`, `lbmp`, `energy`, `congestion`, `loss` ($/MWh) |
| `lbmp_rt` | hour × location | same (hourly average of 5-min) |
| `gas_price` | day × point | `date`, `point` (HENRY, TRANSCO_Z6_NY, IROQUOIS_Z2, ASSUMED_BASIS), `usd_per_mmbtu` |
| `oil_price` | day | `date`, `usd_per_mmbtu`, `usd_per_bbl` |
| `capacity_price` | month × locality | `month`, `locality` (G-J), `usd_per_kw_month` |
| `rggi_price` | day | `date`, `usd_per_ton` |
| `forward_curve` | as_of × month × block × location | `as_of`, `delivery_month`, `block` (5x16/2x16/7x8), `location`, `price` |
| `weather` | day × station | `date`, `station`, `tmin_f`, `tmax_f`, `hdd`, `cdd` |

Time: store `ts_local` as America/New_York **and** `ts_utc`; handle 23/25-hour DST days explicitly; never drop or duplicate an hour silently (test it).

### 3.2 Plant parameters (`config/plant.roseton.yaml`)

Every leaf has the five provenance fields. Example:

```yaml
units:
  - id: U1
    pmax_mw:          {value: 600,   unit: MW,          status: assumed,  source: "EIA-860 nameplate ~600; confirm net", as_of: 2026-11-15}
    pmin_mw:          {value: 150,   unit: MW,          status: assumed,  source: "typical 25% of Pmax for 1970s steam", as_of: 2026-11-15}
    heat_rate_curve:  # incremental heat rate by output; monotone handling in cost.py
      value: [{mw: 150, ihr: 11.4}, {mw: 300, ihr: 10.1}, {mw: 450, ihr: 10.0}, {mw: 600, ihr: 10.8}]
      unit: MMBtu/MWh; status: assumed; source: "shape typical; level from EIA-923 annual avg ~10.5"; as_of: 2026-11-15
    no_load_mmbtu_per_hr: {value: 400, unit: MMBtu/h, status: assumed, source: "intercept of I/O curve, typical", as_of: 2026-11-15}
    start:
      hot:   {hours_offline_max: 12, fuel_mmbtu: 1500, other_usd: 8000,  status: assumed, source: "typical", as_of: 2026-11-15}
      warm:  {hours_offline_max: 72, fuel_mmbtu: 3000, other_usd: 15000, status: assumed, source: "typical", as_of: 2026-11-15}
      cold:  {hours_offline_max: null, fuel_mmbtu: 5000, other_usd: 25000, status: assumed, source: "typical", as_of: 2026-11-15}
    min_up_hours:    {value: 8, ...}
    min_down_hours:  {value: 6, ...}
    ramp_mw_per_min: {value: 5, ...}
    vom_usd_per_mwh: {value: 3.0, ...}
    efor:            {value: 0.10, unit: fraction, status: assumed, source: "old steam typical", as_of: 2026-11-15}
fuel:
  gas_point:         {value: TRANSCO_Z6_NY, status: assumed, source: "nearest major index; plant's actual point to confirm"}
  gas_basis_adder_by_month: {value: {1: 3, 2: 3, 3: 3, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1, 9: 1, 10: 1, 11: 3, 12: 3}, unit: $/MMBtu, status: assumed, ...}
  oil_heat_rate_penalty:     {value: 0.03, unit: fraction, status: assumed, ...}
  oil_tank_capacity_bbl:     {value: 1_000_000, status: assumed, source: "order of magnitude; confirm", ...}
  oil_mmbtu_per_bbl:         {value: 6.3, status: public, source: "No.6 fuel oil heat content"}
  oil_permit_hours_per_year: {value: 720, status: assumed, ...}
  barge_lead_days:           {value: 5, status: assumed, ...}
  transport_demand_charge_usd_per_mmbtu_day: {value: 0.0, status: assumed, source: "unknown whether FT held; 0 until confirmed"}
emissions:
  co2_t_per_mmbtu: {gas: 0.0531, oil: 0.0741, status: public, source: "EPA factors"}
capacity:
  ucap_mw:          {value: 1100, status: assumed, source: "ICAP 1200 × (1 − EFORd)"}
  locality:         {value: "G-J", status: public, source: "NYISO locality map"}
fixed:
  fixed_om_usd_per_kw_year: {value: 45, status: assumed, ...}
```

The loader rejects any leaf missing `status` or `source`.

### 3.3 Decisions and state (engine/plant/state.py)

```python
class PlantState(BaseModel):
    ts: datetime
    committed: bool
    hours_in_state: int          # on-hours if committed, off-hours if not
    thermal_state: Literal["hot", "warm", "cold"]   # derived from hours_offline
    output_mw: float
    fuel: Literal["gas", "oil", None]
    oil_inventory_bbl: float
    oil_permit_hours_used_ytd: float
    available_mw: float          # after derates/outages
    da_schedule_mw: float        # binding DA award for this hour

class Decision(BaseModel):      # produced by the commitment solver per hour
    ts: datetime
    commit: bool
    target_mw: float
    fuel: Literal["gas", "oil"]
    reason: str                  # human-readable: "spread 41.2 > 0 and min-run binding"
```

`transition(state, decision, inputs) -> (new_state, LedgerEntries)` is the only function that mutates state and the only function that writes ledger entries. Pure, deterministic, unit-tested.

### 3.4 Ledger (engine/ledger/ledger.py)

Append-only hourly entries:

```python
class LedgerEntry(BaseModel):
    ts: datetime
    unit_id: str
    line: Literal[
      "da_energy_rev", "rt_balancing", "uplift", "capacity_rev", "capacity_penalty", "ancillary_rev",
      "fuel_cost_gas", "fuel_cost_oil", "start_cost", "no_load_cost", "vom", "emissions_cost",
      "transport_demand_charge", "hedge_settlement", "collateral_delta", "fixed_om"]
    quantity: float; quantity_unit: str      # MWh, MMBtu, starts, t, …
    price: float | None; price_unit: str | None
    amount_usd: float
    ref: dict                                 # ids of the inputs used (lbmp row, gas row, hedge id)
```

Monthly roll-ups are views over this table; nothing is stored twice.

---

## 4. Engine semantics (the rules the code must implement)

**Marginal cost** (`cost.py`): `c(q) = IHR(q) × P_fuel + VOM + ER_fuel × IHR(q) × P_CO2` with `P_fuel = min(delivered_gas, oil)` per MMBtu; the offer curve is the convexified (monotone non-decreasing) step curve of `c` over `[Pmin, Pmax]`. Start cost = start fuel × P_fuel + other; no-load = no-load MMBtu × P_fuel. Thermal state from hours offline per the config thresholds.

**Commitment** (`commitment.py`), two solvers behind one interface `solve(prices_24h, state0, plant) -> list[Decision]`:
- `price_taker`: run block if `price > c + VOM`, no constraints. Kept forever as the baseline to measure against.
- `dp`: dynamic program over (committed, hours_in_state) with start cost by thermal state, min up/down, Pmin/Pmax, dispatch at the profit-maximizing MW on the offer curve. Horizon: 48 h rolling, step 24 h, perfect foresight on DA LBMP (document the haircut as a scenario option).

**Settlement** (`settlement.py`), per hour: `da_energy_rev = da_mw × da_lbmp`; `rt_balancing = (actual_mw − da_mw) × rt_lbmp`; uplift = max(0, offered start + no-load + energy costs over the commitment − DA revenue over the commitment) applied once per commitment block (simplified BPCG; flag as assumption); capacity revenue monthly = `ucap_mw × price × 1000`; penalties only when a scenario declares an emergency event.

**Availability**: deterministic availability factor in milestones 1–2; Bernoulli daily outage draws (seeded) from milestone 3; correlated with HDD from milestone 8 (`p_outage = base × (1 + k × max(0, HDD − threshold))`).

**Dual fuel**: fuel choice per day by cheaper $/MMBtu; oil burn draws inventory down (bbl = MMBtu / 6.3); barge replenishes to a target with lead time; permit hours cap oil burn; when oil is unavailable, gas is used regardless of price (or the unit sits if gas > spread).

**Hedges** (milestone 6): positions `{instrument, index_location, block, start, end, mw, fixed_price, counterparty, threshold_usd}`; monthly settlement vs block-average index; daily MTM vs forward curve as-of; collateral = max(0, −MTM − threshold).

---

## 5. Invariants (tests, run on every commit; reconcile.py)

1. **Energy balance:** Σ hourly `actual_mw` = Σ (`da_schedule_mw` + deviation). Deviation line sums to RT balancing / RT price per hour.
2. **Fuel balance:** MMBtu burned = Σ (IHR × MWh) + no-load hours × no-load + start fuel; oil bbl drawn = oil MMBtu / 6.3; inventory never negative; permit hours never exceeded.
3. **Cost identity:** `fuel_cost_* + start_cost + no_load_cost` equals MMBtu × price by fuel, to the cent.
4. **Revenue identity:** energy revenue = `da_mw × da_lbmp + (actual − da) × rt_lbmp`, per hour, per unit.
5. **Margin bound:** DP solver margin ≥ price-taker-with-constraints margin on every day (DP is optimal); DP margin ≤ unconstrained price-taker margin.
6. **Time integrity:** every local day has 23/24/25 hours matching DST; no duplicate `ts_utc`.
7. **Provenance:** no plant parameter without `status` and `source`; the UI shows a count of `assumed` parameters on every screen.
8. **Reproducibility:** `run(scenario)` twice → identical ledger hash.

A failing invariant blocks the commit. Fixture days in `tests/fixtures/` have answers computed by hand in a spreadsheet checked into the repo.

---

## 6. Milestones (build in this order; each is a PR)

| # | Add | Engine acceptance | UI view touched | Number to report in `docs/milestones/NN.md` |
|---|---|---|---|---|
| 0 | Skeleton: contracts, config loader with provenance, NYISO + EIA loaders, empty ledger, API returning a run id, UI shell with the flow diagram (static) | loaders produce curated tables; DST test passes | Flow diagram renders with placeholder values | row counts, date ranges |
| 1 | Price-taker dispatch, gas only, DA only, one unit, one month | invariants 3,4,6,7,8 | Hour scrubber lights the plant node on/off; arrows show DA price, offer, MW | Jan-2025 energy margin |
| 2 | DP commitment with start/min-run; no-load | invariant 5; starts count | Commitment timeline strip; start-cost arrow appears | margin and starts: DP vs price-taker |
| 3 | RT settlement on deviations + seeded daily outages | invariants 1,4 | RT arrow with ± amount; outage marker | cost of outages in a January |
| 4 | Dual fuel: oil price, inventory, permit hours, barge | invariant 2 | Fuel switch indicator; inventory gauge | days on oil, margin captured on them |
| 5 | Delivered gas basis (assumed adder → real index when available) | — | Gas price arrow decomposed Henry + basis | implied HR against Henry vs delivered |
| 6 | Capacity revenue + penalty events; fixed O&M | — | Revenue mix donut (energy / capacity / other) | energy vs capacity share |
| 7 | Hedge book: swap, HR call; monthly settlement; MTM; collateral | hedge settles vs block index to the cent | Hedge node with settlement arrow; collateral gauge | hedged vs unhedged monthly margin |
| 8 | Forward curves as-of + price-path simulator (OU + seasonal jumps); outages correlated with HDD | path count convergence test | Distribution panel; P5/P50/P95 on the ledger | P5 energy margin, with and without jumps |
| 9 | Attribution bridge between two runs | bridge sums to delta within noise | Waterfall view | one real bridge, two runs a month apart |

Do not reorder. Do not merge two milestones. Each milestone's doc states what you expected the numbers to do, what they did, and what you learned.

---

## 7. UI (ui/, Next.js + TypeScript; charts with a lightweight SVG/Canvas layer, no heavy chart library unless justified)

**Purpose:** make one hour of the engine legible in one screen, and one month legible in one scroll. The UI is a viewer over `RunResult`; it holds no business logic.

**Screens**

1. **Flow** (home). A fixed diagram, left to right:
   `LSE bids ──► [ DA MARKET ] ◄── Plant offer`  → published DA LBMP → `[ PLANT ]` (state badge: off / hot / warm / cold; fuel; MW; inventory gauge) → `[ RT MARKET ]` (deviation ± MW, RT LBMP) → `[ LEDGER ]` (the hour's lines).
   Fuel supply enters the plant from below: `Gas (Henry + basis)`, `Oil (tank)`, with prices on the arrows. `Hedge book` sits to the right of the ledger with its settlement arrow (hidden until milestone 7).
   **Every arrow carries its value for the selected hour** (price, MW, $). Clicking an arrow opens the ledger entries and the input rows (`ref`) behind it. A scrubber at the bottom moves through hours; play at 1 h / 100 ms. Icons: simple line icons for market, plant, tank, ledger; never decorative illustration.
2. **Ledger.** Monthly table by line; expand to days to hours; every cell traces to entries. Totals reconcile visibly (identities from §5 shown as green checks).
3. **Commitment.** 24 × N heatmap of on/off/MW with starts marked and the DA LBMP overlaid; toggle DP vs price-taker to see the difference.
4. **Parameters.** The plant config as a table with status badges and sources; count of `assumed` in the header of every screen.
5. **Distribution** (milestone 8+). Histogram of monthly/annual margin across paths with P5/P50/P95, hedged vs unhedged.
6. **Bridge** (milestone 9). Waterfall between two selected runs.

**Design direction.** See `docs/brand.md`: it is the contract for color, type, layout and elevation, and for which token each UI role uses. Its tokens block is copied verbatim into `ui/styles/tokens.css`; every color in components is one of those variables, never a literal. Every screen works at 1280 wide and degrades to a phone by stacking.

**Accessibility & craft:** keyboard scrubber, focus states, `prefers-reduced-motion` honored, aria labels on the diagram's nodes and arrows naming their current values.

---

## 8. API (api/)

- `POST /runs` with a scenario → run id (runs synchronously for ≤ 1 year; background job beyond).
- `GET /runs/{id}` meta (config hash, seeds, data snapshot ids, invariant results).
- `GET /runs/{id}/ledger?grain=hour|day|month`
- `GET /runs/{id}/hour/{ts}` → the flow-diagram payload: every arrow's value plus the `ref` rows.
- `GET /runs/{id}/states`
- `GET /params` → plant config with provenance.
- `GET /runs/{a}/bridge/{b}` (milestone 9).

Responses are the pydantic contracts serialized; the UI types are generated from the OpenAPI schema, never hand-written.

---

## 9. Definition of done, per PR

- Tests green, including invariants on the fixtures and on one full real month.
- `docs/milestones/NN.md` written with before/after numbers.
- `docs/methodology.md` updated for any new rule.
- Any new assumed parameter added to `open_questions.md` with how it would be confirmed.
- UI screenshot of the touched view committed under `docs/screens/`.

---

## 10. Things you must not do

- Simulate the ISO's optimization. The plant is a price-taker against published LBMPs.
- Put a number in code that belongs in config.
- Compute any dollar figure in the UI.
- Fetch vendor or employer data, or hard-code a value you remember from one.
- Start a milestone's UI before its engine tests pass.
- Replace the price-taker baseline; it stays as the comparison forever.
- Use `datetime.now()` anywhere in the engine; time comes from the scenario.

Begin with milestone 0. Before writing code, print the planned file list and the pydantic contracts for review.
