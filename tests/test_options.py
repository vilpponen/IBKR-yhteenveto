"""62N-86: exercised option premium goes into the shares' cost (call) or reduces the sale price (put) — synthetic data.

Rows follow IBKR's documented format: the option row closing by exercise has code 'C;Ex' and no realized P/L; the
share row created by the exercise has code 'O;Ex' (call) / 'C;Ex' (put) and IBKR folds the premium into its basis.
"""
from decimal import Decimal
import io

import pytest
from openpyxl import load_workbook

from ibkr_yhteenveto import Settings, build, load
from ibkr_yhteenveto.excel_personal import write_personal_workbook
from ibkr_yhteenveto.personal import PSettings, build_personal, opening_lots
from ibkr_yhteenveto.report import personal as personal_report

HEAD = """Statement,Header,Field Name,Field Value
Statement,Data,Title,Activity Statement
Statement,Data,Period,"January 1, 2026 - December 31, 2026"
Account Information,Header,Field Name,Field Value
Account Information,Data,Name,Esimerkki Henkilo
Account Information,Data,Account,U0000000
Account Information,Data,Customer Type,Individual
Account Information,Data,Base Currency,EUR
Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code
"""
FII = """Financial Instrument Information,Header,Asset Category,Symbol,Description,Conid,Underlying,Listing Exch,Multiplier,Expiry,Delivery Month,Type,Strike,Code
Financial Instrument Information,Data,Equity and Index Options,AAA 17JUN26 100 C,AAA 17JUN26 100 C,1,AAA,CBOE,100,2026-06-17,2026-06,C,100,
Financial Instrument Information,Data,Equity and Index Options,BBB 17JUN26 95 P,BBB 17JUN26 95 P,2,BBB,CBOE,100,2026-06-17,2026-06,P,95,
"""


def csv(rows: str, fii: str = FII) -> bytes:
    return (HEAD + rows + fii).encode()


def t(cls, sym, date, qty, price, proceeds, comm, basis, code, ccy="EUR"):
    return f'Trades,Data,Order,{cls},{ccy},{sym},"{date}, 10:00:00",{qty},{price},{price},{proceeds},{comm},{basis},0,0,{code}\n'


OPT, STK = "Equity and Index Options", "Stocks"
CALL = csv(
    t(OPT, "AAA 17JUN26 100 C", "2026-02-02", 1, 2, -200, -1, 201, "O")        # premium 201 € incl. commission
    + t(OPT, "AAA 17JUN26 100 C", "2026-06-17", -1, 0, 0, 0, -201, "C;Ex")      # exercised
    + t(STK, "AAA", "2026-06-17", 100, 100, -10000, 0, 10201, "O;Ex")           # shares received at strike
    + t(STK, "AAA", "2026-07-01", -100, 130, 13000, 0, -10201, "C"))            # shares sold


def build_p(data: bytes, **kw):
    return build_personal(load([("s.csv", data)]), PSettings(**kw))


def test_exercised_call_premium_in_share_cost():
    pb = build_p(CALL)
    (m,) = pb.matches
    assert (m.cost, m.proceeds, m.result) == (10201, 13000, 2799)    # without the fix: 3000
    assert m.premium == pytest.approx(201)
    (ev,) = pb.option_events
    assert ev["kind"] == "exercise" and ev["target"] == "Osakkeiden hankintamenoon" and ev["premium_eur"] == 201
    assert not pb.preliminary and opening_lots(load([("s.csv", CALL)])) == []


def test_exercised_put_premium_reduces_sale_price():
    data = csv(
        t(STK, "BBB", "2026-01-05", 100, 100, -10000, 0, 10000, "O")
        + t(OPT, "BBB 17JUN26 95 P", "2026-02-02", 1, 1.5, -150, 0, 150, "O")
        + t(OPT, "BBB 17JUN26 95 P", "2026-06-17", -1, 0, 0, 0, -150, "C;Ex")
        + t(STK, "BBB", "2026-06-17", -100, 95, 9500, 0, -10000, "C;Ex"))
    (m,) = build_p(data).matches
    assert (m.proceeds, m.cost, m.result) == (9500, 10150, -650) and m.premium == pytest.approx(150)   # gross; premium in costs


YEAR_START = csv(   # call bought last year: no opening option trade in this statement
    t(OPT, "AAA 17JUN26 100 C", "2026-06-17", -1, 0, 0, 0, -250, "C;Ex")
    + t(STK, "AAA", "2026-06-17", 100, 100, -10000, 0, 10250, "O;Ex")
    + t(STK, "AAA", "2026-07-01", -100, 130, 13000, 0, -10250, "C"))


