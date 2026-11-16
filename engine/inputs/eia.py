"""EIA public files -> curated `gas_price` (Henry Hub) and the EIA plant reference extract.

* Henry Hub daily spot: workbook RNGWHHDd.xls, sheet "Data 1", $/MMBtu, published
  trading days only. Non-trading days are NOT filled here (see docs/methodology.md).
* EIA-860 (generator capacities) and EIA-923 (annual fuel burn and net generation) are
  read for one plant code, as public evidence for plant parameters. They are a reference
  table; nothing in the engine reads them as an input.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

from engine.inputs.nyiso import RawFile

GAS_PRICE_COLUMNS = ["date", "point", "price_usd_per_mmbtu", "as_of", "source_id"]
EIA_REFERENCE_COLUMNS = [
    "dataset",
    "report_year",
    "plant_code",
    "key",
    "field",
    "value",
    "unit",
    "as_of",
    "source_id",
]

HENRY_HUB_SHEET = "Data 1"
HENRY_HUB_HEADER_WORDS = ("henry hub", "dollars per million btu")

# EIA-860 generator fields kept: column header -> (field name with unit, unit)
EIA860_GENERATOR_FIELDS = {
    "Nameplate Capacity (MW)": ("nameplate_capacity_mw", "MW"),
    "Summer Capacity (MW)": ("summer_capacity_mw", "MW"),
    "Winter Capacity (MW)": ("winter_capacity_mw", "MW"),
    "Minimum Load (MW)": ("minimum_load_mw", "MW"),
    "Operating Year": ("operating_year", "year"),
}
# EIA-923 page 1 fields kept (headers normalised to single spaces)
EIA923_FIELDS = {
    "Elec Fuel Consumption MMBtu": ("elec_fuel_consumption_mmbtu", "MMBtu"),
    "Net Generation (Megawatthours)": ("net_generation_mwh", "MWh"),
}


class EiaFormatError(ValueError):
    """An EIA file does not look like the layout this loader was written for."""


def load_henry_hub(raw_file: RawFile, first_date: date, last_date: date) -> pd.DataFrame:
    """Henry Hub daily spot price, $/MMBtu, for published days in [first_date, last_date]."""
    sheet = pd.read_excel(raw_file.path, sheet_name=HENRY_HUB_SHEET, header=None)
    header_rows = sheet.index[sheet[0].astype(str).str.strip() == "Date"]
    if len(header_rows) != 1:
        raise EiaFormatError(f"{raw_file.path}: expected one 'Date' header row in {HENRY_HUB_SHEET!r}")
    header_row = int(header_rows[0])
    title = str(sheet.iloc[header_row, 1]).lower()
    if not all(word in title for word in HENRY_HUB_HEADER_WORDS):
        raise EiaFormatError(f"{raw_file.path}: unexpected series title {title!r}")

    data = sheet.iloc[header_row + 1 :, :2].dropna(how="all")
    table = pd.DataFrame(
        {
            "date": pd.to_datetime(data[0]).dt.date,
            "price_usd_per_mmbtu": pd.to_numeric(data[1]),
        }
    )
    if table["date"].duplicated().any():
        raise EiaFormatError(f"{raw_file.path}: duplicate dates")
    table = table[(table["date"] >= first_date) & (table["date"] <= last_date)].copy()
    # The full history has dated rows with a blank price (e.g. 2018-01-05). Inside the
    # requested range a blank is refused rather than dropped, so it is a visible decision.
    blank = table.loc[table["price_usd_per_mmbtu"].isna(), "date"]
    if not blank.empty:
        raise EiaFormatError(f"{raw_file.path}: dated rows without a price: {blank.tolist()}")
    if table.empty:
        raise EiaFormatError(f"{raw_file.path}: no prices between {first_date} and {last_date}")
    table["point"] = "HENRY"
    table["as_of"] = raw_file.as_of
    table["source_id"] = raw_file.source_id
    return table.sort_values("date").reset_index(drop=True)[GAS_PRICE_COLUMNS]


def _member(archive: zipfile.ZipFile, prefix: str) -> str:
    matches = [name for name in archive.namelist() if Path(name).name.startswith(prefix)]
    if len(matches) != 1:
        raise EiaFormatError(f"expected one member starting with {prefix!r}, found {matches}")
    return matches[0]


def _normalise(columns: pd.Index) -> list[str]:
    return [" ".join(str(column).split()) for column in columns]


def _report_year(name: str) -> int:
    digits = "".join(character if character.isdigit() else " " for character in name).split()
    years = [int(token) for token in digits if len(token) == 4 and token.startswith("20")]
    if not years:
        raise EiaFormatError(f"no report year in file name {name!r}")
    return years[0]


def load_eia860_generators(raw_file: RawFile, plant_code: int) -> pd.DataFrame:
    """Operable generators of one plant from EIA-860 file 3_1, one row per generator x field."""
    with zipfile.ZipFile(raw_file.path) as archive:
        member = _member(archive, "3_1_Generator")
        sheet = pd.read_excel(io.BytesIO(archive.read(member)), sheet_name="Operable", header=1)
    sheet.columns = _normalise(sheet.columns)
    missing = [column for column in ("Plant Code", "Generator ID", *EIA860_GENERATOR_FIELDS) if column not in sheet]
    if missing:
        raise EiaFormatError(f"{member}: missing columns {missing}")
    generators = sheet[sheet["Plant Code"] == plant_code]
    if generators.empty:
        raise EiaFormatError(f"{member}: no operable generators for plant code {plant_code}")
    rows = []
    for _, generator in generators.iterrows():
        for column, (field, unit) in EIA860_GENERATOR_FIELDS.items():
            rows.append(
                {
                    "dataset": "EIA-860",
                    "report_year": _report_year(member),
                    "plant_code": plant_code,
                    "key": f"generator:{generator['Generator ID']}",
                    "field": field,
                    "value": float(generator[column]),
                    "unit": unit,
                    "as_of": raw_file.as_of,
                    "source_id": raw_file.source_id,
                }
            )
    return pd.DataFrame(rows, columns=EIA_REFERENCE_COLUMNS)


def load_eia860_plant_name(raw_file: RawFile, plant_code: int) -> str:
    """Plant name for a plant code from EIA-860 file 2 (used to verify the configured code)."""
    with zipfile.ZipFile(raw_file.path) as archive:
        member = _member(archive, "2___Plant")
        sheet = pd.read_excel(io.BytesIO(archive.read(member)), header=1)
    sheet.columns = _normalise(sheet.columns)
    names = sheet.loc[sheet["Plant Code"] == plant_code, "Plant Name"]
    if len(names) != 1:
        raise EiaFormatError(f"{member}: plant code {plant_code} matches {len(names)} plants")
    return str(names.iloc[0])


def load_eia923_fuel(raw_file: RawFile, plant_code: int) -> pd.DataFrame:
    """Annual fuel burn (MMBtu) and net generation (MWh) by fuel from EIA-923 page 1."""
    with zipfile.ZipFile(raw_file.path) as archive:
        member = _member(archive, "EIA923_Schedules_2_3_4_5")
        sheet = pd.read_excel(
            io.BytesIO(archive.read(member)), sheet_name="Page 1 Generation and Fuel Data", header=5
        )
    sheet.columns = _normalise(sheet.columns)
    missing = [column for column in ("Plant Id", "Reported Fuel Type Code", "YEAR", *EIA923_FIELDS) if column not in sheet]
    if missing:
        raise EiaFormatError(f"{member}: missing columns {missing}")
    plant = sheet[sheet["Plant Id"] == plant_code]
    if plant.empty:
        raise EiaFormatError(f"{member}: no rows for plant id {plant_code}")
    rows = []
    for _, record in plant.iterrows():
        for column, (field, unit) in EIA923_FIELDS.items():
            rows.append(
                {
                    "dataset": "EIA-923",
                    "report_year": int(record["YEAR"]),
                    "plant_code": plant_code,
                    "key": f"fuel:{record['Reported Fuel Type Code']}",
                    "field": field,
                    "value": float(record[column]),
                    "unit": unit,
                    "as_of": raw_file.as_of,
                    "source_id": raw_file.source_id,
                }
            )
    return pd.DataFrame(rows, columns=EIA_REFERENCE_COLUMNS)
