"""Data contracts: units in names, timestamps, ledger amounts, and parameter provenance."""

from __future__ import annotations

import copy
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import yaml
from pydantic import ValidationError

from engine import contracts
from engine.contracts import LbmpDaRow, LedgerEntry, Param, PlantState, Scenario
from engine.plant.params import (
    ProvenanceError,
    flatten_leaves,
    load_plant,
    parse_plant,
    status_counts,
)
from tests.conftest import REPO_ROOT

NEW_YORK = ZoneInfo("America/New_York")
UTC_NOON = datetime(2025, 1, 15, 17, 0, tzinfo=timezone.utc)
LOCAL_NOON = UTC_NOON.astimezone(NEW_YORK)
PLANT_PATH = REPO_ROOT / "config" / "plant.roseton.yaml"


def lbmp_row(**overrides) -> dict:
    row = dict(
        ts_utc=UTC_NOON,
        ts_local=LOCAL_NOON,
        location="ROSETON___1",
        location_ptid=23587,
        location_type="gen",
        lbmp_usd_per_mwh=50.00,
        energy_usd_per_mwh=45.00,
        congestion_usd_per_mwh=-3.00,
        loss_usd_per_mwh=2.00,
        as_of=date(2026, 11, 16),
        source_id="abc",
    )
    row.update(overrides)
    return row


def ledger_entry(**overrides) -> dict:
    entry = dict(
        ts_utc=UTC_NOON,
        ts_local=LOCAL_NOON,
        unit_id="U1",
        line="da_energy_rev",
        quantity=300.0,
        quantity_unit="MWh",
        price=41.27,
        price_unit="USD/MWh",
        amount_usd=12381.00,
        ref={"lbmp_da": "abc:23587:2025-01-15T17:00:00+00:00"},
    )
    entry.update(overrides)
    return entry


# ------------------------------------------------------------------ units in names

BARE_NAMES = {"price", "cost", "rate", "amount", "inventory", "output", "capacity", "heat_rate", "lbmp", "energy"}
GENERIC_BY_DESIGN = {("LedgerEntry", "price"), ("LedgerEntry", "quantity"), ("LedgerRollup", "quantity")}


def test_no_bare_quantity_names_in_contracts():
    """Brief §0.8: never bare `price`. Only the ledger's generic quantity/price are exempt,
    and those carry an explicit *_unit field."""
    offenders = []
    for name in dir(contracts):
        model = getattr(contracts, name)
        if isinstance(model, type) and issubclass(model, contracts.BaseModel) and model.__module__ == contracts.__name__:
            for field, info in model.model_fields.items():
                numeric = info.annotation in (float, int, float | None, int | None)
                if numeric and field in BARE_NAMES and (name, field) not in GENERIC_BY_DESIGN:
                    offenders.append(f"{name}.{field}")
    assert offenders == []
    assert {"quantity_unit", "price_unit"} <= set(LedgerEntry.model_fields)


def test_lbmp_columns_carry_units():
    priced = [f for f in LbmpDaRow.model_fields if f.split("_")[0] in ("lbmp", "energy", "congestion", "loss")]
    assert priced and all(field.endswith("_usd_per_mwh") for field in priced)


# ---------------------------------------------------------------------- timestamps


def test_lbmp_row_accepts_consistent_row():
    row = LbmpDaRow(**lbmp_row())
    assert row.ts_utc == row.ts_local


def test_timestamps_must_be_aware_and_same_instant():
    with pytest.raises(ValidationError, match="timezone-aware"):
        LbmpDaRow(**lbmp_row(ts_local=LOCAL_NOON.replace(tzinfo=None)))
    with pytest.raises(ValidationError, match="same instant"):
        LbmpDaRow(**lbmp_row(ts_local=LOCAL_NOON + timedelta(hours=1)))
    with pytest.raises(ValidationError, match="zero UTC offset"):
        LbmpDaRow(**lbmp_row(ts_utc=LOCAL_NOON))


def test_lbmp_energy_identity_uses_nyiso_sign():
    # lbmp 50 = energy 45 + loss 2 - congestion(-3)
    LbmpDaRow(**lbmp_row())
    with pytest.raises(ValidationError, match="energy identity"):
        LbmpDaRow(**lbmp_row(energy_usd_per_mwh=51.00))  # the wrong-sign answer


def test_plant_state_rejects_unknown_fields_and_negative_inventory():
    state = dict(
        ts_utc=UTC_NOON, ts_local=LOCAL_NOON, unit_id="U1", committed=False, hours_in_state_h=5,
        thermal_state="hot", output_mw=0.0, fuel=None, oil_inventory_bbl=1000.0,
        oil_permit_hours_used_ytd_h=0.0, available_mw=600.0, da_schedule_mw=0.0,
    )
    PlantState(**state)
    with pytest.raises(ValidationError):
        PlantState(**{**state, "oil_inventory_bbl": -1.0})
    with pytest.raises(ValidationError):
        PlantState(**{**state, "price": 3.0})


