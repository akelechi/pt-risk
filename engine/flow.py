"""Flow-diagram payloads: one `HourFlow` per unit and hour, built from a RunResult.

Every figure the UI puts on an arrow is taken from here. Dollar figures are sums of the
hour's ledger entries; nothing is re-derived from prices.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from engine.contracts import HourFlow, LedgerEntry, RunResult
from engine.run import ENERGY_MARGIN_LINES

FUEL_LINES = ("fuel_cost_gas", "fuel_cost_oil")


def _sum_usd(entries: list[LedgerEntry], lines: tuple[str, ...]) -> float:
    return float(sum((Decimal(repr(entry.amount_usd)) for entry in entries if entry.line in lines), Decimal("0")))


def hour_flows(result: RunResult, unit_id: str | None = None, month: str | None = None) -> list[HourFlow]:
    """Flow payloads in run order, optionally for one unit and/or one local month (YYYY-MM)."""
    entries_by_hour: dict[tuple[str, datetime], list[LedgerEntry]] = defaultdict(list)
    for entry in result.ledger:
        entries_by_hour[(entry.unit_id, entry.ts_utc)].append(entry)
    offers = {(offer.unit_id, offer.local_date): offer for offer in result.offers}

    flows: list[HourFlow] = []
    for state, decision, inputs in zip(result.states, result.decisions, result.hour_inputs, strict=True):
        if unit_id is not None and state.unit_id != unit_id:
            continue
        if month is not None and state.ts_local.strftime("%Y-%m") != month:
            continue
        offer = offers[(state.unit_id, state.ts_local.date())]
        entries = entries_by_hour.get((state.unit_id, state.ts_utc), [])
        fuel_entries = [entry for entry in entries if entry.line in FUEL_LINES]
        flows.append(
            HourFlow(
                ts_utc=state.ts_utc,
                ts_local=state.ts_local,
                unit_id=state.unit_id,
                state=state,
                decision=decision,
                da_lbmp_usd_per_mwh=inputs.da_lbmp_usd_per_mwh,
                offered_mw=offer.blocks[-1].mw_to if offer.blocks else 0.0,
                offer_min_price_usd_per_mwh=offer.blocks[0].price_usd_per_mwh if offer.blocks else None,
                offer_max_price_usd_per_mwh=offer.blocks[-1].price_usd_per_mwh if offer.blocks else None,
                offer_blocks=offer.blocks,
                da_schedule_mw=state.da_schedule_mw,
                output_mw=state.output_mw,
                gas_price_usd_per_mmbtu=inputs.gas_price_usd_per_mmbtu,
                gas_burn_mmbtu=sum(entry.quantity for entry in fuel_entries if entry.line == "fuel_cost_gas"),
                da_energy_rev_usd=_sum_usd(entries, ("da_energy_rev",)),
                fuel_cost_usd=_sum_usd(entries, FUEL_LINES),
                vom_usd=_sum_usd(entries, ("vom",)),
                hour_energy_margin_usd=_sum_usd(entries, ENERGY_MARGIN_LINES),
                entries=entries,
                input_refs={"lbmp_da": inputs.da_lbmp_ref, "gas_price": inputs.gas_price_ref},
            )
        )
    return flows


def hour_flow(result: RunResult, unit_id: str, ts_utc: datetime) -> HourFlow | None:
    """Flow payload for one unit and hour, or None if the run has no such hour."""
    for flow in hour_flows(result, unit_id=unit_id):
        if flow.ts_utc == ts_utc:
            return flow
    return None
