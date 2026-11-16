"""Append-only ledger of hourly entries, with roll-ups as views.

Entries are only ever appended (by `transition()` from milestone 1). Nothing is stored
twice: daily and monthly figures are computed from the entries on request.
"""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Iterable, Literal

from engine.contracts import LedgerEntry, LedgerRollup

Grain = Literal["hour", "day", "month"]
_CENT = Decimal("0.01")


def round_to_cent_usd(amount_usd: float) -> float:
    """Round a dollar amount to the cent, half-even, via Decimal (no binary-float drift)."""
    return float(Decimal(repr(amount_usd)).quantize(_CENT, rounding=ROUND_HALF_EVEN))


def period_of(entry: LedgerEntry, grain: Grain) -> str:
    """Local period label of an entry: ISO hour, YYYY-MM-DD, or YYYY-MM (market local time)."""
    if grain == "hour":
        return entry.ts_local.isoformat()
    if grain == "day":
        return entry.ts_local.strftime("%Y-%m-%d")
    if grain == "month":
        return entry.ts_local.strftime("%Y-%m")
    raise ValueError(f"unknown grain {grain!r}")


class Ledger:
    """Append-only list of `LedgerEntry`. There is no update or delete."""

    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    def append(self, entries: Iterable[LedgerEntry]) -> None:
        for entry in entries:
            if not isinstance(entry, LedgerEntry):
                raise TypeError(f"ledger accepts LedgerEntry, got {type(entry).__name__}")
            self._entries.append(entry)

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def content_hash(self) -> str:
        """sha256 over the entries in order, each as canonical JSON. Used by invariant 8."""
        digest = hashlib.sha256()
        for entry in self._entries:
            payload = entry.model_dump(mode="json")
            payload["ts_local"] = entry.ts_utc.isoformat()  # hash the instant, not its rendering
            digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            digest.update(b"\n")
        return digest.hexdigest()

    def rollup(self, grain: Grain) -> list[LedgerRollup]:
        """Sum entries by local period x unit x line, in first-seen order."""
        return rollup(self._entries, grain)


def rollup(entries: Iterable[LedgerEntry], grain: Grain) -> list[LedgerRollup]:
    """Roll entries up to `grain`. Amounts in USD (re-rounded to the cent after summing)."""
    totals: dict[tuple[str, str, str], dict] = {}
    for entry in entries:
        key = (period_of(entry, grain), entry.unit_id, entry.line)
        bucket = totals.setdefault(
            key, {"quantity": 0.0, "quantity_unit": entry.quantity_unit, "amount": Decimal("0"), "count": 0}
        )
        if bucket["quantity_unit"] != entry.quantity_unit:
            raise ValueError(f"line {entry.line} mixes quantity units within {key[0]}")
        bucket["quantity"] += entry.quantity
        bucket["amount"] += Decimal(repr(entry.amount_usd))
        bucket["count"] += 1
    return [
        LedgerRollup(
            period=period,
            unit_id=unit_id,
            line=line,
            quantity=bucket["quantity"],
            quantity_unit=bucket["quantity_unit"],
            amount_usd=float(bucket["amount"].quantize(_CENT, rounding=ROUND_HALF_EVEN)),
            entry_count=bucket["count"],
        )
        for (period, unit_id, line), bucket in totals.items()
    ]
