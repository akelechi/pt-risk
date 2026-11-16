"""Download the public raw files listed in config/market.nyiso.yaml into data/raw/.

This script is the ONLY place in the repository that reads the wall clock: the
retrieval time of each file is written to data/raw.manifest.json, and the engine
takes every `as_of` from that manifest. Raw files are never edited after download.

Usage:  python scripts/fetch_raw.py [--force]

Idempotent: a file already on disk whose sha256 matches the manifest is skipped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
MANIFEST_PATH = ROOT / "data" / "raw.manifest.json"
USER_AGENT = "public-data-loader/0.1"
ZIP_MAGIC = b"PK"
OLE_MAGIC = b"\xd0\xcf\x11\xe0"


def months_in_window(start: date, end: date) -> list[str]:
    """Return 'YYYYMM' for every calendar month touched by [start, end]."""
    out: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        out.append(f"{year:04d}{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def planned_downloads(market: dict) -> list[dict]:
    """Expand the `sources` block of the market config into (source, url, raw_path)."""
    window = market["data_window"]
    months = months_in_window(window["start"], window["end"])
    plan: list[dict] = []
    for source, spec in market["sources"].items():
        if spec["cadence"] == "monthly":
            for yyyymm in months:
                plan.append(
                    {
                        "source": source,
                        "url": spec["url"].format(yyyymm=yyyymm),
                        "raw_path": spec["raw_path"].format(yyyymm=yyyymm),
                    }
                )
        elif spec["cadence"] == "once":
            plan.append({"source": source, "url": spec["url"], "raw_path": spec["raw_path"]})
        else:
            raise ValueError(f"unknown cadence {spec['cadence']!r} for source {source}")
    return plan


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_payload(raw_path: str, payload: bytes) -> None:
    """Refuse HTML error pages saved under a data file name."""
    if raw_path.endswith(".zip") and not payload.startswith(ZIP_MAGIC):
        raise ValueError(f"{raw_path}: expected a zip archive, got {payload[:40]!r}")
    if raw_path.endswith(".xls") and not payload.startswith(OLE_MAGIC):
        raise ValueError(f"{raw_path}: expected an .xls workbook, got {payload[:40]!r}")
    if raw_path.endswith(".csv") and payload.lstrip().startswith(b"<"):
        raise ValueError(f"{raw_path}: expected CSV, got markup {payload[:40]!r}")


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download every file")
    args = parser.parse_args()

    market = yaml.safe_load((ROOT / "config" / "market.nyiso.yaml").read_text())
    manifest: dict[str, dict] = {}
    if MANIFEST_PATH.exists():
        manifest = {row["raw_path"]: row for row in json.loads(MANIFEST_PATH.read_text())["files"]}

    failures: list[str] = []
    for item in planned_downloads(market):
        raw_path = item["raw_path"]
        target = RAW_DIR / raw_path
        known = manifest.get(raw_path)
        if not args.force and known and target.exists() and sha256_of(target) == known["sha256"]:
            continue
        try:
            payload = download(item["url"])
            check_payload(raw_path, payload)
        except Exception as error:  # noqa: BLE001 - report every failed source, then exit non-zero
            failures.append(f"{raw_path}: {error}")
            print(f"FAIL {raw_path}: {error}", file=sys.stderr)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        manifest[raw_path] = {
            "raw_path": raw_path,
            "source": item["source"],
            "url": item["url"],
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        print(f"ok   {raw_path}  {len(payload):>10,d} bytes")
        _write_manifest(manifest)

    _write_manifest(manifest)
    print(f"{len(manifest)} files in manifest, {len(failures)} failures")
    return 1 if failures else 0


def _write_manifest(manifest: dict[str, dict]) -> None:
    files = [manifest[key] for key in sorted(manifest)]
    MANIFEST_PATH.write_text(json.dumps({"files": files}, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
