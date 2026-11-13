"""62N-100: company — written options still open at year-end (OPT-Y8, proposal). Synthetic data."""
import io

import pytest
from openpyxl import load_workbook

from ibkr_yhteenveto import Settings, build, load
from ibkr_yhteenveto.__main__ import main
from ibkr_yhteenveto.excel import write_workbook
from ibkr_yhteenveto.report import company, recognised
from test_options import OPT, STK, csv, t
from test_written_options import POS, RU

C = "AAA 17JUN26 100 C"


def ru(sym, cls, unrealized):
    return (f"Realized & Unrealized Performance Summary,Data,{cls},{sym},0,0,0,0,0,0,"
            f"0,{unrealized},0,0,{unrealized},{unrealized},\n")


OPEN = csv(t(OPT, C, "2026-03-02", -1, 3, 300, 0, -300, "O")
           + POS + f"Open Positions,Data,Summary,{OPT},EUR,{C},-1,100,3,-300,5,-500,-200,\n"
           + RU + ru(C, OPT, -200))
st = load([("s.csv", OPEN)])


def b(**kw):
    return build(st, Settings(**kw))


def test_open_written_option_listed_with_book_loss():
    (o,) = recognised(st)["written_open"]
    assert (o["symbol"], o["contracts"], o["loss_eur"]) == (C, 1, 200)


def test_no_choice_adds_back_and_is_preliminary():
    x = b()
    assert x.preliminary and x.v["evl_add_wd_wopt"] == 200 and x.v["evl_add_wd_other"] == 0
    assert any("ilman valittua käsittelyä" in w for w in x.warnings)


def test_three_choices():
    add, ded = b(wopt_y8={C: "addback"}), b(wopt_y8={C: "deduct"})
    assert not add.preliminary and not ded.preliminary
    assert add.v["taxable"] - ded.v["taxable"] == pytest.approx(200)
    assert any("ei ole lähdettä" in w for w in ded.warnings)
    ignored = b(wopt_y8={C: "fair_value"})                       # needs KPL 5:2a fair-value accounting
    assert ignored.preliminary and ignored.v["evl_add_wd_wopt"] == 200
    fv = b(wopt_y8={C: "fair_value"}, fair_value_5_2a=True)
    assert not fv.preliminary and fv.v["taxable"] == pytest.approx(ded.v["taxable"])


def test_next_year_deducts_carry_separately_from_shares():
    nxt = load([("s.csv", csv(t(STK, "BBB", "2026-01-05", 1, 100, -100, 0, 100, "O")))])
    for cat, diff in (("muu omaisuus", 0.0), ("rahoitusomaisuus", -200.0)):
        base = build(nxt, Settings(share_category=cat, opening_writedowns=200))
        carry = build(nxt, Settings(share_category=cat, opening_writedowns=200, wopt_loss_carry=200))
        assert carry.v["evl_ded_wd_wopt"] == -200
        assert carry.v["taxable"] - base.v["taxable"] == pytest.approx(diff)   # shares no longer absorb the carry


def test_no_written_options_no_step_and_no_change():
    plain = load([("s.csv", csv(t(STK, "BBB", "2026-01-05", 1, 100, -100, 0, 100, "O")
                                + RU + ru("BBB", STK, -10)))])
    assert recognised(plain)["written_open"] == []
    x = build(plain, Settings())
    assert not x.preliminary and x.v["evl_add_wd_wopt"] == 0 and x.v["evl_ded_wd_wopt"] == 0


def test_workbook_report_and_cli(tmp_path):
    res, xlsx = company(st, Settings(wopt_y8={C: "addback"}, wopt_loss_carry=0))
    assert "Asetetut optiot (OPT-Y8)" in res["tabs"] and not res["preliminary"]
    wb = load_workbook(io.BytesIO(write_workbook(b(wopt_y8={C: "deduct"}))))
    rp = wb["Realisoitu P_L"]
    assert any(str(rp.cell(r, 10).value).startswith("Asetettu optio: vähennetään") for r in range(1, rp.max_row + 1))
    ev = wb["EVL-täsmäytys"]
    assert any(str(ev.cell(r, 1).value).startswith("+ OPT-Y8") for r in range(1, ev.max_row + 1))
    f = tmp_path / "s.csv"
    f.write_bytes(OPEN)
    assert main([str(f), "-o", str(tmp_path / "a.xlsx")]) == 2                     # no choice → preliminary
    assert main([str(f), "-o", str(tmp_path / "b.xlsx"), "--wopt-y8", "addback"]) == 0
