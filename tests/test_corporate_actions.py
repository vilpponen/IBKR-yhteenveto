"""62N-90: corporate actions in FIFO — split, reverse split with cash for fractions, stock dividend, unknown actions
(synthetic data; IBKR Corporate Actions columns per its documentation; the symbol starts the description)."""
import io

import pytest
from openpyxl import load_workbook

from ibkr_yhteenveto import load
from ibkr_yhteenveto.excel_personal import write_personal_workbook
from ibkr_yhteenveto.personal import PSettings, build_personal, opening_lots
from ibkr_yhteenveto.report import personal as personal_report
from test_options import STK, csv, t

CA_HDR = ("Corporate Actions,Header,Asset Category,Currency,Report Date,Date/Time,Description,Quantity,Proceeds,"
          "Value,Realized P/L,Code\n")


def ca(date, desc, qty, proceeds=0):
    return f'Corporate Actions,Data,Stocks,EUR,{date},"{date}, 20:25:00","{desc}",{qty},{proceeds},0,0,\n'


def build(data, **kw):
    return build_personal(load([("s.csv", data)]), PSettings(use_presumption=False, **kw))


def test_forward_split_keeps_cost_and_purchase_date():
    data = csv(t(STK, "AAA", "2026-01-05", 100, 40, -4000, 0, 4000, "O")
               + t(STK, "AAA", "2026-08-03", -400, 15, 6000, 0, -4000, "C")
               + CA_HDR + ca("2026-06-01", "AAA(US0000000001) Split 4 for 1 (AAA, AAA INC, US0000000001)", 300))
    pb = build(data)
    (m,) = pb.matches
    assert (m.qty, m.buy_date, m.cost, m.proceeds, m.result) == (400, "2026-01-05", 4000, 6000, 2000)
    assert pb.ca_events[0]["factor"] == 4 and not pb.preliminary
    assert opening_lots(load([("s.csv", data)])) == []          # the split is not mistaken for a year-start lot


def test_reverse_split_new_ticker_and_cash_for_fraction():
    data = csv(t(STK, "BBB", "2026-01-05", 1005, 1, -1005, 0, 1005, "O")
               + t(STK, "BBB", "2026-09-01", -100, 12, 1200, 0, -1000, "C")
               + CA_HDR
               + ca("2026-06-01", "BBB.OLD(US0000000002) Split 1 for 10 (BBB.OLD, BBB INC, US0000000002)", -1005)
               + ca("2026-06-01", "BBB(US0000000003) Split 1 for 10 (BBB, BBB INC, US0000000003)", 100, 5))
    pb = build(data)
    frac, sale = pb.matches
    assert frac.qty == pytest.approx(0.5) and frac.proceeds == pytest.approx(5) and "murto-osa" in frac.source
    assert frac.cost == pytest.approx(5)                     # 1005 € × 0.5 / 100.5
    assert (sale.qty, sale.cost, sale.result) == (pytest.approx(100), pytest.approx(1000), pytest.approx(200))
    assert sale.buy_date == "2026-01-05"


def test_stock_dividend_spreads_cost():
    data = csv(t(STK, "CCC", "2026-01-05", 100, 10, -1000, 0, 1000, "O")
               + t(STK, "CCC", "2026-09-01", -110, 11, 1210, 0, -1000, "C")
               + CA_HDR + ca("2026-05-01", "CCC(US0000000004) Stock Dividend US0000000004 1 for 10 (CCC, CCC OYJ, US0000000004)", 10))
    (m,) = build(data).matches
    assert (m.qty, m.cost, m.result) == (pytest.approx(110), pytest.approx(1000), pytest.approx(210))


def test_unknown_action_stops_fifo_and_flags():
    data = csv(t(STK, "DDD", "2026-01-05", 100, 10, -1000, 0, 1000, "O")
               + t(STK, "DDD", "2026-09-01", -100, 12, 1200, 0, -1000, "C")
               + CA_HDR + ca("2026-05-01", "DDD(US0000000005) Spinoff 1 for 5 (EEE, EEE INC, US0000000006)", 20))
    pb = build(data)
    assert pb.matches == [] and pb.blocked == ["DDD"] and pb.preliminary
    assert any("tuntematon yritystapahtuma" in w for w in pb.warnings)


def test_position_removed_stops_fifo():
    data = csv(t(STK, "FFF", "2026-01-05", 100, 10, -1000, 0, 1000, "O")
               + CA_HDR + ca("2026-05-01", "FFF(US0000000007) Split (FFF, FFF INC, US0000000007)", -100))
    pb = build(data)
    assert pb.blocked == ["FFF"] and pb.preliminary


def test_workbook_and_report_list_actions():
    data = csv(t(STK, "AAA", "2026-01-05", 100, 40, -4000, 0, 4000, "O")
               + CA_HDR + ca("2026-06-01", "AAA(US0000000001) Split 4 for 1 (AAA, AAA INC, US0000000001)", 300)
               + "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,"
                 "Cost Basis,Close Price,Value,Unrealized P/L,Code\n"
               + "Open Positions,Data,Summary,Stocks,EUR,AAA,400,1,10,4000,11,4400,400,\n")
    st = load([("s.csv", data)])
    res, xlsx = personal_report(st, PSettings())
    assert "Yritystapahtumat" in res["tabs"]
    ws = load_workbook(io.BytesIO(xlsx))["Arvopaperit yhteenveto"]
    assert any("YRITYSTAPAHTUMAT" in str(ws.cell(r, 1).value) for r in range(1, ws.max_row + 1))
    pb = build_personal(st, PSettings())
    assert pb.end_lots[0]["qty"] == pytest.approx(400) and pb.end_lots[0]["cost_eur"] == pytest.approx(4000)
