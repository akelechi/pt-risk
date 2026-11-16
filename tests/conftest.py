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
