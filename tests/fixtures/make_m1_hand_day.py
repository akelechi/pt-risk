"""Write tests/fixtures/m1_hand_day.xlsx: one day of price-taker dispatch, worked by formula.

Usage:  python tests/fixtures/make_m1_hand_day.py

The workbook holds INPUTS (typed) and FORMULAS (Excel computes them when opened). It does
not import the engine. The expected values asserted in tests/test_settlement.py were
worked by hand from the same inputs and are written there as literals; open the workbook
to check them.

Toy unit (the brief's original example): Pmin 150, Pmax 600, incremental heat rates
11.4 / 10.1 / 10.0 / 10.8 MMBtu/MWh for the blocks ending at 150 / 300 / 450 / 600 MW,
VOM 3.00 $/MWh, fully available. Gas 4.00 $/MMBtu.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

TARGET = Path(__file__).resolve().parent / "m1_hand_day.xlsx"
# hour-beginning local hour -> DA LBMP ($/MWh)
LBMP_BY_HOUR = [40.00] * 6 + [45.00] * 2 + [45.50] * 8 + [50.00] * 4 + [40.00] * 4

if __name__ == "__main__":
    book = Workbook()
    inputs = book.active
    inputs.title = "inputs"
    inputs.append(["gas_price_usd_per_mmbtu", 4.00])
    inputs.append(["vom_usd_per_mwh", 3.00])
    inputs.append([])
    inputs.append(["block_to_mw", "width_mw", "ihr_mmbtu_per_mwh", "block_fuel_mmbtu_per_h"])
    for row, (to_mw, width, ihr) in enumerate([(150, 150, 11.4), (300, 150, 10.1), (450, 150, 10.0), (600, 150, 10.8)], start=5):
        inputs.append([to_mw, width, ihr, f"=B{row}*C{row}"])
    inputs.append([])
    inputs.append(["Convexified offer (blocks 1-3 pooled: 11.4 > 10.1 > 10.0, then 10.8 is above the pool)"])
    inputs.append(["step_to_mw", "pooled_ihr", "offer_usd_per_mwh", "fuel_at_step_mmbtu_per_h"])
    inputs.append([450, "=SUM(D5:D7)/450", "=ROUND(B12*$B$1+$B$2,2)", "=SUM(D5:D7)"])
    inputs.append([600, "=C8", "=ROUND(B13*$B$1+$B$2,2)", "=SUM(D5:D8)"])

    hours = book.create_sheet("hours")
    hours.append(["hour_beginning_local", "da_lbmp_usd_per_mwh", "mw", "fuel_mmbtu", "da_energy_rev_usd",
                  "fuel_cost_usd", "vom_usd", "margin_usd"])
    for index, lbmp in enumerate(LBMP_BY_HOUR):
        row = index + 2
        hours.append([
            index,
            lbmp,
            f"=IF(B{row}>inputs!$C$13,600,IF(B{row}>inputs!$C$12,450,0))",  # strict >: a tie does not run
            f"=IF(C{row}=600,inputs!$D$13,IF(C{row}=450,inputs!$D$12,0))",
            f"=ROUND(C{row}*B{row},2)",
            f"=-ROUND(D{row}*inputs!$B$1,2)",
            f"=-ROUND(C{row}*inputs!$B$2,2)",
            f"=E{row}+F{row}+G{row}",
        ])
    hours.append(["total", None, "=SUM(C2:C25)", "=SUM(D2:D25)", "=SUM(E2:E25)", "=SUM(F2:F25)", "=SUM(G2:G25)", "=SUM(H2:H25)"])
    book.save(TARGET)
    print(f"wrote {TARGET}")