# -------------------------------------------------------------------------- ledger


def test_ledger_entry_amount_must_match_quantity_times_price_to_the_cent():
    LedgerEntry(**ledger_entry())
    LedgerEntry(**ledger_entry(line="fuel_cost_gas", quantity=3000.0, quantity_unit="MMBtu",
                               price=4.10, price_unit="USD/MMBtu", amount_usd=-12300.00))
    with pytest.raises(ValidationError, match="does not match"):
        LedgerEntry(**ledger_entry(amount_usd=12381.02))
    with pytest.raises(ValidationError, match="not rounded to the cent"):
        LedgerEntry(**ledger_entry(amount_usd=12381.001))
    with pytest.raises(ValidationError, match="given together"):
        LedgerEntry(**ledger_entry(price_unit=None))


def test_ledger_entry_is_frozen():
    entry = LedgerEntry(**ledger_entry())
    with pytest.raises(ValidationError):
        entry.amount_usd = 0.0


def test_scenario_rejects_reversed_dates_and_unknown_modules():
    base = yaml.safe_load((REPO_ROOT / "config" / "scenario.base.yaml").read_text())
    Scenario.model_validate(base)
    with pytest.raises(ValidationError, match="before start_date"):
        Scenario.model_validate({**base, "end_date": date(2024, 1, 1)})
    with pytest.raises(ValidationError):
        Scenario.model_validate({**base, "modules": {"telepathy": True}})


# ---------------------------------------------------------------------- provenance


@pytest.fixture()
def plant_raw() -> dict:
    return yaml.safe_load(PLANT_PATH.read_text())


def test_param_requires_all_five_fields():
    good = dict(value=600, unit="MW", status="assumed", source="brief", as_of=date(2026, 11, 15))
    Param[float](**good)
    for field in good:
        with pytest.raises(ValidationError):
            Param[float](**{k: v for k, v in good.items() if k != field})
    with pytest.raises(ValidationError):
        Param[float](**{**good, "status": "guessed"})
    with pytest.raises(ValidationError):
        Param[float](**{**good, "source": ""})


def test_real_plant_config_loads_with_full_provenance():
    plant = load_plant(PLANT_PATH)
    leaves = flatten_leaves(plant)
    assert [unit.id for unit in plant.units] == ["U1", "U2"]
    assert len(leaves) == 36
    assert all(leaf.source and leaf.unit and leaf.status for leaf in leaves)
    counts = status_counts(plant)
    assert sum(counts.values()) == len(leaves)
    assert counts == {"public": 3, "assumed": 33, "confirmed": 0}
    assert "units.U1.pmax_mw" in {leaf.path for leaf in leaves}


@pytest.mark.parametrize("field", ["status", "source", "unit", "as_of"])
def test_loader_rejects_leaf_missing_a_provenance_field(plant_raw: dict, field: str):
    broken = copy.deepcopy(plant_raw)
    del broken["units"][0]["pmax_mw"][field]
    with pytest.raises(ProvenanceError) as caught:
        parse_plant(broken)
    assert caught.value.problems == [f"units.U1.pmax_mw: leaf is missing `{field}`"]


def test_loader_rejects_empty_source_and_bare_values(plant_raw: dict):
    broken = copy.deepcopy(plant_raw)
    broken["fuel"]["oil_mmbtu_per_bbl"]["source"] = ""
    broken["units"][1]["vom_usd_per_mwh"] = 3.0
    with pytest.raises(ProvenanceError) as caught:
        parse_plant(broken)
    assert "fuel.oil_mmbtu_per_bbl: leaf has empty `source`" in caught.value.problems
    assert any(p.startswith("units.U2.vom_usd_per_mwh: bare value 3.0") for p in caught.value.problems)


def test_loader_rejects_misspelled_keys_and_bad_structure(plant_raw: dict):
    typo = copy.deepcopy(plant_raw)
    typo["units"][0]["pmax_mw"]["staus"] = "assumed"
    with pytest.raises(ValidationError):
        parse_plant(typo)

    inverted = copy.deepcopy(plant_raw)
    inverted["units"][0]["pmin_mw"]["value"] = 700
    with pytest.raises(ValidationError, match="pmin_mw < pmax_mw"):
        parse_plant(inverted)

    curve = copy.deepcopy(plant_raw)
    curve["units"][0]["heat_rate_curve"]["value"][-1]["output_mw"] = 590
    with pytest.raises(ValidationError, match="end at pmax_mw"):
        parse_plant(curve)
