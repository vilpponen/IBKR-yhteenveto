"""62N-89: hankintameno-olettama per lot — 20 % (40 % if held ≥ 10 years) of the GROSS sale price, used when it gives
the lower gain; no costs are deducted with it; it never creates a loss (synthetic data)."""
from decimal import Decimal
import io

import pytest
from openpyxl import load_workbook

from ibkr_yhteenveto import _leg_commissions, load
from ibkr_yhteenveto.excel_personal import write_personal_workbook
from ibkr_yhteenveto.model import Statement
from ibkr_yhteenveto.personal import PSettings, build_personal, omavero_fields
from test_options import OPT, STK, csv, t


def one(data: bytes, **kw):
    pb = build_personal(load([("s.csv", data)]), PSettings(**kw))
    return pb, pb.matches[0]


CHEAP = csv(t(STK, "AAA", "2026-01-05", 1, 10, -10, 0, 10, "O") + t(STK, "AAA", "2026-03-05", -1, 100, 100, 0, -10, "C"))


def test_olettama_when_it_gives_lower_gain():
    pb, m = one(CHEAP)                       # bought 10 €, sold 100 €: olettama 20 € > actual 10 €
    assert (m.proceeds, m.cost, m.presumption, m.deduction, m.result) == (100, 10, 20, 20, 80)
    assert m.presumption_used and "olettama 20 %" in m.source
    assert pb.v["presumption_lots"] == 1 and pb.v["presumption_benefit"] == pytest.approx(10)
    _, m = one(CHEAP, use_presumption=False)
    assert m.result == 90 and not m.presumption_used


def test_forty_percent_after_ten_years():
    st = load([("s.csv", csv(t(STK, "AAA", "2026-03-05", -1, 100, 100, 0, -10, "C")))])
    ch = {"AAA": {"method": "lots", "lots": [{"date": "2014-01-15", "qty": 1, "cost_eur": 10}]}}
    m = build_personal(st, PSettings(opening_choices=ch)).matches[0]
    assert m.presumption_rate == Decimal("0.4") and m.deduction == pytest.approx(40) and m.result == pytest.approx(60)


def test_gross_price_and_no_costs_with_olettama():
    # buy 10 @ 10 + 1 € commission; sell 10 @ 100 − 5 € commission
    data = csv(t(STK, "AAA", "2026-01-05", 10, 10, -100, -1, 101, "O")
               + t(STK, "AAA", "2026-03-05", -10, 100, 1000, -5, -101, "C"))
    _, m = one(data)
    assert (m.proceeds, m.cost) == (1000, 106)          # gross price; actual costs incl. both commissions
    assert m.deduction == 200 and m.result == 800        # olettama of the GROSS price, no commissions deducted
    _, m = one(data, use_presumption=False)
    assert m.result == 894                                # same as before 62N-89: net 995 − cost 101


def test_put_exercise_shares_use_gross_before_premium():
    data = csv(t(STK, "BBB", "2026-01-05", 100, 10, -1000, 0, 1000, "O")
               + t(OPT, "BBB 17JUN26 95 P", "2026-02-02", 1, 1.5, -150, 0, 150, "O")
               + t(OPT, "BBB 17JUN26 95 P", "2026-06-17", -1, 0, 0, 0, -150, "C;Ex")
               + t(STK, "BBB", "2026-06-17", -100, 95, 9500, 0, -1000, "C;Ex"))
    _, m = one(data)
    assert (m.proceeds, m.cost) == (9500, 1150)           # gross strike price; costs incl. the put premium
    assert m.deduction == pytest.approx(1900) and m.result == pytest.approx(7600)


def test_never_creates_or_increases_a_loss():
    data = csv(t(STK, "AAA", "2026-01-05", 100, 100, -10000, 0, 10000, "O")
               + t(STK, "AAA", "2026-03-05", -100, 90, 9000, 0, -10000, "C"))
    _, m = one(data)
    assert m.result == -1000 and not m.presumption_used


def test_omavero_fields_and_workbook_formulas():
    pb, _ = one(CHEAP)
    f = {k: v for _, k, v, _ in omavero_fields(pb)}
    assert f["Osakkeet ja rahastot — luovutushinnat yhteensä"] == 100
    assert f["Osakkeet ja rahastot — hankintamenot ja kulut (tai hankintameno-olettamat) yhteensä"] == 20
    ws = load_workbook(io.BytesIO(write_personal_workbook(pb)))["Luovutukset (FIFO)"]
    row = next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value == "AAA")
    assert ws.cell(row, 7).value == f"=E{row}-M{row}" and "MAX(F" in ws.cell(row, 13).value
    assert ws.cell(row, 11).value == 0.2 and ws.cell(row, 12).value == f"=E{row}*K{row}"


def test_pdf_lots_get_their_commission_share():
    st = Statement(base_currency="EUR")
    st.trade_rows = [{"date": "2026-01-02", "time": "11:07:48", "symbol": "AAA", "qty": -350, "comm": 7.0, "ccy": "USD"}]
    st.stock_legs = [   # two FX lots of one order, net of commission (USD cash → EUR at 0.9)
        {"date": "2026-01-02", "time": "11:07:48", "symbol": "AAA", "qty": -100, "cash": 1000.0, "eur": 900.0},
        {"date": "2026-01-02", "time": "11:07:48", "symbol": "AAA", "qty": -250, "cash": 2500.0, "eur": 2250.0}]
    _leg_commissions(st)
    assert [round(x["comm_eur"], 2) for x in st.stock_legs] == [1.8, 4.5]    # 7 USD × share × 0.9
