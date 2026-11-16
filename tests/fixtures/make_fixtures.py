"""Cut small verbatim slices of real NYISO files into tests/fixtures/nyiso/.

Usage:  python tests/fixtures/make_fixtures.py     (needs data/raw/, see scripts/fetch_raw.py)

Lines are copied byte-for-byte from the public files; only rows are dropped. Each fixture
zip keeps NYISO's layout (one CSV per day) for the days around both 2025 DST changes:
2025-03-08..10 (spring forward, 23 h on the 9th) and 2025-11-01..03 (fall back, 25 h on
the 2nd). Generator files keep only the Roseton buses; zonal files keep every zone.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "nyiso"
OUT = ROOT / "tests" / "fixtures" / "nyiso"
DAYS = ["20250308", "20250309", "20250310", "20251101", "20251102", "20251103"]
ROSETON_MARKERS = (",23587,", ",23588,")
FIXED_ZIP_TIME = (2025, 1, 1, 0, 0, 0)  # constant, so rebuilding gives identical bytes


def cut(kind: str, market: str, keep_all_rows: bool) -> None:
    target = OUT / f"{market}_{kind}_dst.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
        for day in DAYS:
            source = RAW / f"{market}_{kind}" / f"{day[:6]}01{market}_{kind}_csv.zip"
            member = f"{day}{market}_{kind}.csv"
            lines = zipfile.ZipFile(source).read(member).decode("utf-8").splitlines(keepends=True)
            kept = [lines[0]] + [
                line for line in lines[1:] if keep_all_rows or any(marker in line for marker in ROSETON_MARKERS)
            ]
            out.writestr(zipfile.ZipInfo(member, FIXED_ZIP_TIME), "".join(kept))
    print(f"wrote {target.relative_to(ROOT)} ({target.stat().st_size:,d} bytes)")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for market in ("damlbmp", "rtlbmp"):
        cut("gen", market, keep_all_rows=False)
        cut("zone", market, keep_all_rows=True)
