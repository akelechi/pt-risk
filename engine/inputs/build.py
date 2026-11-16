"""Build curated tables from data/raw/ using data/raw.manifest.json.

Usage:  python -m engine.inputs.build

Writes data/curated/{lbmp_da,lbmp_rt,gas_price,eia_plant_reference}.parquet and
data/curated/manifest.json (snapshot id, row count and coverage per table). Every `as_of`
comes from the raw manifest; this module never reads the wall clock.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml

from engine.contracts import GasPriceRow, LbmpDaRow, LbmpRtRow
from engine.inputs import eia, nyiso, store
from engine.plant.params import load_plant

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = Path("data") / "raw"
RAW_MANIFEST = Path("data") / "raw.manifest.json"


def load_raw_files(root: Path) -> dict[str, list[nyiso.RawFile]]:
    """Raw files by source name, each list sorted by path, verified to exist on disk."""
    manifest = json.loads((root / RAW_MANIFEST).read_text())
    by_source: dict[str, list[nyiso.RawFile]] = {}
    for row in sorted(manifest["files"], key=lambda item: item["raw_path"]):
        path = root / RAW_DIR / row["raw_path"]
        if not path.exists():
            raise FileNotFoundError(f"{path} is in the raw manifest but not on disk; run scripts/fetch_raw.py")
        by_source.setdefault(row["source"], []).append(
            nyiso.RawFile(
                path=path,
                source=row["source"],
                sha256=row["sha256"],
                as_of=date.fromisoformat(row["retrieved_at"][:10]),
            )
        )
    return by_source


def _lbmp(
    raw: dict[str, list[nyiso.RawFile]], sources: list[str], market: dict
) -> pd.DataFrame:
    locations = [
        nyiso.Location(name=item["name"], ptid=item["ptid"], type=item["type"])
        for item in market["locations"]
    ]
    ptids = {location.ptid for location in locations}
    frames = [
        (nyiso.read_lbmp_zip(raw_file.path, ptids), raw_file)
        for source in sources
        for raw_file in raw[source]
    ]
    return nyiso.build_lbmp_table(
        frames,
        locations,
        market["timezone"],
        market["data_window"]["start"],
        market["data_window"]["end"],
        market["energy_identity_tolerance_usd_per_mwh"],
    )


def _coverage(frame: pd.DataFrame) -> dict:
    if "ts_local" in frame:
        return {
            "first_local": frame["ts_local"].min().isoformat(),
            "last_local": frame["ts_local"].max().isoformat(),
            "locations": sorted(frame["location"].unique().tolist()),
        }
    if "date" in frame:
        return {"first_local": frame["date"].min().isoformat(), "last_local": frame["date"].max().isoformat()}
    return {}


def build(root: Path = REPO_ROOT) -> dict:
    """Build every milestone-0 curated table; returns the curated manifest that was written."""
    market = yaml.safe_load((root / "config" / "market.nyiso.yaml").read_text())
    plant = load_plant(root / "config" / "plant.roseton.yaml")
    raw = load_raw_files(root)

    tables: dict[str, pd.DataFrame] = {}
    tables["lbmp_da"] = _lbmp(raw, ["lbmp_da_gen", "lbmp_da_zone"], market)
    store.validate_rows(tables["lbmp_da"], LbmpDaRow)
    tables["lbmp_rt"] = _lbmp(raw, ["lbmp_rt_gen", "lbmp_rt_zone"], market)
    store.validate_rows(tables["lbmp_rt"], LbmpRtRow)

    window = market["data_window"]
    (henry_file,) = raw["henry_hub"]
    tables["gas_price"] = eia.load_henry_hub(
        henry_file, window["start"] - timedelta(days=market["gas_lookback_days"]), window["end"]
    )
    store.validate_rows(tables["gas_price"], GasPriceRow)

    (eia860_file,) = raw["eia860"]
    (eia923_file,) = raw["eia923"]
    eia_name = eia.load_eia860_plant_name(eia860_file, plant.eia_plant_code)
    if plant.name.lower() not in eia_name.lower():
        raise ValueError(
            f"EIA plant code {plant.eia_plant_code} is {eia_name!r}, which does not match plant {plant.name!r}"
        )
    tables["eia_plant_reference"] = pd.concat(
        [
            eia.load_eia860_generators(eia860_file, plant.eia_plant_code),
            eia.load_eia923_fuel(eia923_file, plant.eia_plant_code),
        ],
        ignore_index=True,
    )

    manifest = {"tables": {}}
    for name, frame in tables.items():
        snapshot_id = store.write_table(root, name, frame)
        manifest["tables"][name] = {
            "snapshot_id": snapshot_id,
            "rows": len(frame),
            "raw_source_ids": sorted(frame["source_id"].unique().tolist()),
            **_coverage(frame),
        }
    path = root / store.CURATED_DIR / store.MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
