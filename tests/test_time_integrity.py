"""Invariant 6: 23/24/25-hour local days, no hour dropped or duplicated silently.

Fixtures are verbatim slices of NYISO files around both 2025 DST changes.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from engine.inputs import store
from engine.inputs.timeutil import (
    TimeIntegrityError,
    expected_hours_in_local_day,
    time_integrity_problems,
)
from tests.conftest import REPO_ROOT, build_fixture_table

SPRING = (date(2025, 3, 8), date(2025, 3, 10))
FALL = (date(2025, 11, 1), date(2025, 11, 3))
ROSETON_1 = 23587
MARKETS = ["damlbmp", "rtlbmp"]


def hours_by_day(table: pd.DataFrame, ptid: int) -> dict[date, int]:
    one = table[table["location_ptid"] == ptid]
    return one.groupby(one["ts_local"].dt.date).size().to_dict()


def test_expected_hours_follow_dst_rules(timezone: str):
    days = pd.Series(pd.date_range("2025-01-01", "2025-12-31").date)
    hours = expected_hours_in_local_day(days, timezone)
    assert hours.sum() == 8760
    assert days[hours == 23].tolist() == [date(2025, 3, 9)]
    assert days[hours == 25].tolist() == [date(2025, 11, 2)]


@pytest.mark.parametrize("market_prefix", MARKETS)
def test_spring_forward_day_has_23_hours(raw_dst_frames, locations, market, market_prefix):
    table = build_fixture_table(raw_dst_frames(market_prefix), locations, market, *SPRING)
    for location in locations:
        assert hours_by_day(table, location.ptid) == {
            date(2025, 3, 8): 24, date(2025, 3, 9): 23, date(2025, 3, 10): 24
        }
    day = table[(table["location_ptid"] == ROSETON_1) & (table["ts_local"].dt.date == date(2025, 3, 9))]
    assert 2 not in day["ts_local"].dt.hour.tolist()  # 02:00 does not exist
    # 01:00 EST (06:00 UTC) is followed directly by 03:00 EDT (07:00 UTC)
    assert day["ts_utc"].diff().dropna().eq(pd.Timedelta(hours=1)).all()


@pytest.mark.parametrize("market_prefix", MARKETS)
def test_fall_back_day_has_25_hours_with_both_one_oclocks(raw_dst_frames, locations, market, market_prefix):
    table = build_fixture_table(raw_dst_frames(market_prefix), locations, market, *FALL)
    for location in locations:
        assert hours_by_day(table, location.ptid) == {
            date(2025, 11, 1): 24, date(2025, 11, 2): 25, date(2025, 11, 3): 24
        }
    day = table[(table["location_ptid"] == ROSETON_1) & (table["ts_local"].dt.date == date(2025, 11, 2))]
    ones = day[day["ts_local"].dt.hour == 1]
    assert len(ones) == 2
    # first 01:00 is EDT (UTC-4 -> 05:00Z), second is EST (UTC-5 -> 06:00Z)
    assert ones["ts_utc"].dt.hour.tolist() == [5, 6]
    assert [stamp.utcoffset().total_seconds() / 3600 for stamp in ones["ts_local"]] == [-4.0, -5.0]
    assert not table.duplicated(["location_ptid", "ts_utc"]).any()
    assert day["ts_utc"].diff().dropna().eq(pd.Timedelta(hours=1)).all()


def test_fall_back_keeps_file_order_prices(raw_dst_frames, locations, market):
    """The two 01:00 prices must stay attached to their own hour (first row -> EDT)."""
    frames = raw_dst_frames("damlbmp")
    raw_gen = frames[0][0]
    raw_ones = raw_gen[(raw_gen["location_ptid"] == ROSETON_1) & (raw_gen["ts_naive"] == "2025-11-02 01:00")]
    table = build_fixture_table(frames, locations, market, *FALL)
    day = table[(table["location_ptid"] == ROSETON_1) & (table["ts_local"].dt.date == date(2025, 11, 2))]
    ones = day[day["ts_local"].dt.hour == 1].sort_values("ts_utc")
    assert ones["lbmp_usd_per_mwh"].tolist() == raw_ones["lbmp_usd_per_mwh"].tolist()
    assert raw_ones["lbmp_usd_per_mwh"].nunique() == 2  # the fixture really distinguishes them


def test_missing_hour_is_refused(raw_dst_frames, locations, market):
    frames = raw_dst_frames("damlbmp")
    gen, raw_file = frames[0]
    drop = (gen["location_ptid"] == ROSETON_1) & (gen["ts_naive"] == "2025-03-10 14:00")
    assert drop.sum() == 1
    frames[0] = (gen[~drop].reset_index(drop=True), raw_file)
    with pytest.raises(TimeIntegrityError, match=r"local day 2025-03-10 has 23 hours, expected 24"):
        build_fixture_table(frames, locations, market, *SPRING)


def test_missing_second_one_oclock_on_fall_back_is_refused(raw_dst_frames, locations, market):
    frames = raw_dst_frames("damlbmp")
    gen, raw_file = frames[0]
    ones = gen.index[(gen["location_ptid"] == ROSETON_1) & (gen["ts_naive"] == "2025-11-02 01:00")]
    frames[0] = (gen.drop(index=ones[1]).reset_index(drop=True), raw_file)
    with pytest.raises(TimeIntegrityError, match=r"local day 2025-11-02 has 24 hours, expected 25"):
        build_fixture_table(frames, locations, market, *FALL)


def test_duplicated_ordinary_hour_is_refused(raw_dst_frames, locations, market):
    frames = raw_dst_frames("damlbmp")
    gen, raw_file = frames[0]
    extra = gen[(gen["location_ptid"] == ROSETON_1) & (gen["ts_naive"] == "2025-03-10 14:00")]
    frames[0] = (pd.concat([gen, extra], ignore_index=True), raw_file)
    with pytest.raises(TimeIntegrityError, match="appears 2 times"):
        build_fixture_table(frames, locations, market, *SPRING)


def test_tripled_hour_is_refused(raw_dst_frames, locations, market):
    frames = raw_dst_frames("damlbmp")
    gen, raw_file = frames[0]
    extra = gen[(gen["location_ptid"] == ROSETON_1) & (gen["ts_naive"] == "2025-11-02 01:00")].head(1)
    frames[0] = (pd.concat([gen, extra], ignore_index=True), raw_file)
    with pytest.raises(TimeIntegrityError, match="more than twice"):
        build_fixture_table(frames, locations, market, *FALL)


def test_hour_inside_spring_gap_is_refused(raw_dst_frames, locations, market):
    frames = raw_dst_frames("damlbmp")
    gen, raw_file = frames[0]
    ghost = gen[(gen["location_ptid"] == ROSETON_1) & (gen["ts_naive"] == "2025-03-09 01:00")].copy()
    ghost["ts_naive"] = pd.Timestamp("2025-03-09 02:00")
    frames[0] = (pd.concat([gen, ghost], ignore_index=True), raw_file)
    with pytest.raises(TimeIntegrityError, match="cannot localize"):
        build_fixture_table(frames, locations, market, *SPRING)


def test_missing_whole_day_is_reported(raw_dst_frames, locations, market, timezone):
    table = build_fixture_table(raw_dst_frames("damlbmp"), locations, market, *SPRING)
    without_middle = table[table["ts_local"].dt.date != date(2025, 3, 9)]
    problems = time_integrity_problems(without_middle, timezone)
    assert len(problems) == len(locations)
    assert all("1 local days missing" in problem for problem in problems)


@pytest.mark.parametrize("name", ["lbmp_da", "lbmp_rt"])
def test_full_year_curated_table_has_complete_days(name: str, timezone: str, market: dict):
    table, _ = store.read_table(REPO_ROOT, name)
    assert time_integrity_problems(table, timezone) == []
    assert not table.duplicated(["location_ptid", "ts_utc"]).any()
    window = market["data_window"]
    for ptid, group in table.groupby("location_ptid"):
        days = hours_by_day(table, ptid)
        assert min(days) == window["start"] and max(days) == window["end"]
        assert sorted(set(days.values())) == [23, 24, 25]
        assert len(group) == 8760  # 2025: 365 days, one 23 h and one 25 h day
