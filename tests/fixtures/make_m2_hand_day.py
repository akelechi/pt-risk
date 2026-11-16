"""Write tests/fixtures/m2_hand_day.xlsx: one day of commitment with start and no-load cost.

Usage:  python tests/fixtures/make_m2_hand_day.py

The workbook holds INPUTS (typed) and FORMULAS (Excel computes them when opened). It does
not import the engine. The expected values asserted in tests/test_commitment.py and
tests/test_settlement.py were worked by hand from the same inputs and are written there
as literals; open the workbook to check them.

Toy unit (the brief's original example): Pmin 150, Pmax 600, incremental heat rates
11.4 / 10.1 / 10.0 / 10.8 MMBtu/MWh for the blocks ending at 150 / 300 / 450 / 600 MW,
VOM 3.00 $/MWh, no-load 400 MMBtu/h, minimum up 8 h, minimum down 6 h, cold start
5,000 MMBtu + 25,000 $, hot start 1,500 MMBtu + 8,000 $. Gas 4.00 $/MMBtu. The unit
begins the day cold (168 h off).

Two plans are evaluated on the same prices:
  plan A (the DP optimum): on hours 6-21, riding through the 44 $/MWh dip;
  plan B (the price-taker made feasible): on 6-13, off 14-19, hot start at 20, on 20-23.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

TARGET = Path(__file__).resolve().parent / "m2_hand_day.xlsx"
LBMP_BY_HOUR = [40.00] * 6 + [60.00] * 4 + [44.00] * 6 + [70.00] * 6 + [40.00] * 2
PLAN_A_ON = [0] * 6 + [1] * 16 + [0] * 2
PLAN_B_ON = [0] * 6 + [1] * 8 + [0] * 6 + [1] * 4
PLAN_B_START_COST = {6: "=inputs!$B$9", 20: "=inputs!$B$10"}

if __name__ == "__main__":
    book = Workbook()
    inputs = book.active
    inputs.title = "inputs"
    inputs.append(["gas_price_usd_per_mmbtu", 4.00])                                  # B1
    inputs.append(["vom_usd_per_mwh", 3.00])                                          # B2
    inputs.append(["no_load_mmbtu_per_h", 400])                                       # B3
    inputs.append(["fuel_at_150_mw_mmbtu_per_h", "=150*11.4"])                        # B4
    inputs.append(["fuel_at_450_mw_mmbtu_per_h", "=B4+150*10.1+150*10.0"])            # B5
    inputs.append(["fuel_at_600_mw_mmbtu_per_h", "=B5+150*10.8"])                     # B6
    inputs.append(["offer_150_to_450_usd_per_mwh", "=ROUND((150*10.1+150*10.0)/300*B1+B2,2)"])  # B7
    inputs.append(["offer_450_to_600_usd_per_mwh", "=ROUND(10.8*B1+B2,2)"])           # B8
    inputs.append(["cold_start_cost_usd", "=5000*B1+25000"])                          # B9
    inputs.append(["hot_start_cost_usd", "=1500*B1+8000"])                            # B10

    for title, flags, start_cost in (
        ("plan_a_dp", PLAN_A_ON, {6: "=inputs!$B$9"}),
        ("plan_b_price_taker_constrained", PLAN_B_ON, PLAN_B_START_COST),
    ):
        sheet = book.create_sheet(title)
        sheet.append(["hour_beginning_local", "da_lbmp_usd_per_mwh", "on", "mw", "fuel_mmbtu", "da_energy_rev_usd",
                      "fuel_cost_usd", "no_load_cost_usd", "vom_usd", "start_cost_usd", "margin_usd"])
        for index, (lbmp, on) in enumerate(zip(LBMP_BY_HOUR, flags)):
            row = index + 2
            sheet.append([
                index,
                lbmp,
                on,
                # on line: Pmin, plus each step above Pmin priced strictly below the LBMP
                f"=IF(C{row}=0,0,IF(B{row}>inputs!$B$8,600,IF(B{row}>inputs!$B$7,450,150)))",
                f"=IF(D{row}=600,inputs!$B$6,IF(D{row}=450,inputs!$B$5,IF(D{row}=150,inputs!$B$4,0)))",
                f"=ROUND(D{row}*B{row},2)",
                f"=-ROUND(E{row}*inputs!$B$1,2)",
                f"=-ROUND(C{row}*inputs!$B$3*inputs!$B$1,2)",
                f"=-ROUND(D{row}*inputs!$B$2,2)",
                f"=-({start_cost[index][1:]})" if index in start_cost else 0,
                f"=SUM(F{row}:J{row})",
            ])
        sheet.append(["total", None, "=SUM(C2:C25)", "=SUM(D2:D25)", "=SUM(E2:E25)", "=SUM(F2:F25)", "=SUM(G2:G25)",
                      "=SUM(H2:H25)", "=SUM(I2:I25)", "=SUM(J2:J25)", "=SUM(K2:K25)"])
    uplift = book.create_sheet("uplift_plan_b")
    uplift.append(["Plan B, first commitment block (hours 6-13): costs less DA revenue, floored at 0"])
    uplift.append(["block_cost_usd", "=-SUM(plan_b_price_taker_constrained!G8:J15)"])
    uplift.append(["block_da_revenue_usd", "=SUM(plan_b_price_taker_constrained!F8:F15)"])
    uplift.append(["uplift_usd", "=MAX(0,B2-B3)"])
    book.save(TARGET)
    print(f"wrote {TARGET}")
