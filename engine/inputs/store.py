"""Curated table store: parquet files under data/curated/ plus a manifest of snapshot ids.

A table's snapshot id is a hash of its content (including `as_of` and `source_id`), so a
run that records snapshot ids pins the exact rows it used. `read_table` re-hashes what it
reads and refuses a file that no longer matches the manifest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TypeVar

import pandas as pd
from pydantic import BaseModel

CURATED_DIR = Path("data") / "curated"
MANIFEST_NAME = "manifest.json"
SNAPSHOT_ID_LENGTH = 16

RowModel = TypeVar("RowModel", bound=BaseModel)


class SnapshotMismatchError(ValueError):
    """A curated file's content does not match the snapshot id in the manifest."""


def table_snapshot_id(frame: pd.DataFrame) -> str:
    """Content hash of a table: sha256 of its canonical CSV rendering, first 16 hex chars."""
    canonical = frame.to_csv(index=False, float_format="%.6f", lineterminator="\n")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:SNAPSHOT_ID_LENGTH]


def validate_rows(frame: pd.DataFrame, model: type[RowModel]) -> int:
    """Validate every row of a table against its pydantic contract; returns the row count."""
    if list(frame.columns) != list(model.model_fields):
        raise ValueError(
            f"{model.__name__}: columns {list(frame.columns)} != contract {list(model.model_fields)}"
        )
    for record in frame.to_dict("records"):
        model.model_validate(record)
    return len(frame)


def read_manifest(root: Path) -> dict:
    path = root / CURATED_DIR / MANIFEST_NAME
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build curated tables first: "
            "python scripts/fetch_raw.py && python -m engine.inputs.build"
        )
    return json.loads(path.read_text())


def write_table(root: Path, name: str, frame: pd.DataFrame) -> str:
    """Write one curated table as parquet; returns its snapshot id."""
    directory = root / CURATED_DIR
    directory.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(directory / f"{name}.parquet", index=False)
    return table_snapshot_id(frame)


def read_table(root: Path, name: str) -> tuple[pd.DataFrame, str]:
    """Read one curated table and verify it against the manifest; returns (table, snapshot id)."""
    manifest = read_manifest(root)
    if name not in manifest["tables"]:
        raise KeyError(f"table {name!r} is not in the curated manifest")
    frame = pd.read_parquet(root / CURATED_DIR / f"{name}.parquet")
    snapshot_id = table_snapshot_id(frame)
    expected = manifest["tables"][name]["snapshot_id"]
    if snapshot_id != expected:
        raise SnapshotMismatchError(
            f"{name}: content hash {snapshot_id} != manifest snapshot id {expected}; "
            "rebuild with python -m engine.inputs.build"
        )
    return frame, snapshot_id
