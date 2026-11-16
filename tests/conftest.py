"""Shared fixtures: repository paths, market config, DST fixture frames, a temp repo copy."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml

from engine.inputs import nyiso

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
FIXTURE_AS_OF = date(2026, 11, 16)


@pytest.fixture(scope="session")
def market() -> dict:
    return yaml.safe_load((REPO_ROOT / "config" / "market.nyiso.yaml").read_text())


@pytest.fixture(scope="session")
def timezone(market: dict) -> str:
    return market["timezone"]


@pytest.fixture(scope="session")
def locations(market: dict) -> list[nyiso.Location]:
    return [nyiso.Location(name=i["name"], ptid=i["ptid"], type=i["type"]) for i in market["locations"]]


def fixture_raw_file(name: str) -> nyiso.RawFile:
    return nyiso.RawFile(path=FIXTURES / "nyiso" / name, source="fixture", sha256="f" * 64, as_of=FIXTURE_AS_OF)


def read_fixture(name: str, ptids: set[int]) -> tuple[pd.DataFrame, nyiso.RawFile]:
    raw_file = fixture_raw_file(name)
    return nyiso.read_lbmp_zip(raw_file.path, ptids), raw_file


@pytest.fixture()
def raw_dst_frames(locations: list[nyiso.Location]):
    """Parsed fixture frames (gen + zone) for one market, in RAW_COLUMNS, per test (mutable)."""

    def load(market_prefix: str) -> list[tuple[pd.DataFrame, nyiso.RawFile]]:
        ptids = {location.ptid for location in locations}
        return [
            read_fixture(f"{market_prefix}_gen_dst.zip", ptids),
            read_fixture(f"{market_prefix}_zone_dst.zip", ptids),
        ]

    return load


def build_fixture_table(frames, locations, market: dict, start: date, end: date) -> pd.DataFrame:
    return nyiso.build_lbmp_table(
        frames, locations, market["timezone"], start, end, market["energy_identity_tolerance_usd_per_mwh"]
    )


@pytest.fixture()
def repo_copy(tmp_path: Path) -> Path:
    """A throwaway repository root with the real config and curated tables (no git, no raw)."""
    shutil.copytree(REPO_ROOT / "config", tmp_path / "config")
    shutil.copytree(REPO_ROOT / "data" / "curated", tmp_path / "data" / "curated")
    return tmp_path


# ------------------------------------------------------------- milestone 1 toy case

from datetime import datetime, timedelta  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from openpyxl import load_workbook  # noqa: E402

from engine.contracts import DayPrices, HourInputs, HourPrice  # noqa: E402
from engine.plant.params import UnitParams, parse_plant  # noqa: E402

HAND_DAY = date(2025, 1, 15)
HAND_GAS_USD_PER_MMBTU = 4.00
OFFER_PRICE_DECIMALS = 2


def toy_plant_raw() -> dict:
    """The real config with U1 replaced by the brief's original example unit:
    Pmin 150, Pmax 600, IHR 11.4/10.1/10.0/10.8, VOM 3.00, fully available (EFOR 0)."""
    raw = yaml.safe_load((REPO_ROOT / "config" / "plant.roseton.yaml").read_text())
    unit = raw["units"][0]
    unit["pmax_mw"]["value"] = 600
    unit["pmin_mw"]["value"] = 150
    unit["heat_rate_curve"]["value"] = [
        {"output_mw": 150, "incremental_heat_rate_mmbtu_per_mwh": 11.4},
        {"output_mw": 300, "incremental_heat_rate_mmbtu_per_mwh": 10.1},
        {"output_mw": 450, "incremental_heat_rate_mmbtu_per_mwh": 10.0},
        {"output_mw": 600, "incremental_heat_rate_mmbtu_per_mwh": 10.8},
    ]
    unit["vom_usd_per_mwh"]["value"] = 3.0
    unit["efor"]["value"] = 0.0
    return raw


@pytest.fixture(scope="session")
def toy_unit() -> UnitParams:
    return parse_plant(toy_plant_raw()).unit("U1")


@pytest.fixture(scope="session")
def real_unit() -> UnitParams:
    return parse_plant(yaml.safe_load((REPO_ROOT / "config" / "plant.roseton.yaml").read_text())).unit("U1")


@pytest.fixture(scope="session")
def hand_lbmps() -> list[float]:
    """The 24 DA LBMPs typed into the hand-worked spreadsheet (inputs, not formulas)."""
    sheet = load_workbook(FIXTURES / "m1_hand_day.xlsx")["hours"]
    return [float(sheet.cell(row=row, column=2).value) for row in range(2, 26)]


def day_prices(unit_id: str, lbmps: list[float], local_date: date = HAND_DAY) -> DayPrices:
    """DayPrices for an ordinary 24-hour winter day in New York."""
    midnight = datetime(local_date.year, local_date.month, local_date.day, tzinfo=ZoneInfo("America/New_York"))
    hours = []
    for index, lbmp in enumerate(lbmps):
        ts_utc = midnight.astimezone(ZoneInfo("UTC")) + timedelta(hours=index)
        hours.append(
            HourPrice(ts_utc=ts_utc, ts_local=ts_utc.astimezone(ZoneInfo("America/New_York")),
                      da_lbmp_usd_per_mwh=lbmp, da_lbmp_ref=f"hand:lbmp:{index}")
        )
    return DayPrices(unit_id=unit_id, local_date=local_date, hours=hours)


def hour_inputs_for(hour: HourPrice, unit_id: str, available_mw: float,
                    gas_usd_per_mmbtu: float = HAND_GAS_USD_PER_MMBTU) -> HourInputs:
    return HourInputs(
        ts_utc=hour.ts_utc, ts_local=hour.ts_local, unit_id=unit_id,
        da_lbmp_usd_per_mwh=hour.da_lbmp_usd_per_mwh, da_lbmp_ref=hour.da_lbmp_ref,
        gas_price_usd_per_mmbtu=gas_usd_per_mmbtu, gas_index_price_usd_per_mmbtu=gas_usd_per_mmbtu,
        gas_basis_adder_usd_per_mmbtu=0.0, gas_price_ref="hand:gas", available_mw=available_mw,
    )
