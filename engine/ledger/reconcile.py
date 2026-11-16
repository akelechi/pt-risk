"""Invariants from brief §5. Each check returns an `InvariantResult`.

Milestone 0 implements 6 (time integrity), 7 (provenance) and 8 (reproducibility).
Invariants 1-5 need dispatch and settlement; until their milestone they report
`not_applicable` with the milestone that will switch them on. They never report `pass`
for something that was not checked.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from engine.contracts import InvariantResult
from engine.inputs.timeutil import time_integrity_problems
from engine.plant.params import provenance_problems

INVARIANT_NAMES = {
    1: "Energy balance",
    2: "Fuel balance",
    3: "Cost identity",
    4: "Revenue identity",
    5: "Margin bound",
    6: "Time integrity",
    7: "Provenance",
    8: "Reproducibility",
}
PENDING_MILESTONE = {1: 3, 2: 4, 3: 1, 4: 1, 5: 2}
_MAX_PROBLEMS_SHOWN = 5


def _result(invariant_id: int, problems: list[str], ok_detail: str) -> InvariantResult:
    if problems:
        shown = "; ".join(problems[:_MAX_PROBLEMS_SHOWN])
        more = f" (+{len(problems) - _MAX_PROBLEMS_SHOWN} more)" if len(problems) > _MAX_PROBLEMS_SHOWN else ""
        return InvariantResult(
            invariant_id=invariant_id, name=INVARIANT_NAMES[invariant_id], status="fail", detail=shown + more
        )
    return InvariantResult(
        invariant_id=invariant_id, name=INVARIANT_NAMES[invariant_id], status="pass", detail=ok_detail
    )


def pending(invariant_id: int) -> InvariantResult:
    """An invariant whose engine module does not exist yet."""
    return InvariantResult(
        invariant_id=invariant_id,
        name=INVARIANT_NAMES[invariant_id],
        status="not_applicable",
        detail=f"not checked: needs milestone {PENDING_MILESTONE[invariant_id]}",
    )


def check_time_integrity(
    hourly_tables: dict[str, pd.DataFrame],
    timezone: str,
    start_date: date,
    end_date: date,
    expected_ptids: set[int],
) -> InvariantResult:
    """Invariant 6: every local day has 23/24/25 hours matching DST; no duplicate ts_utc.

    Also requires each table to cover exactly [start_date, end_date] for every expected
    location, so a silently short table cannot pass.
    """
    problems: list[str] = []
    days = 0
    hours = 0
    for name, table in hourly_tables.items():
        problems.extend(f"{name}: {problem}" for problem in time_integrity_problems(table, timezone))
        present = set(table["location_ptid"].unique()) if not table.empty else set()
        for ptid in sorted(expected_ptids - present):
            problems.append(f"{name}: no rows for PTID {ptid}")
        if table.empty:
            continue
        local_date = table["ts_utc"].dt.tz_convert(timezone).dt.date
        for ptid, dates in local_date.groupby(table["location_ptid"]):
            if dates.min() != start_date or dates.max() != end_date:
                problems.append(
                    f"{name}: PTID {ptid} covers {dates.min()}..{dates.max()}, "
                    f"scenario needs {start_date}..{end_date}"
                )
        days += int(local_date.groupby(table["location_ptid"]).nunique().sum())
        hours += len(table)
    return _result(
        6,
        problems,
        f"{hours} hourly rows over {days} location-days in {len(hourly_tables)} tables; "
        "all days 23/24/25 h per DST, no duplicate ts_utc",
    )


def check_provenance(plant_raw: Any, leaf_count: int, assumed_count: int) -> InvariantResult:
    """Invariant 7: no plant parameter without status and source (all five fields)."""
    return _result(
        7,
        provenance_problems(plant_raw),
        f"{leaf_count} parameter leaves all carry value/unit/status/source/as_of; {assumed_count} assumed",
    )


def check_reproducibility(first_ledger_hash: str, second_ledger_hash: str, entry_count: int) -> InvariantResult:
    """Invariant 8: executing the scenario twice gives an identical ledger hash."""
    problems = (
        []
        if first_ledger_hash == second_ledger_hash
        else [f"ledger hash differs between two executions: {first_ledger_hash} vs {second_ledger_hash}"]
    )
    return _result(8, problems, f"two executions, identical ledger hash over {entry_count} entries")
