"""Public tests — synthetic data only (tests/fixtures/esimerkki_oy_2025.csv is made up)."""
from pathlib import Path

import pytest

from ibkr_yhteenveto import Settings, build, load, write_workbook
from ibkr_yhteenveto.books import classify_transfers
from ibkr_yhteenveto.excel_personal import write_personal_workbook
from ibkr_yhteenveto.model import CashLine, Position, Statement
from ibkr_yhteenveto.parse_csv import parse_csv
from ibkr_yhteenveto.personal import PSettings, build_personal, fifo

FIX = Path(__file__).parent / "fixtures" / "esimerkki_oy_2025.csv"


@pytest.fixture(scope="module")
def stmt():
    return load([FIX])


def test_csv_parsing(stmt):
    assert (stmt.name, stmt.account, stmt.customer_type) == ("Esimerkki Oy", "U0000000", "Corporate")
    assert (stmt.period_start, stmt.period_end) == ("2025-01-01", "2025-12-31")
    assert stmt.nav_end == 105625 and stmt.change_in_nav["Mark-to-Market"] == 5700
    assert stmt.commissions_eur == -200
    assert stmt.fees_total_eur == -10          # 'Subtitle' column handled
    assert stmt.dividends_total_eur == 300 and stmt.withholding_total_eur == -81


def test_company_ties_to_nav(stmt):
    b = build(stmt, Settings())
    v = b.v
    assert v["E"] == pytest.approx(5625) and v["N"] == pytest.approx(125) and v["T"] == pytest.approx(5500)
    assert v["F"] == pytest.approx(0, abs=0.01)                 # no FX in an all-EUR account
    assert v["book_result"] == pytest.approx(5625)
    assert v["bs_equity"] == pytest.approx(v["nav_end"])
    assert all(abs(o - i) < 0.01 for _, o, i, _ in b.checks)    # every IBKR cross-check passes


def test_company_evl(stmt):
    v = build(stmt, Settings()).v
    assert v["evl_add_wht"] == pytest.approx(81)
    assert v["evl_add_wd_shares"] == pytest.approx(500)        # muu omaisuus: write-down added back
    assert v["taxable"] == pytest.approx(6206)
    assert v["tax_credit"] == pytest.approx(-45)                # DK 15 % treaty cap, 27 % withheld
    v2 = build(stmt, Settings(share_category="rahoitusomaisuus")).v
    assert v2["taxable"] == pytest.approx(5706)


def test_cancelled_withdrawal(stmt):
    kinds = classify_transfers(stmt.deposits)
    assert kinds == ["Talletus", "Peruttu", "Peruttu", "Nosto"]
    v = build(stmt, Settings()).v
    assert (v["deposits_in"], v["withdrawals"], v["net_deposits"]) == (120000, -20000, 100000)


def test_workbooks_build(stmt):
    assert write_workbook(build(stmt, Settings()))[:2] == b"PK"
    assert write_personal_workbook(build_personal(stmt, PSettings()))[:2] == b"PK"


def test_fifo_per_lot():
    st = Statement(base_currency="EUR")
    st.stock_legs = [
        {"date": "2025-01-10", "symbol": "XYZ", "qty": 100, "ccy": "USD", "eur": 10000.0, "exact": True},
        {"date": "2025-02-10", "symbol": "XYZ", "qty": 50, "ccy": "USD", "eur": 6000.0, "exact": True},
        {"date": "2025-03-10", "symbol": "XYZ", "qty": -120, "ccy": "USD", "eur": 15600.0, "exact": True},
    ]
    st.positions = [Position("Stocks", "USD", "XYZ", 30, 1, 0, 0, 0, 0, 0)]
    m = fifo(st, [])
    assert [(x.buy_date, x.qty) for x in m] == [("2025-01-10", 100), ("2025-02-10", 20)]
    assert [round(x.proceeds, 2) for x in m] == [13000.0, 2600.0]
    assert [round(x.result, 2) for x in m] == [3000.0, 200.0]


def test_fifo_short_cover():
    st = Statement(base_currency="EUR")
    st.stock_legs = [
        {"date": "2025-05-01", "symbol": "SHO", "qty": -10, "ccy": "EUR", "eur": 1000.0, "exact": True},
        {"date": "2025-05-20", "symbol": "SHO", "qty": 10, "ccy": "EUR", "eur": 800.0, "exact": True},
    ]
    (m,) = fifo(st, [])
    assert m.short and m.proceeds == 1000.0 and m.cost == 800.0 and m.result == 200.0


def test_personal_small_disposal_exemption():
    st = Statement(base_currency="EUR")
    st.stock_legs = [
        {"date": "2025-01-10", "symbol": "S", "qty": 10, "ccy": "EUR", "eur": 500.0, "exact": True},
        {"date": "2025-06-10", "symbol": "S", "qty": -10, "ccy": "EUR", "eur": 900.0, "exact": True},
    ]
    v = build_personal(st, PSettings()).v
    assert v["sec_proceeds"] == 900 and v["small_exempt"] == 1.0 and v["disp_net"] == 0


def test_personal_capital_income_tax():
    st = Statement(base_currency="EUR")
    st.stock_legs = [
        {"date": "2025-01-10", "symbol": "S", "qty": 100, "ccy": "EUR", "eur": 50000.0, "exact": True},
        {"date": "2025-06-10", "symbol": "S", "qty": -100, "ccy": "EUR", "eur": 90000.0, "exact": True},
    ]
    st.dividends = [CashLine("2025-05-01", "EUR", "ABC(FI0000000000) Cash Dividend (Ordinary Dividend)", 1000, 1000)]
    v = build_personal(st, PSettings()).v
    assert v["capital_income"] == pytest.approx(40000 + 850)            # 85 % of listed dividends
    assert v["tax_net"] == pytest.approx(30000 * 0.30 + 10850 * 0.34)
