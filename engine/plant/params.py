"""Typed plant parameters with provenance, loaded from config/plant.*.yaml.

Every leaf of the YAML must be a `Param` with value, unit, status, source and as_of.
`load_plant` first walks the raw YAML and reports every leaf that lacks provenance (and
every bare value that is not inside a leaf), then validates the typed structure.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from engine.contracts import Co2Factors, HeatRatePoint, Param, ParamLeafView, StartSpec

PROVENANCE_FIELDS = ("value", "unit", "status", "source", "as_of")
IDENTIFIER_KEYS = ("id", "name", "eia_plant_code")  # identifiers, not parameters; allowed without provenance


class ProvenanceError(ValueError):
    """A plant parameter is missing provenance. Brief §0.3: this is a build error."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("plant config provenance errors:\n  " + "\n  ".join(problems))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StartParams(_Strict):
    hot: Param[StartSpec]
    warm: Param[StartSpec]
    cold: Param[StartSpec]

    @model_validator(mode="after")
    def _check_thresholds(self) -> "StartParams":
        hot_h, warm_h, cold_h = (
            self.hot.value.hours_offline_max_h,
            self.warm.value.hours_offline_max_h,
            self.cold.value.hours_offline_max_h,
        )
        if hot_h is None or warm_h is None or not hot_h < warm_h:
            raise ValueError("start thresholds must satisfy hot < warm (hours offline)")
        if cold_h is not None:
            raise ValueError("cold start must be unbounded (hours_offline_max_h: null)")
        return self


class UnitParams(_Strict):
    id: str
    pmax_mw: Param[float]
    pmin_mw: Param[float]
    heat_rate_curve: Param[list[HeatRatePoint]]
    no_load_mmbtu_per_hr: Param[float]
    start: StartParams
    min_up_hours: Param[int]
    min_down_hours: Param[int]
    ramp_mw_per_min: Param[float]
    vom_usd_per_mwh: Param[float]
    efor: Param[float]

    @model_validator(mode="after")
    def _check_unit(self) -> "UnitParams":
        if not 0 < self.pmin_mw.value < self.pmax_mw.value:
            raise ValueError(f"{self.id}: need 0 < pmin_mw < pmax_mw")
        outputs = [point.output_mw for point in self.heat_rate_curve.value]
        if len(outputs) < 1 or outputs != sorted(set(outputs)):
            raise ValueError(f"{self.id}: heat_rate_curve output_mw must be strictly increasing")
        if outputs[0] < self.pmin_mw.value or outputs[-1] != self.pmax_mw.value:
            raise ValueError(f"{self.id}: heat_rate_curve must start at >= pmin_mw and end at pmax_mw")
        if not 0 <= self.efor.value < 1:
            raise ValueError(f"{self.id}: efor must be a fraction in [0, 1)")
        return self


class FuelParams(_Strict):
    gas_point: Param[str]
    gas_basis_adder_usd_per_mmbtu_by_month: Param[dict[int, float]]
    oil_heat_rate_penalty_fraction: Param[float]
    oil_tank_capacity_bbl: Param[float]
    oil_mmbtu_per_bbl: Param[float]
    oil_price_ratio_to_no2_distillate: Param[float]
    oil_target_inventory_bbl: Param[float]
    oil_permit_hours_per_year: Param[float]
    barge_lead_days: Param[int]
    transport_demand_charge_usd_per_mmbtu_day: Param[float]

    @model_validator(mode="after")
    def _check_months(self) -> "FuelParams":
        if sorted(self.gas_basis_adder_usd_per_mmbtu_by_month.value) != list(range(1, 13)):
            raise ValueError("gas_basis_adder_usd_per_mmbtu_by_month needs exactly months 1..12")
        if not 0 <= self.oil_target_inventory_bbl.value <= self.oil_tank_capacity_bbl.value:
            raise ValueError("oil_target_inventory_bbl must be between 0 and oil_tank_capacity_bbl")
        if self.oil_price_ratio_to_no2_distillate.value <= 0 or self.oil_mmbtu_per_bbl.value <= 0:
            raise ValueError("oil price ratio and oil heat content must be positive")
        if self.oil_heat_rate_penalty_fraction.value < 0 or self.barge_lead_days.value < 0:
            raise ValueError("oil heat-rate penalty and barge lead days cannot be negative")
        return self


