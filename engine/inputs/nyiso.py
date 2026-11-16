"""NYISO public LBMP files -> curated `lbmp_da` / `lbmp_rt` tables.

Source files are the monthly zip archives of daily CSVs published at mis.nyiso.com
(day-ahead: `damlbmp`; real-time, time-weighted integrated hourly: `rtlbmp`), in both
generator and zonal flavours. Columns, in file order:

    Time Stamp, Name, PTID, LBMP ($/MWHr), Marginal Cost Losses ($/MWHr),
    Marginal Cost Congestion ($/MWHr)

NYISO publishes no energy component; it is derived as lbmp - loss + congestion
(NYISO's sign convention: LBMP = energy + losses - congestion). All prices in $/MWh.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from engine.inputs.timeutil import (
    TimeIntegrityError,
    localize_hour_beginning,
    time_integrity_problems,
)

RAW_COLUMNS = [
    "ts_naive",
    "location",
    "location_ptid",
    "lbmp_usd_per_mwh",
    "loss_usd_per_mwh",
    "congestion_usd_per_mwh",
]
LBMP_COLUMNS = [
    "ts_utc",
    "ts_local",
    "location",
    "location_ptid",
    "location_type",
    "lbmp_usd_per_mwh",
    "energy_usd_per_mwh",
    "congestion_usd_per_mwh",
    "loss_usd_per_mwh",
    "as_of",
    "source_id",
]
SOURCE_ID_LENGTH = 16


@dataclass(frozen=True)
class RawFile:
    """A downloaded file as recorded in data/raw.manifest.json."""

    path: Path
    source: str
    sha256: str
    as_of: date  # retrieval date (UTC)

    @property
    def source_id(self) -> str:
        return self.sha256[:SOURCE_ID_LENGTH]


@dataclass(frozen=True)
class Location:
    """A pricing location from config/market.*.yaml."""

    name: str
    ptid: int
    type: str  # "gen" or "zone"


class LbmpFormatError(ValueError):
    """A raw LBMP file does not look like the documented NYISO layout."""


def parse_lbmp_csv(text: str) -> pd.DataFrame:
    """Parse one daily NYISO LBMP CSV into RAW_COLUMNS, preserving file order.

    Works for both quoted (real-time) and unquoted (day-ahead) files. Prices in $/MWh.
    """
    frame = pd.read_csv(io.StringIO(text), header=0)
    if frame.shape[1] != len(RAW_COLUMNS):
        raise LbmpFormatError(f"expected {len(RAW_COLUMNS)} columns, got {list(frame.columns)}")
    header = [str(column).lower() for column in frame.columns]
    expected_words = ["time stamp", "name", "ptid", "lbmp", "losses", "congestion"]
    for column, word in zip(header, expected_words):
        if word not in column:
            raise LbmpFormatError(f"unexpected header {list(frame.columns)}; wanted {expected_words}")
    frame.columns = RAW_COLUMNS
    frame["ts_naive"] = pd.to_datetime(frame["ts_naive"], format="%m/%d/%Y %H:%M")
    return frame


def read_lbmp_zip(path: Path, ptids: set[int]) -> pd.DataFrame:
    """Read every daily CSV in a monthly zip, keeping only rows for `ptids`, in day order."""
    parts: list[pd.DataFrame] = []
    with zipfile.ZipFile(path) as archive:
        for member in sorted(archive.namelist()):
            if not member.lower().endswith(".csv"):
                continue
            day = parse_lbmp_csv(archive.read(member).decode("utf-8"))
            parts.append(day[day["location_ptid"].isin(ptids)])
    if not parts:
        raise LbmpFormatError(f"{path}: no CSV members")
    return pd.concat(parts, ignore_index=True)


def build_lbmp_table(
    raw_frames: list[tuple[pd.DataFrame, RawFile]],
    locations: list[Location],
    timezone: str,
    window_start: date,
    window_end: date,
    energy_tolerance_usd_per_mwh: float,
) -> pd.DataFrame:
    """Assemble a curated LBMP table (LBMP_COLUMNS) from parsed raw frames.

    raw_frames: (frame in RAW_COLUMNS, the raw file it came from), in chronological order
                per location. Rows outside [window_start, window_end] (local dates) and
                locations not in `locations` are discarded.
    Raises TimeIntegrityError if any local day is not a complete 23/24/25-hour day, and
    ValueError if a configured location is absent or the derived energy component differs
    across locations in the same hour by more than the tolerance.
    """
    by_ptid = {location.ptid: location for location in locations}
    parts: list[pd.DataFrame] = []
    for frame, raw_file in raw_frames:
        part = frame[frame["location_ptid"].isin(by_ptid.keys())].copy()
        part["as_of"] = raw_file.as_of
        part["source_id"] = raw_file.source_id
        parts.append(part)
    table = pd.concat(parts, ignore_index=True)

    for ptid, location in by_ptid.items():
        names = set(table.loc[table["location_ptid"] == ptid, "location"])
        if not names:
            raise ValueError(f"location {location.name} (PTID {ptid}) not found in raw files")
        if names != {location.name}:
            raise ValueError(f"PTID {ptid} is named {names} in raw files, config says {location.name!r}")

    table["ts_utc"], table["ts_local"] = localize_hour_beginning(
        table["ts_naive"], table["location_ptid"], timezone
    )
    local_date = table["ts_local"].dt.date
    table = table[(local_date >= window_start) & (local_date <= window_end)].copy()

    table["location_type"] = table["location_ptid"].map(lambda ptid: by_ptid[ptid].type)
    table["energy_usd_per_mwh"] = (
        table["lbmp_usd_per_mwh"] - table["loss_usd_per_mwh"] + table["congestion_usd_per_mwh"]
    ).round(2)

    table = table.sort_values(["location_ptid", "ts_utc"], kind="stable").reset_index(drop=True)
    table = table[LBMP_COLUMNS]

    problems = time_integrity_problems(table, timezone)
    if problems:
        raise TimeIntegrityError(problems)

    spread = table.groupby("ts_utc")["energy_usd_per_mwh"].agg(lambda s: s.max() - s.min())
    worst = float(spread.max())
    if worst > energy_tolerance_usd_per_mwh:
        raise ValueError(
            f"derived energy component differs across locations by {worst:.4f} $/MWh at "
            f"{spread.idxmax()} (tolerance {energy_tolerance_usd_per_mwh}); "
            "check the congestion sign convention"
        )
    return table
