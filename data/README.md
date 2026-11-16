# Data

Public data only. `raw/` holds downloaded files, never edited (not in git; rebuild with
`python scripts/fetch_raw.py`). `raw.manifest.json` records url, sha256, size and retrieval
time for each. `curated/` holds one parquet per table plus `manifest.json` with snapshot
ids (rebuild with `python -m engine.inputs.build`).

All files below were retrieved 2026-11-16 03:47-03:48 UTC.

## Raw files

| path under `raw/` | files | source URL | publisher / terms |
|---|---:|---|---|
| `nyiso/damlbmp_gen/YYYYMM01damlbmp_gen_csv.zip` | 12 | `http://mis.nyiso.com/public/csv/damlbmp/YYYYMM01damlbmp_gen_csv.zip` | NYISO public market data |
| `nyiso/damlbmp_zone/YYYYMM01damlbmp_zone_csv.zip` | 12 | `http://mis.nyiso.com/public/csv/damlbmp/YYYYMM01damlbmp_zone_csv.zip` | NYISO public market data |
| `nyiso/rtlbmp_gen/YYYYMM01rtlbmp_gen_csv.zip` | 12 | `http://mis.nyiso.com/public/csv/rtlbmp/YYYYMM01rtlbmp_gen_csv.zip` | NYISO public market data |
| `nyiso/rtlbmp_zone/YYYYMM01rtlbmp_zone_csv.zip` | 12 | `http://mis.nyiso.com/public/csv/rtlbmp/YYYYMM01rtlbmp_zone_csv.zip` | NYISO public market data |
| `nyiso/generator.csv` | 1 | `http://mis.nyiso.com/public/csv/generator/generator.csv` | NYISO public market data |
| `eia/RNGWHHDd.xls` | 1 | `https://www.eia.gov/dnav/ng/hist_xls/RNGWHHDd.xls` | U.S. EIA, public domain |
| `eia/EER_EPD2F_PF4_Y35NY_DPGd.xls` | 1 | `https://www.eia.gov/dnav/pet/hist_xls/EER_EPD2F_PF4_Y35NY_DPGd.xls` (New York Harbor No. 2 heating oil spot, daily; retrieved 2026-11-16; curated as `oil_price`) | U.S. EIA, public domain |
| `eia/eia8602024.zip` | 1 | `https://www.eia.gov/electricity/data/eia860/archive/xls/eia8602024.zip` | U.S. EIA, public domain |
| `eia/f923_2024.zip` | 1 | `https://www.eia.gov/electricity/data/eia923/archive/xls/f923_2024.zip` | U.S. EIA, public domain |

Months covered: 2025-01 through 2025-12. NYISO data is published for public use on its
Market Information System; the licence terms have not been reviewed beyond that and should
be checked before any redistribution of the raw files (they are not committed here).

## Curated tables

| file | contract | grain | rows | coverage |
|---|---|---|---:|---|
| `curated/lbmp_da.parquet` | `LbmpDaRow` | hour x location | 26,280 | 2025-01-01 .. 2025-12-31 local; ROSETON___1, ROSETON___2, HUD VL |
| `curated/lbmp_rt.parquet` | `LbmpRtRow` | hour x location | 26,280 | same |
| `curated/gas_price.parquet` | `GasPriceRow` | published day x point | 269 | 2024-12-02 .. 2025-12-31; HENRY |
| `curated/eia_plant_reference.parquet` | reference (not an engine input) | generator / fuel x field | 16 | EIA-860 and EIA-923, report year 2024, plant code 8006 |

Every row carries `as_of` (UTC retrieval date) and `source_id` (first 16 hex of the raw
file's sha256, traceable in `raw.manifest.json`).

## Test fixtures

`tests/fixtures/nyiso/*.zip` are verbatim row slices of the raw NYISO files around both
2025 DST changes (2025-03-08..10 and 2025-11-01..03), produced by
`tests/fixtures/make_fixtures.py`.