class EmissionsParams(_Strict):
    co2_t_per_mmbtu: Param[Co2Factors]


class CapacityParams(_Strict):
    ucap_mw: Param[float]
    locality: Param[str]


class FixedParams(_Strict):
    fixed_om_usd_per_kw_year: Param[float]


class Plant(_Strict):
    """The plant as a commercial object: every parameter that turns a price into a dollar."""

    name: str
    eia_plant_code: int
    units: list[UnitParams]
    fuel: FuelParams
    emissions: EmissionsParams
    capacity: CapacityParams
    fixed: FixedParams

    @model_validator(mode="after")
    def _check_unit_ids(self) -> "Plant":
        ids = [unit.id for unit in self.units]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("plant needs at least one unit and unit ids must be unique")
        return self

    def unit(self, unit_id: str) -> UnitParams:
        for unit in self.units:
            if unit.id == unit_id:
                return unit
        raise KeyError(f"no unit {unit_id!r} in plant {self.name!r}")


def provenance_problems(raw: Any, path: str = "") -> list[str]:
    """Walk raw YAML and list every leaf without full provenance.

    A dict containing `value` is a leaf and must carry all five provenance fields, each
    non-empty. A scalar found outside a leaf (other than an identifier) is a bare value.
    """
    problems: list[str] = []
    if isinstance(raw, dict):
        if "value" in raw:
            for field in PROVENANCE_FIELDS:
                if field not in raw:
                    problems.append(f"{path}: leaf is missing `{field}`")
                elif field != "value" and raw[field] in (None, ""):
                    problems.append(f"{path}: leaf has empty `{field}`")
            return problems
        for key, child in raw.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key in IDENTIFIER_KEYS and not isinstance(child, (dict, list)):
                continue
            problems.extend(provenance_problems(child, child_path))
    elif isinstance(raw, list):
        for index, child in enumerate(raw):
            label = child.get("id", index) if isinstance(child, dict) else index
            problems.extend(provenance_problems(child, f"{path}.{label}"))
    else:
        problems.append(f"{path}: bare value {raw!r} without provenance (value/unit/status/source/as_of)")
    return problems


def parse_plant(raw: Any) -> Plant:
    """Validate parsed YAML into a `Plant`; raises ProvenanceError before any type error."""
    problems = provenance_problems(raw)
    if problems:
        raise ProvenanceError(problems)
    return Plant.model_validate(raw)


def load_plant(path: Path) -> Plant:
    """Load and validate a plant config file."""
    return parse_plant(yaml.safe_load(Path(path).read_text()))


def flatten_leaves(plant: Plant) -> list[ParamLeafView]:
    """Every parameter leaf with its dotted path, in config order."""
    leaves: list[ParamLeafView] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if set(node) == set(PROVENANCE_FIELDS):
                leaves.append(ParamLeafView(path=path, **node))
                return
            for key, child in node.items():
                if key in IDENTIFIER_KEYS:
                    continue
                walk(child, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                label = child.get("id", index) if isinstance(child, dict) else index
                walk(child, f"{path}.{label}")

    walk(plant.model_dump(mode="json"), "")
    return leaves


def status_counts(plant: Plant) -> dict[str, int]:
    """Number of parameter leaves by provenance status (always includes all three keys)."""
    counts = Counter(leaf.status for leaf in flatten_leaves(plant))
    return {status: counts.get(status, 0) for status in ("public", "assumed", "confirmed")}
