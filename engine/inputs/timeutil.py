"""Local-time handling for hourly market data, with DST made explicit.

NYISO stamps hourly rows with naive local prevailing time, hour-beginning:
* spring-forward day (23 h): the 02:00 hour does not exist and is absent;
* fall-back day (25 h): 01:00 appears twice with no marker. File order is the only
  disambiguator: the first 01:00 is daylight time (EDT), the second standard time (EST).

Nothing here drops or duplicates an hour silently; problems are raised or reported.
"""

from __future__ import annotations

import pandas as pd


class TimeIntegrityError(ValueError):
    """Hourly data does not form complete, non-duplicated local days."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        shown = problems[:10]
        more = f"\n  ... and {len(problems) - 10} more" if len(problems) > 10 else ""
        super().__init__("time integrity problems:\n  " + "\n  ".join(shown) + more)


def localize_hour_beginning(
    ts_naive: pd.Series, group: pd.Series, timezone: str
) -> tuple[pd.Series, pd.Series]:
    """Convert naive local hour-beginning stamps to (ts_utc, ts_local).

    ts_naive: naive datetime64 local wall-clock stamps, in file order.
    group:    the series identifying each location (same index); repeated stamps are
              counted per location.
    Returns tz-aware UTC and tz-aware `timezone` series with the same index.

    A stamp repeated within one location is read as the fall-back hour: first occurrence
    daylight time, second standard time. More than two occurrences, or a stamp inside the
    spring-forward gap, raises.
    """
    occurrence = ts_naive.groupby([group, ts_naive]).cumcount()
    if (occurrence > 1).any():
        bad = ts_naive[occurrence > 1].iloc[0]
        raise TimeIntegrityError([f"local stamp {bad} appears more than twice for one location"])
    is_first_occurrence = (occurrence == 0).to_numpy()
    try:
        localized = pd.DatetimeIndex(ts_naive).tz_localize(
            timezone, ambiguous=is_first_occurrence, nonexistent="raise"
        )
    except Exception as error:  # pytz/zoneinfo raise different types for the DST gap
        raise TimeIntegrityError([f"cannot localize stamps to {timezone}: {error}"]) from error
    ts_local = pd.Series(localized, index=ts_naive.index)
    ts_utc = ts_local.dt.tz_convert("UTC")
    return ts_utc, ts_local


def expected_hours_in_local_day(local_dates: pd.Series, timezone: str) -> pd.Series:
    """Hours in each local calendar day (23, 24 or 25), from the timezone rules.

    local_dates: series of datetime.date. Returns an int series with the same index.
    """
    midnight = pd.to_datetime(local_dates)
    start = pd.DatetimeIndex(midnight).tz_localize(timezone)
    end = pd.DatetimeIndex(midnight + pd.Timedelta(days=1)).tz_localize(timezone)
    hours = (end - start) / pd.Timedelta(hours=1)
    return pd.Series(hours.astype(int), index=local_dates.index)


def time_integrity_problems(
    frame: pd.DataFrame, timezone: str, location_column: str = "location_ptid"
) -> list[str]:
    """Check invariant 6 on an hourly table; returns human-readable problems (empty = ok).

    * no duplicate `ts_utc` per location;
    * every stamp is on the hour;
    * every local day present has exactly the 23/24/25 hours the DST rules call for;
    * the days present are contiguous (no missing day inside the covered range).
    """
    problems: list[str] = []
    if frame.empty:
        return problems
    ts_utc = frame["ts_utc"]
    ts_local = ts_utc.dt.tz_convert(timezone)

    duplicated = frame.duplicated(subset=[location_column, "ts_utc"], keep=False)
    for (location, stamp), count in (
        frame[duplicated].groupby([location_column, "ts_utc"]).size().items()
    ):
        problems.append(f"{location}: ts_utc {stamp} appears {count} times")

    off_hour = (ts_utc.dt.minute != 0) | (ts_utc.dt.second != 0)
    if off_hour.any():
        problems.append(f"{int(off_hour.sum())} stamps are not on the hour")

    local_date = ts_local.dt.date
    counts = frame.groupby([frame[location_column], local_date]).size()
    counts.index = counts.index.set_names([location_column, "local_date"])
    counts = counts.rename("hours").reset_index()
    counts["expected"] = expected_hours_in_local_day(counts["local_date"], timezone)
    for row in counts[counts["hours"] != counts["expected"]].itertuples(index=False):
        problems.append(
            f"{getattr(row, location_column)}: local day {row.local_date} has {row.hours} hours, "
            f"expected {row.expected}"
        )

    for location, days in counts.groupby(location_column)["local_date"]:
        ordered = sorted(days)
        span_days = (ordered[-1] - ordered[0]).days + 1
        if span_days != len(ordered):
            problems.append(
                f"{location}: {span_days - len(ordered)} local days missing between "
                f"{ordered[0]} and {ordered[-1]}"
            )
    return problems
