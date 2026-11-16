"""Pydantic data contracts: every table row and record type the engine exchanges.

Conventions
-----------
* Units are in field names (`lbmp_usd_per_mwh`, `oil_inventory_bbl`). The only generic
  fields are `LedgerEntry.quantity` / `.price`, whose unit depends on the ledger line and
  is carried alongside in `quantity_unit` / `price_unit`.
* Every hourly record carries `ts_utc` (tz-aware UTC) and `ts_local` (tz-aware market
  local time, with its UTC offset). Both name the same instant; hours are hour-beginning.
* Money is `float` USD. Ledger amounts are rounded to the cent when the entry is written.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime, timedelta
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")

CENT_USD = 0.01
_HALF_CENT_USD = 0.005 + 1e-9


# --------------------------------------------------------------------------- time


class Stamped(BaseModel):
    """Base for hourly records: one instant, expressed in UTC and in market local time."""

    ts_utc: datetime
    ts_local: datetime

    @model_validator(mode="after")
    def _check_timestamps(self) -> "Stamped":
        if self.ts_utc.tzinfo is None or self.ts_local.tzinfo is None:
            raise ValueError("ts_utc and ts_local must be timezone-aware")
        if self.ts_utc.utcoffset() != timedelta(0):
            raise ValueError("ts_utc must have a zero UTC offset")
        if self.ts_utc != self.ts_local:
            raise ValueError("ts_utc and ts_local must be the same instant")
        return self


# --------------------------------------------------------------- plant parameters

Status = Literal["public", "assumed", "confirmed"]


class Param(BaseModel, Generic[T]):
    """A plant-parameter leaf with provenance. All five fields are required (brief §0.3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: T
    unit: str = Field(min_length=1)  # "MW", "MMBtu/MWh", "fraction", "enum", ...
    status: Status
    source: str = Field(min_length=1)
    as_of: Date


class HeatRatePoint(BaseModel):
    """One point of the incremental heat-rate curve."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    output_mw: float = Field(gt=0)
    incremental_heat_rate_mmbtu_per_mwh: float = Field(gt=0)


class StartSpec(BaseModel):
    """Cost of one start from a given thermal state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hours_offline_max_h: int | None  # upper bound of the state; None = cold (unbounded)
    start_fuel_mmbtu: float = Field(ge=0)
    start_other_cost_usd: float = Field(ge=0)


class Co2Factors(BaseModel):
    """CO2 emission factors in short tons per MMBtu of fuel burned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gas_t_per_mmbtu: float = Field(gt=0)
    oil_t_per_mmbtu: float = Field(gt=0)


class ParamLeafView(BaseModel):
    """A flattened plant-parameter leaf, for the Parameters screen and the assumed count."""

    path: str  # e.g. "units.U1.pmax_mw"
    value: object
    unit: str
    status: Status
    source: str
    as_of: Date


# ------------------------------------------------------------ market input tables


class LbmpRow(Stamped):
    """One hour x location of LBMP, hour-beginning. Prices in $/MWh.

    `congestion_usd_per_mwh` keeps NYISO's published sign, under which
    LBMP = energy + losses - congestion, so energy = lbmp - loss + congestion.
    """

    model_config = ConfigDict(extra="forbid")

    location: str  # NYISO name, e.g. "ROSETON___1", "HUD VL"
    location_ptid: int
    location_type: Literal["gen", "zone"]
    lbmp_usd_per_mwh: float
    energy_usd_per_mwh: float
    congestion_usd_per_mwh: float
    loss_usd_per_mwh: float
    as_of: Date  # retrieval date of the raw file (from data/raw.manifest.json)
    source_id: str  # sha256 prefix of the raw file the row came from

    @model_validator(mode="after")
    def _check_energy_identity(self) -> "LbmpRow":
        implied = self.lbmp_usd_per_mwh - self.loss_usd_per_mwh + self.congestion_usd_per_mwh
        if abs(implied - self.energy_usd_per_mwh) > _HALF_CENT_USD:
            raise ValueError(
                f"energy identity broken: lbmp - loss + congestion = {implied:.4f}, "
                f"energy = {self.energy_usd_per_mwh:.4f}"
            )
        return self


class LbmpDaRow(LbmpRow):
    """Row of curated table `lbmp_da` (day-ahead market)."""


class LbmpRtRow(LbmpRow):
    """Row of curated table `lbmp_rt` (NYISO time-weighted integrated hourly real-time)."""


class GasPriceRow(BaseModel):
    """Row of curated table `gas_price`: one published day x pricing point."""

    model_config = ConfigDict(extra="forbid")

    date: Date
    point: Literal["HENRY", "TRANSCO_Z6_NY", "IROQUOIS_Z2", "ASSUMED_BASIS"]
    price_usd_per_mmbtu: float
    as_of: Date
    source_id: str


# --------------------------------------------------------------- state & decisions

Fuel = Literal["gas", "oil"]
ThermalState = Literal["hot", "warm", "cold"]


class PlantState(Stamped):
    """State of one unit at the start of hour `ts_*`. Oil fields are station-level."""

    model_config = ConfigDict(extra="forbid")

    unit_id: str
    committed: bool
    hours_in_state_h: int = Field(ge=0)  # on-hours if committed, off-hours if not
    thermal_state: ThermalState  # derived from hours offline
    output_mw: float = Field(ge=0)
    fuel: Fuel | None
    oil_inventory_bbl: float = Field(ge=0)
    oil_permit_hours_used_ytd_h: float = Field(ge=0)
    available_mw: float = Field(ge=0)  # after derates / outages
    da_schedule_mw: float = Field(ge=0)  # binding DA award for this hour


class Decision(Stamped):
    """What the commitment solver decided for one unit and hour."""

    model_config = ConfigDict(extra="forbid")

    unit_id: str
    commit: bool
    target_mw: float = Field(ge=0)
    fuel: Fuel
    reason: str = Field(min_length=1)  # "spread 41.2 $/MWh > 0 and min-run binding"


# ------------------------------------------------------------------ offers & prices


class OfferBlock(BaseModel):
    """One step of the convexified offer curve: MW range and its offer price."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mw_from: float = Field(ge=0)
    mw_to: float = Field(gt=0)
    incremental_heat_rate_mmbtu_per_mwh: float = Field(gt=0)
    price_usd_per_mwh: float


class Offer(BaseModel):
    """A unit's DA offer for one local day: monotone non-decreasing steps from 0 MW."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str
    local_date: Date
    fuel: Fuel
    fuel_price_usd_per_mmbtu: float
    fuel_price_ref: str  # id of the gas/oil price row used
    available_mw: float = Field(ge=0)
    blocks: list[OfferBlock]

    @model_validator(mode="after")
    def _check_blocks(self) -> "Offer":
        previous_to, previous_price = 0.0, float("-inf")
        for block in self.blocks:
            if abs(block.mw_from - previous_to) > 1e-6 or block.mw_to <= block.mw_from:
                raise ValueError("offer blocks must be contiguous from 0 MW")
            if block.price_usd_per_mwh < previous_price - 1e-9:
                raise ValueError("offer prices must be non-decreasing")
            previous_to, previous_price = block.mw_to, block.price_usd_per_mwh
        if self.blocks and previous_to > self.available_mw + 1e-6:
            raise ValueError("offer exceeds available_mw")
        return self


class HourPrice(Stamped):
    """The DA price one unit sees in one hour, with the id of the row it came from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    da_lbmp_usd_per_mwh: float
    da_lbmp_ref: str


class DayPrices(BaseModel):
    """What the commitment solver sees for one unit and local day (23, 24 or 25 hours)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str
    local_date: Date
    hours: list[HourPrice] = Field(min_length=23, max_length=25)


class HourInputs(Stamped):
    """Exogenous inputs to `transition()` for one unit and hour."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str
    da_lbmp_usd_per_mwh: float
    da_lbmp_ref: str
    gas_price_usd_per_mmbtu: float  # delivered: index + basis adder; the price the plant pays
    gas_index_price_usd_per_mmbtu: float  # published index price (Henry Hub)
    gas_basis_adder_usd_per_mmbtu: float  # assumed monthly adder from the plant config (Q-028)
    gas_price_ref: str
    available_mw: float = Field(ge=0)

    @model_validator(mode="after")
    def _delivered_is_index_plus_basis(self) -> "HourInputs":
        expected = self.gas_index_price_usd_per_mmbtu + self.gas_basis_adder_usd_per_mmbtu
        if abs(self.gas_price_usd_per_mmbtu - expected) > 1e-9:
            raise ValueError("gas_price_usd_per_mmbtu must equal index price + basis adder")
        return self


# -------------------------------------------------------------------------- ledger

LedgerLine = Literal[
    "da_energy_rev",
    "rt_balancing",
    "uplift",
    "capacity_rev",
    "capacity_penalty",
    "ancillary_rev",
    "fuel_cost_gas",
    "fuel_cost_oil",
    "start_cost",
    "no_load_cost",
    "vom",
    "emissions_cost",
    "transport_demand_charge",
    "hedge_settlement",
    "collateral_delta",
    "fixed_om",
]
QuantityUnit = Literal["MWh", "MMBtu", "starts", "t", "kW-month", "h", "USD"]
PriceUnit = Literal["USD/MWh", "USD/MMBtu", "USD/start", "USD/t", "USD/kW-month"]


class LedgerEntry(Stamped):
    """One append-only ledger line for one unit and hour.

    `amount_usd` is signed (revenue positive, cost negative) and rounded to the cent.
    When `price` is given, |amount_usd| must equal |quantity x price| to the cent.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str
    line: LedgerLine
    quantity: float
    quantity_unit: QuantityUnit
    price: float | None
    price_unit: PriceUnit | None
    amount_usd: float
    ref: dict[str, str]  # ids of the input rows used, e.g. {"lbmp_da": "<source_id>:<ptid>:<ts_utc>"}

    @model_validator(mode="after")
    def _check_amount(self) -> "LedgerEntry":
        if (self.price is None) != (self.price_unit is None):
            raise ValueError("price and price_unit must be given together")
        if abs(round(self.amount_usd, 2) - self.amount_usd) > 1e-9:
            raise ValueError(f"amount_usd {self.amount_usd!r} is not rounded to the cent")
        if self.price is not None:
            implied = abs(self.quantity * self.price)
            if abs(implied - abs(self.amount_usd)) > _HALF_CENT_USD:
                raise ValueError(
                    f"amount_usd {self.amount_usd} does not match quantity x price = {implied:.4f}"
                )
        return self


class LedgerRollup(BaseModel):
    """A view over ledger entries: one period x unit x line. Never stored."""

    period: str  # ISO local hour, local date (YYYY-MM-DD) or local month (YYYY-MM)
    unit_id: str
    line: LedgerLine
    quantity: float
    quantity_unit: QuantityUnit
    amount_usd: float
    entry_count: int


# ----------------------------------------------------------------------- scenarios


class Modules(BaseModel):
    """Which engine modules a scenario switches on. All off in milestone 0."""

    model_config = ConfigDict(extra="forbid")

    dispatch: bool = False  # milestone 1
    dp_commitment: bool = False  # milestone 2
    rt_settlement: bool = False  # milestone 3
    outages: bool = False  # milestone 3
    dual_fuel: bool = False  # milestone 4
    gas_basis: bool = False  # milestone 5
    capacity: bool = False  # milestone 6
    hedges: bool = False  # milestone 7
    simulation: bool = False  # milestone 8


class Scenario(BaseModel):
    """Everything that defines a run. Time comes from here, never from the wall clock."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    start_date: Date  # first local day, inclusive
    end_date: Date  # last local day, inclusive
    plant_config: str  # path relative to the repository root
    market_config: str
    unit_ids: list[str] = Field(min_length=1)
    initial_hours_offline_h: int = Field(ge=0)  # each unit starts the run off, this long
    modules: Modules = Modules()
    seed: int

    @model_validator(mode="after")
    def _check_dates(self) -> "Scenario":
        if self.end_date < self.start_date:
            raise ValueError("end_date is before start_date")
        return self


# ---------------------------------------------------------------------- run result

InvariantStatus = Literal["pass", "fail", "not_applicable"]


class InvariantResult(BaseModel):
    """Outcome of one identity from brief §5."""

    invariant_id: int
    name: str
    status: InvariantStatus
    detail: str


class TableSummary(BaseModel):
    """Row count and coverage of one curated input table inside the scenario window."""

    table: str
    rows: int
    first_local: str | None
    last_local: str | None
    locations: list[str]
    snapshot_id: str


class RunMeta(BaseModel):
    """What makes a run reproducible, plus its invariant results."""

    run_id: str
    scenario: Scenario
    config_hash: str
    data_snapshot_ids: dict[str, str]
    code_version: str
    seed: int
    ledger_hash: str
    ledger_entry_count: int
    inputs: list[TableSummary]
    invariants: list[InvariantResult]
    assumed_parameter_count: int
    ledger_totals_usd: dict[str, float]  # sum of amount_usd by ledger line (view, not stored twice)
    energy_margin_usd: float  # DA + RT energy revenue less fuel, start, no-load, VOM, emissions


class RunResult(BaseModel):
    """Output of `engine.run.run(scenario)`."""

    meta: RunMeta
    ledger: list[LedgerEntry]
    states: list[PlantState]
    decisions: list[Decision]
    offers: list[Offer]
    hour_inputs: list[HourInputs]


class RunSummary(BaseModel):
    """One stored run, for pickers. Response item of GET /runs."""

    run_id: str
    scenario_name: str
    start_date: Date
    end_date: Date
    unit_ids: list[str]
    ledger_entry_count: int
    energy_margin_usd: float


class HourFlow(Stamped):
    """The flow-diagram payload for one unit and hour: every arrow's value, the ledger
    entries booked in the hour, and the input rows behind them (`ref`)."""

    unit_id: str
    state: PlantState
    decision: Decision
    da_lbmp_usd_per_mwh: float
    offered_mw: float
    offer_min_price_usd_per_mwh: float | None  # None when nothing is offered
    offer_max_price_usd_per_mwh: float | None
    offer_blocks: list[OfferBlock]
    da_schedule_mw: float
    output_mw: float
    gas_price_usd_per_mmbtu: float  # delivered: index + basis adder
    gas_index_price_usd_per_mmbtu: float
    gas_basis_adder_usd_per_mmbtu: float
    gas_burn_mmbtu: float
    da_energy_rev_usd: float
    fuel_cost_usd: float  # negative: a cost
    vom_usd: float  # negative: a cost
    hour_energy_margin_usd: float
    entries: list[LedgerEntry]
    input_refs: dict[str, str]  # input name -> row id, e.g. {"lbmp_da": "...", "gas_price": "..."}


class RunCreated(BaseModel):
    """Response of POST /runs."""

    run_id: str


class ParamsResponse(BaseModel):
    """Response of GET /params: the plant config, flattened, with status counts."""

    plant_name: str
    leaves: list[ParamLeafView]
    status_counts: dict[str, int]
    assumed_parameter_count: int
