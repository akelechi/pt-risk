"""Hourly settlement amounts. Milestone 1: day-ahead energy only.

These functions compute; they do not book. `engine.plant.state.transition` is the only
place ledger entries are created from them.
"""

from __future__ import annotations

HOUR_H = 1.0  # every settlement interval in this model is one hour


def da_energy_mwh(da_schedule_mw: float) -> float:
    """Energy sold day-ahead in one hour, MWh."""
    return da_schedule_mw * HOUR_H


def da_energy_revenue_usd(da_schedule_mw: float, da_lbmp_usd_per_mwh: float) -> float:
    """DA energy revenue for one hour: da_mw x 1 h x da_lbmp, in USD (unrounded)."""
    return da_energy_mwh(da_schedule_mw) * da_lbmp_usd_per_mwh
