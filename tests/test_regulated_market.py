"""62N-91: futures/option losses are deductible for individuals only on a regulated (or equivalent) market."""
import io

import pytest
from openpyxl import load_workbook

from ibkr_yhteenveto import load
from ibkr_yhteenveto.excel_personal import write_personal_workbook
from ibkr_yhteenveto.personal import PSettings, build_personal, omavero_fields

CSV = """Statement,Header,Field Name,Field Value
Statement,Data,Period,"January 1, 2026 - December 31, 2026"
Account Information,Header,Field Name,Field Value
Account Information,Data,Account,U0000000
Account Information,Data,Base Currency,EUR
Realized & Unrealized Performance Summary,Header,Asset Category,Symbol,Cost Adj.,Realized S/T Profit,Realized S/T Loss,Realized L/T Profit,Realized L/T Loss,Realized Total,Unrealized S/T Profit,Unrealized S/T Loss,Unrealized L/T Profit,Unrealized L/T Loss,Unrealized Total,Total,Code
Realized & Unrealized Performance Summary,Data,Futures,ESZ6,0,1000,-400,0,0,600,0,0,0,0,0,600,
Realized & Unrealized Performance Summary,Data,Futures,XXZ6,0,300,-700,0,0,-400,0,0,0,0,0,-400,
Realized & Unrealized Performance Summary,Data,Futures,YYZ6,0,0,-100,0,0,-100,0,0,0,0,0,-100,
Financial Instrument Information,Header,Asset Category,Symbol,Description,Conid,Underlying,Listing Exch,Multiplier,Expiry,Delivery Month,Code
Financial Instrument Information,Data,Futures,ESZ6,ES 18DEC26,1,ES,CME,50,2026-12-18,2026-12,
Financial Instrument Information,Data,Futures,XXZ6,XX 18DEC26,2,XX,OFFSHORE,10,2026-12-18,2026-12,
"""


def build(**kw):
    return build_personal(load([("s.csv", CSV.encode())]), PSettings(**kw))


def test_losses_off_regulated_markets_not_deductible():
    pb = build()
    v = pb.v
    assert v["der_gains"] == 1300                          # gains are taxable everywhere
    assert v["der_losses"] == -500                         # CME −400 + unknown exchange −100 (assumed regulated)
    assert v["der_losses_nondeductible"] == -700           # OFFSHORE
    assert any("OFFSHORE" in w for w in pb.warnings) and any("Markkinapaikka tuntematon" in w for w in pb.warnings)
    f = {k: val for _, k, val, _ in omavero_fields(pb)}
    assert f["Vähennyskelvottomat johdannaistappiot (ei säännelty markkina)"] == 700


def test_user_can_add_an_equivalent_market():
    v = build(extra_regulated="offshore").v
    assert v["der_losses"] == -1200 and v["der_losses_nondeductible"] == 0


def test_workbook_counts_only_deductible_losses():
    ws = load_workbook(io.BytesIO(write_personal_workbook(build())))["Johdannaiset"]
    row = next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 2).value == "XXZ6")
    assert ws.cell(row, 4).value == 0 and "vähennyskelvoton" in ws.cell(row, 6).value
    assert any(ws.cell(r, 1).value == "Vähennyskelvottomat tappiot (ei mukana)" for r in range(1, ws.max_row + 1))
