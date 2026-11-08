"""62N-85: CFDs for individuals — gains are other capital income per trade, losses are ignored (synthetic data only)."""
import io

import pytest
from openpyxl import load_workbook

from ibkr_yhteenveto import Settings, build
from ibkr_yhteenveto.excel_personal import write_personal_workbook
from ibkr_yhteenveto.model import CashLine, RURow, Statement
from ibkr_yhteenveto.parse_csv import parse_csv
from ibkr_yhteenveto.personal import PSettings, build_personal, omavero_fields
from ibkr_yhteenveto.report import personal as personal_report

HEAD = """Statement,Header,Field Name,Field Value
Statement,Data,Title,Activity Statement
Statement,Data,Period,"January 1, 2026 - December 31, 2026"
Account Information,Header,Field Name,Field Value
Account Information,Data,Name,Esimerkki Henkilo
Account Information,Data,Account,U0000000
Account Information,Data,Customer Type,Individual
Account Information,Data,Base Currency,EUR
Realized & Unrealized Performance Summary,Header,Asset Category,Symbol,Cost Adj.,Realized S/T Profit,Realized S/T Loss,Realized L/T Profit,Realized L/T Loss,Realized Total,Unrealized S/T Profit,Unrealized S/T Loss,Unrealized L/T Profit,Unrealized L/T Loss,Unrealized Total,Total,Code
"""
TRADES_HDR = ("Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,"
              "Notional Value,Comm/Fee,Basis,Realized P/L,MTM P/L,Code\n")

# EUR CFDs: closing trades +500, -300, +200 (opening trades have no realized P/L); a futures loss of -1000
CSV_EUR = HEAD + """Realized & Unrealized Performance Summary,Data,CFDs,AAA,0,700,-300,0,0,400,0,0,0,0,0,400,
Realized & Unrealized Performance Summary,Data,Futures,FUT1,0,0,-1000,0,0,-1000,0,0,0,0,0,-1000,
""" + TRADES_HDR + """Trades,Data,Order,CFDs,EUR,AAA,"2026-02-02, 10:00:00",100,10,10,-1000,-1,1000,0,0,O
Trades,Data,Order,CFDs,EUR,AAA,"2026-02-03, 10:00:00",-100,15,15,1500,-1,-1000,500,0,C
Trades,Data,Order,CFDs,EUR,AAA,"2026-03-02, 10:00:00",100,20,20,-2000,-1,2000,0,0,O
Trades,Data,Order,CFDs,EUR,AAA,"2026-03-03, 10:00:00",-100,17,17,1700,-1,-2000,-300,0,C
Trades,Data,Order,CFDs,EUR,AAA,"2026-04-02, 10:00:00",-100,30,30,3000,-1,-3000,0,0,O
Trades,Data,Order,CFDs,EUR,AAA,"2026-04-03, 10:00:00",100,28,28,-2800,-1,3000,200,0,C
Trades,Total,,CFDs,EUR,,,,,,1400,-6,0,400,0,
"""

# USD CFDs: commissions -10 USD = -9 EUR -> rate 0.9; closing trades +100 USD and -50 USD
CSV_USD = HEAD + """Realized & Unrealized Performance Summary,Data,CFDs,BBB,0,90,-45,0,0,45,0,0,0,0,0,45,
""" + TRADES_HDR + """Trades,Data,Order,CFDs,USD,BBB,"2026-05-04, 15:00:00",10,100,100,-1000,-2.5,1000,0,0,O
Trades,Data,Order,CFDs,USD,BBB,"2026-05-05, 15:00:00",-10,110,110,1100,-2.5,-1000,100,0,C
Trades,Data,Order,CFDs,USD,BBB,"2026-06-04, 15:00:00",10,100,100,-1000,-2.5,1000,0,0,O
Trades,Data,Order,CFDs,USD,BBB,"2026-06-05, 15:00:00",-10,95,95,950,-2.5,-1000,-50,0,C
Trades,Total,,CFDs,USD,,,,,,50,-10,0,50,0,
Trades,Total,,CFDs,EUR,,,,,,45,-9,0,45,0,
"""


def test_cfd_trades_parsed():
    st = parse_csv(CSV_EUR)
    assert [(x["date"], x["eur"]) for x in st.cfd_trades] == [("2026-02-03", 500), ("2026-03-03", -300), ("2026-04-03", 200)]
    st = parse_csv(CSV_USD)
    assert [round(x["eur"], 2) for x in st.cfd_trades] == [90.0, -45.0]


