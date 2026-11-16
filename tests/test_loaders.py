"""Loaders produce curated tables that satisfy their contracts."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd
import pytest

from engine.contracts import GasPriceRow, LbmpDaRow, LbmpRtRow
from engine.inputs import eia, nyiso, store
from engine.inputs.build import RAW_MANIFEST, load_raw_files
from tests.conftest import FIXTURES, REPO_ROOT, build_fixture_table, read_fixture

RAW_PRESENT = (REPO_ROOT / "data" / "raw" / "eia" / "RNGWHHDd.xls").exists()
needs_raw = pytest.mark.skipif(not RAW_PRESENT, reason="data/raw not downloaded (scripts/fetch_raw.py)")

QUOTED = '"Time Stamp","Name","PTID","LBMP ($/MWHr)","Marginal Cost Losses ($/MWHr)","Marginal Cost Congestion ($/MWHr)"\n"11/02/2025 00:00","HUD VL",61758,66.25,2.44,0.00\n'
UNQUOTED = "Time Stamp,Name,PTID,LBMP ($/MWHr),Marginal Cost Losses ($/MWHr),Marginal Cost Congestion ($/MWHr)\n11/02/2025 00:00,HUD VL,61758,50.98,2.38,0.00\n"


def test_parse_handles_quoted_and_unquoted_files():
    for text, lbmp in ((QUOTED, 66.25), (UNQUOTED, 50.98)):
        frame = nyiso.parse_lbmp_csv(text)
        assert list(frame.columns) == nyiso.RAW_COLUMNS
        assert frame.loc[0, "location"] == "HUD VL"
        assert frame.loc[0, "location_ptid"] == 61758
        assert frame.loc[0, "lbmp_usd_per_mwh"] == lbmp
        assert frame.loc[0, "ts_naive"] == pd.Timestamp("2025-11-02 00:00")


def test_parse_refuses_reordered_columns():
    swapped = UNQUOTED.replace(
        "Marginal Cost Losses ($/MWHr),Marginal Cost Congestion ($/MWHr)",
        "Marginal Cost Congestion ($/MWHr),Marginal Cost Losses ($/MWHr)",
    )
    with pytest.raises(nyiso.LbmpFormatError):
        nyiso.parse_lbmp_csv(swapped)


@pytest.mark.parametrize("market_prefix", ["damlbmp", "rtlbmp"])
def test_congestion_sign_convention_on_all_zones(market_prefix: str, market: dict):
    """energy = lbmp - loss + congestion gives one system energy price per hour across all
    zones, including congested hours; the opposite sign does not."""
    frame, _ = read_fixture(f"{market_prefix}_zone_dst.zip", ptids=set(range(0, 10**7)))
    tolerance = market["energy_identity_tolerance_usd_per_mwh"]
    # an hour = local stamp + occurrence (the fall-back 01:00 appears twice per zone)
    key = [frame["ts_naive"], frame.groupby(["ts_naive", "location_ptid"]).cumcount()]
    assert frame["location_ptid"].nunique() == 15
    assert (frame["congestion_usd_per_mwh"].abs() > 1).sum() > 100  # really congested

    right = frame["lbmp_usd_per_mwh"] - frame["loss_usd_per_mwh"] + frame["congestion_usd_per_mwh"]
    wrong = frame["lbmp_usd_per_mwh"] - frame["loss_usd_per_mwh"] - frame["congestion_usd_per_mwh"]
    right_spread = right.groupby(key).agg(lambda s: s.max() - s.min())
    wrong_spread = wrong.groupby(key).agg(lambda s: s.max() - s.min())
    assert right_spread.max() <= tolerance
    assert wrong_spread.max() > 10.0


def test_fixture_table_matches_contract(raw_dst_frames, locations, market):
    table = build_fixture_table(raw_dst_frames("damlbmp"), locations, market, date(2025, 3, 8), date(2025, 3, 10))
    assert list(table.columns) == nyiso.LBMP_COLUMNS
    assert store.validate_rows(table, LbmpDaRow) == 3 * 71
    assert set(table["location_type"]) == {"gen", "zone"}
    assert table["source_id"].eq("f" * 16).all()
    first = table.iloc[0]
    assert first["ts_local"].isoformat() == "2025-03-08T00:00:00-05:00"
    assert first["ts_utc"].isoformat() == "2025-03-08T05:00:00+00:00"


def test_wrong_location_name_or_missing_location_is_refused(raw_dst_frames, locations, market):
    renamed = [nyiso.Location("ROSETON_ONE", 23587, "gen"), *locations[1:]]
    with pytest.raises(ValueError, match="config says 'ROSETON_ONE'"):
        build_fixture_table(raw_dst_frames("damlbmp"), renamed, market, date(2025, 3, 8), date(2025, 3, 10))
    extra = [*locations, nyiso.Location("NOWHERE", 99, "gen")]
    with pytest.raises(ValueError, match="PTID 99\\) not found"):
        build_fixture_table(raw_dst_frames("damlbmp"), extra, market, date(2025, 3, 8), date(2025, 3, 10))


def test_inconsistent_energy_across_locations_is_refused(raw_dst_frames, locations, market):
    frames = raw_dst_frames("damlbmp")
    gen, raw_file = frames[0]
    gen = gen.copy()
    gen.loc[gen.index[0], "congestion_usd_per_mwh"] += 5.0
    frames[0] = (gen, raw_file)
    with pytest.raises(ValueError, match="check the congestion sign convention"):
        build_fixture_table(frames, locations, market, date(2025, 3, 8), date(2025, 3, 10))


# ------------------------------------------------------------- curated tables (real)


@pytest.mark.parametrize("name,model", [("lbmp_da", LbmpDaRow), ("lbmp_rt", LbmpRtRow), ("gas_price", GasPriceRow)])
def test_curated_table_rows_satisfy_contract_and_manifest(name, model):
    table, snapshot_id = store.read_table(REPO_ROOT, name)  # raises if content != manifest
    manifest = store.read_manifest(REPO_ROOT)["tables"][name]
    assert store.validate_rows(table, model) == manifest["rows"] > 0
    assert snapshot_id == manifest["snapshot_id"]
    assert table["as_of"].notna().all() and table["source_id"].str.len().eq(16).all()


def test_curated_source_ids_trace_to_raw_manifest():
    raw = {row["sha256"][:16] for row in json.loads((REPO_ROOT / RAW_MANIFEST).read_text())["files"]}
    for name in ("lbmp_da", "lbmp_rt", "gas_price", "eia_plant_reference"):
        table, _ = store.read_table(REPO_ROOT, name)
        assert set(table["source_id"]) <= raw


def test_curated_lbmp_tables_share_the_same_hours():
    da, _ = store.read_table(REPO_ROOT, "lbmp_da")
    rt, _ = store.read_table(REPO_ROOT, "lbmp_rt")
    key = ["location_ptid", "ts_utc"]
    assert da[key].reset_index(drop=True).equals(rt[key].reset_index(drop=True))
    assert da.groupby("location").size().to_dict() == {"HUD VL": 8760, "ROSETON___1": 8760, "ROSETON___2": 8760}


def test_gas_price_is_published_days_only(market: dict):
    table, _ = store.read_table(REPO_ROOT, "gas_price")
    window = market["data_window"]
    assert set(table["point"]) == {"HENRY"}
    assert not table["date"].duplicated().any()
    assert table["date"].is_monotonic_increasing
    assert all(day.weekday() < 5 for day in table["date"])  # no weekend prices invented
    assert table["price_usd_per_mmbtu"].between(0.5, 30).all()
    assert table["date"].min() >= window["start"] - timedelta(days=market["gas_lookback_days"])
    assert table["date"].min() < window["start"] and table["date"].max() <= window["end"]


def test_tampered_curated_table_is_refused(repo_copy):
    path = repo_copy / "data" / "curated" / "gas_price.parquet"
    table = pd.read_parquet(path)
    table.loc[0, "price_usd_per_mmbtu"] += 0.01
    table.to_parquet(path, index=False)
    with pytest.raises(store.SnapshotMismatchError):
        store.read_table(repo_copy, "gas_price")


def test_eia_reference_supports_the_plant_identifiers():
    table, _ = store.read_table(REPO_ROOT, "eia_plant_reference")
    assert set(table["plant_code"]) == {8006}
    generators = table[table["dataset"] == "EIA-860"]
    assert set(generators["key"]) == {"generator:1", "generator:2"}
    nameplate = generators[generators["field"] == "nameplate_capacity_mw"]["value"]
    assert nameplate.between(500, 700).all()
    fuel = table[table["dataset"] == "EIA-923"]
    burned = fuel[fuel["field"] == "elec_fuel_consumption_mmbtu"]["value"].sum()
    generated = fuel[fuel["field"] == "net_generation_mwh"]["value"].sum()
    assert 8 < burned / generated < 14  # plant annual average heat rate, MMBtu/MWh


@needs_raw
def test_henry_hub_loader_against_raw_file():
    (raw_file,) = load_raw_files(REPO_ROOT)["henry_hub"]
    table = eia.load_henry_hub(raw_file, date(2025, 1, 1), date(2025, 1, 31))
    assert list(table.columns) == eia.GAS_PRICE_COLUMNS
    assert 19 <= len(table) <= 23 and table["date"].min() >= date(2025, 1, 1)
    with pytest.raises(eia.EiaFormatError, match="without a price"):
        eia.load_henry_hub(raw_file, date(2018, 1, 1), date(2018, 1, 31))  # 2018-01-05 is blank
    with pytest.raises(eia.EiaFormatError, match="no prices between"):
        eia.load_henry_hub(raw_file, date(1990, 1, 1), date(1990, 1, 31))


def test_fixture_zips_exist():
    names = sorted(path.name for path in (FIXTURES / "nyiso").glob("*.zip"))
    assert names == ["damlbmp_gen_dst.zip", "damlbmp_zone_dst.zip", "rtlbmp_gen_dst.zip", "rtlbmp_zone_dst.zip"]