def test_year_start_option_needs_decision():
    st = load([("s.csv", YEAR_START)])
    (o,) = opening_lots(st)
    assert (o["symbol"], o["kind"], o["qty"], o["underlying"]) == ("AAA 17JUN26 100 C", "option", 1, "AAA")
    assert o["ibkr_suggestion_eur"] == pytest.approx(250)            # IBKR basis − strike cash
    pb = build_p(YEAR_START)
    assert pb.preliminary and pb.matches[0].cost == 10000            # premium unknown until decided
    manual = {"AAA 17JUN26 100 C": {"method": "lots", "lots": [{"date": "2025-11-03", "qty": 1, "cost_eur": 300}]}}
    assert build_p(YEAR_START, opening_choices=manual).matches[0].cost == 10300
    pb = build_p(YEAR_START, opening_choices={"AAA 17JUN26 100 C": {"method": "ibkr"}})
    assert not pb.preliminary and pb.matches[0].cost == pytest.approx(10250)


def test_same_year_assignment_premium_into_sale_price():   # OPT-H4 (decided 13.11.2026; was "not adjusted")
    data = csv(
        t(STK, "AAA", "2026-01-05", 100, 90, -9000, 0, 9000, "O")
        + t(OPT, "AAA 17JUN26 100 C", "2026-02-02", -1, 3, 300, 0, -300, "O")    # written call, premium received
        + t(OPT, "AAA 17JUN26 100 C", "2026-06-17", 1, 0, 0, 0, 300, "C;A")      # assigned
        + t(STK, "AAA", "2026-06-17", -100, 100, 10000, 0, -9000, "C;A"))
    pb = build_p(data, use_presumption=False)
    (m,) = pb.matches
    assert (m.proceeds, m.cost, m.result) == (10300, 9000, 1300)       # call: premium → sale price of shares delivered
    ev = pb.option_events[0]
    assert ev["kind"] == "assignment" and "OPT-H4" in ev["target"]


def test_usd_premium_converted_with_class_ratio():
    data = (HEAD
            + t(OPT, "AAA 17JUN26 100 C", "2026-02-02", 1, 2, -200, -2, 202, "O", ccy="USD")
            + "Trades,Total,,Equity and Index Options,USD,,,,,,-200,-2,202,0,0,\n"
            + "Trades,Total,,Equity and Index Options,EUR,,,,,,-180,-1.8,181.8,0,0,\n" + FII).encode()
    (o,) = load([("s.csv", data)]).option_trades
    assert o["eur"] == pytest.approx(Decimal("181.8"))                     # paid = |−200 + (−2)| × 0.9 and (o["underlying"], o["right"], o["mult"]) == ("AAA", "C", 100)


def test_csv_buy_commission_increases_cost():
    st = load([("s.csv", csv(t(STK, "AAA", "2026-01-05", 100, 100, -10000, -25, 10025, "O")
                             + t(STK, "AAA", "2026-02-05", -100, 110, 11000, -25, -10025, "C")))])
    assert [x["eur"] for x in st.stock_legs] == [10025, 10975]      # cost incl. commission, sale price net of it


def test_non_fifo_code_warns():
    st = load([("s.csv", csv(t(STK, "AAA", "2026-01-05", 100, 90, -9000, 0, 9000, "O")
                             + t(STK, "AAA", "2026-02-05", -50, 95, 4750, 0, -4500, "C;LI")))])
    assert any("FIFO" in w and "LI" in w for w in st.warnings)


def test_report_workbook_and_company_mode():
    res, xlsx = personal_report(load([("s.csv", CALL)]), PSettings())
    assert "Toteutetut optiot" in res["tabs"]
    wb = load_workbook(io.BytesIO(xlsx))
    lu = wb["Luovutukset (FIFO)"]
    assert any(lu.cell(r, 10).value == 201 for r in range(1, lu.max_row + 1))
    de = wb["Johdannaiset"]
    assert any("TOTEUTETUT OPTIOT" in str(de.cell(r, 1).value) for r in range(1, de.max_row + 1))
    wb2 = load_workbook(io.BytesIO(write_personal_workbook(build_p(YEAR_START))))
    assert "Vuoden alun erät" in wb2.sheetnames
    build(load([("s.csv", CALL)]), Settings())            # company mode unaffected by option rows
