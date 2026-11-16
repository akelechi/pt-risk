"""Ledger mechanics and the invariants implemented so far (6, 7, 8)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import yaml

from engine.contracts import LedgerEntry
from engine.ledger import reconcile
from engine.ledger.ledger import Ledger, rollup, round_to_cent_usd
from engine.inputs import store
from tests.conftest import REPO_ROOT

NEW_YORK = ZoneInfo("America/New_York")
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def entry(hour_utc: datetime, line: str = "da_energy_rev", mwh: float = 300.0, price: float = 40.0, sign: int = 1):
    return LedgerEntry(
        ts_utc=hour_utc,
        ts_local=hour_utc.astimezone(NEW_YORK),
        unit_id="U1",
        line=line,
        quantity=mwh,
        quantity_unit="MWh",
        price=price,
        price_unit="USD/MWh",
        amount_usd=sign * round_to_cent_usd(mwh * price),
        ref={},
    )


def test_round_to_cent_is_half_even_and_float_safe():
    assert round_to_cent_usd(2.675) == 2.68  # binary float 2.675 is below the half; Decimal(repr) is not
    assert round_to_cent_usd(0.125) == 0.12
    assert round_to_cent_usd(0.135) == 0.14
    assert round_to_cent_usd(-12381.004) == -12381.0


def test_empty_ledger_has_the_empty_hash_and_no_rollups():
    ledger = Ledger()
    assert len(ledger) == 0 and ledger.entries == ()
    assert ledger.content_hash() == EMPTY_SHA256
    assert ledger.rollup("month") == []


def test_ledger_is_append_only_and_order_sensitive():
    first = entry(datetime(2025, 1, 15, 17, tzinfo=timezone.utc))
    second = entry(datetime(2025, 1, 15, 18, tzinfo=timezone.utc), price=41.0)
    ledger = Ledger()
    ledger.append([first, second])
    assert ledger.entries == (first, second)
    assert not hasattr(ledger, "remove") and not hasattr(ledger, "clear")
    with pytest.raises(AttributeError):
        ledger.entries.append(first)  # a tuple view, not the list
    with pytest.raises(TypeError):
        ledger.append([{"line": "da_energy_rev"}])

    reordered = Ledger()
    reordered.append([second, first])
    same = Ledger()
    same.append([first, second])
    assert ledger.content_hash() == same.content_hash() != reordered.content_hash()


def test_rollups_are_views_by_local_day_and_month():
    # 2025-02-01 04:00Z is 23:00 on Jan 31 in New York: it belongs to January locally.
    late_january = entry(datetime(2025, 2, 1, 4, tzinfo=timezone.utc), mwh=100.0, price=30.0)
    february = entry(datetime(2025, 2, 1, 5, tzinfo=timezone.utc), mwh=100.0, price=31.0)
    fuel = entry(datetime(2025, 2, 1, 5, tzinfo=timezone.utc), line="vom", mwh=100.0, price=3.0, sign=-1)
    entries = [late_january, february, fuel]

    by_month = {(r.period, r.line): r for r in rollup(entries, "month")}
    assert by_month[("2025-01", "da_energy_rev")].amount_usd == 3000.00
    assert by_month[("2025-02", "da_energy_rev")].amount_usd == 3100.00
    assert by_month[("2025-02", "vom")].amount_usd == -300.00
    by_day = {(r.period, r.line): r for r in rollup(entries, "day")}
    assert set(by_day) == {("2025-01-31", "da_energy_rev"), ("2025-02-01", "da_energy_rev"), ("2025-02-01", "vom")}
    assert sum(r.amount_usd for r in rollup(entries, "hour")) == sum(e.amount_usd for e in entries)
    assert sum(r.entry_count for r in rollup(entries, "month")) == 3


def test_pending_invariants_never_claim_a_pass():
    for invariant_id in (1, 2, 3, 4, 5):
        result = reconcile.pending(invariant_id)
        assert result.status == "not_applicable" and "needs milestone" in result.detail


def test_time_integrity_invariant_on_real_year(timezone, market):
    tables = {name: store.read_table(REPO_ROOT, name)[0] for name in ("lbmp_da", "lbmp_rt")}
    ptids = {item["ptid"] for item in market["locations"]}
    window = market["data_window"]
    result = reconcile.check_time_integrity(tables, timezone, window["start"], window["end"], ptids)
    assert result.status == "pass", result.detail
    assert "52560 hourly rows" in result.detail


def test_time_integrity_invariant_fails_on_short_or_broken_tables(timezone, market):
    da = store.read_table(REPO_ROOT, "lbmp_da")[0]
    ptids = {item["ptid"] for item in market["locations"]}
    window = market["data_window"]

    short = reconcile.check_time_integrity({"lbmp_da": da}, timezone, window["start"], window["end"] + timedelta(days=1), ptids)
    assert short.status == "fail" and "scenario needs" in short.detail

    holed = da.drop(index=da.index[100])
    broken = reconcile.check_time_integrity({"lbmp_da": holed}, timezone, window["start"], window["end"], ptids)
    assert broken.status == "fail" and "has 23 hours, expected 24" in broken.detail

    missing = reconcile.check_time_integrity({"lbmp_da": da}, timezone, window["start"], window["end"], ptids | {99})
    assert missing.status == "fail" and "no rows for PTID 99" in missing.detail


def test_provenance_invariant():
    raw = yaml.safe_load((REPO_ROOT / "config" / "plant.roseton.yaml").read_text())
    assert reconcile.check_provenance(raw, 36, 29).status == "pass"
    del raw["capacity"]["ucap_mw"]["source"]
    failed = reconcile.check_provenance(raw, 36, 29)
    assert failed.status == "fail" and "capacity.ucap_mw: leaf is missing `source`" in failed.detail


def test_reproducibility_invariant():
    assert reconcile.check_reproducibility("abc", "abc", 0).status == "pass"
    assert reconcile.check_reproducibility("abc", "abd", 0).status == "fail"
