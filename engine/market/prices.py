"""Price lookups over curated tables, returning the value together with its row id.

Row ids (`ref`) let every ledger entry name the exact input rows it used.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


class MissingPriceError(LookupError):
    """No usable input price for a requested hour or day."""


def lbmp_row_ref(source_id: str, location_ptid: int, ts_utc: pd.Timestamp) -> str:
    """Id of one LBMP row: '<source_id>:<ptid>:<ts_utc ISO>'."""
    return f"{source_id}:{location_ptid}:{ts_utc.isoformat()}"


def gas_row_ref(source_id: str, point: str, published: date) -> str:
    """Id of one gas price row: '<source_id>:<point>:<published date>'."""
    return f"{source_id}:{point}:{published.isoformat()}"


class GasPrices:
    """Daily gas prices for one point, with the last-published-price rule (Q-012).

    A gas day with no published price (weekend, holiday) uses the last price published on
    or before it, provided that price is at most `max_staleness_days` old. The gas day is
    taken as the local calendar day (Q-023).
    """

    def __init__(self, table: pd.DataFrame, point: str, max_staleness_days: int) -> None:
        rows = table[table["point"] == point].sort_values("date")
        self._point = point
        self._max_staleness = timedelta(days=max_staleness_days)
        self._dates: list[date] = rows["date"].tolist()
        self._prices: list[float] = rows["price_usd_per_mmbtu"].tolist()
        self._source_ids: list[str] = rows["source_id"].tolist()

    def on(self, gas_day: date) -> tuple[float, str]:
        """(price in $/MMBtu, row ref) applying to `gas_day`."""
        index = pd.Index(self._dates).searchsorted(gas_day, side="right") - 1
        if index < 0:
            raise MissingPriceError(f"no {self._point} gas price on or before {gas_day}")
        published = self._dates[index]
        if gas_day - published > self._max_staleness:
            raise MissingPriceError(
                f"latest {self._point} gas price before {gas_day} is {published}, "
                f"older than {self._max_staleness.days} days"
            )
        return float(self._prices[index]), gas_row_ref(self._source_ids[index], self._point, published)


def delivered_gas_price_usd_per_mmbtu(
    index_price_usd_per_mmbtu: float, basis_adder_usd_per_mmbtu_by_month: dict[int, float], gas_day: date
) -> tuple[float, float]:
    """(delivered price, basis adder), both $/MMBtu, for `gas_day`.

    Delivered gas = published index price + the plant config's assumed adder for the gas
    day's calendar month (Q-028). Milestone 5 replaces the adder with a published
    delivered index when module `gas_basis` is on.
    """
    adder = float(basis_adder_usd_per_mmbtu_by_month[gas_day.month])
    return index_price_usd_per_mmbtu + adder, adder