def test_cfd_gains_taxable_losses_ignored():
    pb = build_personal(parse_csv(CSV_EUR), PSettings())
    v = pb.v
    assert v["cfd_gains"] == pytest.approx(700)            # per trade, not the symbol net 400
    assert v["cfd_losses_ignored"] == pytest.approx(-300)
    assert v["der_losses"] == pytest.approx(-1000)          # futures losses stay deductible disposals
    assert v["disp_net"] == pytest.approx(-1000)            # CFDs are not disposals (9A)
    assert v["capital_income"] == pytest.approx(700 - 1000)
    assert not any("CFD" in r.asset_class for r in pb.derivatives)
    fields = {f: (sec, val) for sec, f, val, _ in omavero_fields(pb)}
    assert fields["Muut pääomatulot — CFD-voitot"] == ("Ulkomaan pääomatulot (OmaVero / 16B)", pytest.approx(700))
    assert fields["Vähennyskelvottomat CFD-tappiot (ei huomioida)"][1] == pytest.approx(300)
    assert not any("CFD" in f for f in fields if "Johdannaiset" in f)


def test_cfd_fallback_ru_without_trades():
    st = Statement(base_currency="EUR")
    st.ru = [RURow("CFDs", "AAA", st_profit=700, st_loss=-300)]
    pb = build_personal(st, PSettings())
    assert (pb.v["cfd_gains"], pb.v["cfd_losses_ignored"]) == (700, -300)
    assert any("R&U-yhteenvedosta" in w for w in pb.warnings)


def test_cfd_financing_not_deducted():
    st = parse_csv(CSV_EUR)
    st.interest = [CashLine("2026-02-28", "EUR", "EUR Debit Interest for Feb-2026", -40, -40),
                   CashLine("2026-02-28", "EUR", "CFD Financing AAA Feb-2026", -10, -10)]
    st.fees = [CashLine("2026-02-28", "EUR", "CFD Dividend Adjustment AAA", -5, -5)]
    st.fees_total_eur = -5
    v = build_personal(st, PSettings()).v
    assert (v["int_expense"], v["fees"], v["cfd_costs_ignored"]) == (40, 0, 15)


def test_cfd_workbook_formulas_match_engine():
    st = parse_csv(CSV_EUR)
    st.interest = [CashLine("2026-02-28", "EUR", "CFD Financing AAA Feb-2026", -10, -10)]
    pb = build_personal(st, PSettings())
    wb = load_workbook(io.BytesIO(write_personal_workbook(pb)))
    de = wb["Johdannaiset"]
    labels = {de.cell(r, 1).value: de.cell(r, 3).value for r in range(1, de.max_row + 1)}
    assert labels["Voitot (veronalainen muu pääomatulo)"].startswith('=SUMIF(C')
    po = wb["Pääomatulo & vero"]
    rows = {po.cell(r, 1).value: po.cell(r, 2).value for r in range(1, po.max_row + 1)}
    assert "CFD-voitot (voitolliset kaupat)" in rows
    pi = rows["PÄÄOMATULO (IBKR-osuus)"]
    cfd_row = next(r for r in range(1, po.max_row + 1) if po.cell(r, 1).value == "CFD-voitot (voitolliset kaupat)")
    assert f"B{cfd_row}" in pi                                        # CFD gains are in capital income
    info = next(r for r in range(1, po.max_row + 1) if (po.cell(r, 1).value or "").startswith("Tieto: CFD-tappiot"))
    assert f"B{info}" not in pi                                       # ignored losses are not
    kk = wb["Korot & kulut"]
    kinds = [kk.cell(r, 6).value for r in range(1, kk.max_row + 1)]
    assert "CFD-kulu (ei vähennyskelpoinen)" in kinds


def test_cfd_report_tab():
    res, xlsx = personal_report(parse_csv(CSV_EUR), PSettings())
    assert "CFD:t" in res["tabs"] and xlsx[:2] == b"PK"
    calc = dict((r[0], r[1]) for r in res["tabs"]["Pääomatulolaskelma"]["rows"])
    assert calc["CFD-voitot (muu pääomatulo)"] == pytest.approx(700)
    res2, _ = personal_report(Statement(base_currency="EUR"), PSettings())
    assert "CFD:t" not in res2["tabs"]


def test_company_mode_unchanged_by_cfd():
    st = parse_csv(CSV_EUR)
    b = build(st, Settings())
    assert b.v["gains"] == pytest.approx(700) and b.v["losses"] == pytest.approx(-1300)
