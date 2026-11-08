"""62N-88: year-start positions — history from earlier statements, user choices, preliminary flag (synthetic data)."""
import io

import pytest
from openpyxl import load_workbook

from ibkr_yhteenveto import load
from ibkr_yhteenveto.excel_personal import write_personal_workbook
from ibkr_yhteenveto.model import Statement
from ibkr_yhteenveto.personal import PSettings, build_personal, opening_lots
from ibkr_yhteenveto.report import personal as personal_report, recognised


def statement(year: int, trades: list[tuple], positions: list[tuple] = (), ru: list[tuple] = (),
              account: str = "U0000000") -> bytes:
    """Minimal IBKR Activity Statement CSV (EUR base, EUR stocks). trades: (date, symbol, qty, price)."""
    rows = [
        "Statement,Header,Field Name,Field Value",
        "Statement,Data,Title,Activity Statement",
        f'Statement,Data,Period,"January 1, {year} - December 31, {year}"',
        "Account Information,Header,Field Name,Field Value",
        "Account Information,Data,Name,Esimerkki Henkilo",
        f"Account Information,Data,Account,{account}",
        "Account Information,Data,Customer Type,Individual",
        "Account Information,Data,Base Currency,EUR",
        "Realized & Unrealized Performance Summary,Header,Asset Category,Symbol,Cost Adj.,Realized S/T Profit,"
        "Realized S/T Loss,Realized L/T Profit,Realized L/T Loss,Realized Total,Unrealized S/T Profit,"
        "Unrealized S/T Loss,Unrealized L/T Profit,Unrealized L/T Loss,Unrealized Total,Total,Code",
    ]
    for sym, realized in ru:
        p, l = (realized, 0) if realized >= 0 else (0, realized)
        rows.append(f"Realized & Unrealized Performance Summary,Data,Stocks,{sym},0,{p},{l},0,0,{realized},0,0,0,0,0,{realized},")
    rows.append("Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,"
                "Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code")
    for d, sym, q, px in trades:
        rows.append(f'Trades,Data,Order,Stocks,EUR,{sym},"{d}, 10:00:00",{q},{px},{px},{-q * px},0,{q * px},0,0,O')
    rows.append("Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,"
                "Cost Basis,Close Price,Value,Unrealized P/L,Code")
    for sym, q in positions:
        rows.append(f"Open Positions,Data,Summary,Stocks,EUR,{sym},{q},1,100,{q * 100},100,{q * 100},0,")
    return ("\n".join(rows) + "\n").encode()


Y1 = statement(2025, [("2025-03-03", "AAA", 100, 100)], positions=[("AAA", 100)])           # buy 100 @ 100
Y2 = statement(2026, [("2026-02-02", "AAA", -100, 150)], ru=[("AAA", 5000)])                 # sell 100 @ 150


def test_history_from_previous_year_statement():
    st = load([("y2026.csv", Y2), ("y2025.csv", Y1)])
    assert st.period_end == "2026-12-31" and st.history_periods == ["2025-01-01 – 2025-12-31"]
    assert opening_lots(st) == []                         # nothing left to ask
    pb = build_personal(st, PSettings())
    (m,) = pb.matches
    assert (m.buy_date, m.cost, m.proceeds, m.method) == ("2025-03-03", 10000, 15000, "history")
    assert not pb.preliminary and pb.v["sec_net"] == pytest.approx(5000)


def test_without_history_lot_is_unresolved_and_preliminary():
    st = load([("y2026.csv", Y2)])
    (o,) = opening_lots(st)
    assert (o["symbol"], o["opening_qty"], o["qty"]) == ("AAA", 100, 100)
    assert o["ibkr_suggestion_eur"] == pytest.approx(10000)   # backed out of IBKR's realized P/L
    pb = build_personal(st, PSettings())
    assert pb.preliminary and pb.matches[0].method == "unresolved"
    assert pb.warnings[0].startswith("KESKENERÄINEN")
    pb2 = build_personal(st, PSettings(opening_choices={"AAA": {"method": "ibkr"}}))
    assert not pb2.preliminary and pb2.v["sec_net"] == pytest.approx(5000)


def test_manual_and_olettama_choices():
    st = load([("y2026.csv", Y2)])
    manual = {"AAA": {"method": "lots", "lots": [{"date": "2024-05-02", "qty": 100, "cost_eur": 9000}]}}
    m = build_personal(st, PSettings(opening_choices=manual)).matches[0]
    assert (m.buy_date, m.cost, m.result, m.method) == ("2024-05-02", 9000, 6000, "manual")
    old = {"AAA": {"method": "lots", "lots": [{"date": "2014-01-15", "qty": 100, "olettama": True}]}}
    m = build_personal(st, PSettings(opening_choices=old)).matches[0]
    assert m.cost == pytest.approx(0.4 * 15000) and m.method == "olettama" and m.source.endswith("40 %")
    new = {"AAA": {"method": "lots", "lots": [{"date": "2020-01-15", "qty": 100, "olettama": True}]}}
    assert build_personal(st, PSettings(opening_choices=new)).matches[0].cost == pytest.approx(0.2 * 15000)


def test_partial_lots_leave_rest_unresolved():
    st = load([("y2026.csv", Y2)])
    ch = {"AAA": {"method": "lots", "lots": [{"date": "2024-05-02", "qty": 60, "cost_eur": 5400},
                                             {"date": "2024-09-02", "qty": 0, "cost_eur": None}]}}
    pb = build_personal(st, PSettings(opening_choices=ch))
    assert [(x.qty, x.method) for x in pb.matches] == [(60, "manual"), (40, "unresolved")]
    assert pb.preliminary


def test_short_opened_last_year():
    st = load([("y2026.csv", statement(2026, [("2026-03-02", "SHO", 100, 100)], ru=[("SHO", 2000)]))])
    (o,) = opening_lots(st)
    assert o["short"] and o["opening_qty"] == -100
    ch = {"SHO": {"method": "lots", "lots": [{"date": "2025-11-03", "qty": 100, "cost_eur": 12000}]}}
    (m,) = build_personal(st, PSettings(opening_choices=ch)).matches
    assert m.short and (m.proceeds, m.cost, m.result) == (12000, 10000, 2000)


def test_end_lots_export_feeds_next_year():
    y1 = build_personal(load([("y2025.csv", Y1)]), PSettings())
    assert y1.end_lots == [{"symbol": "AAA", "date": "2025-03-03", "qty": 100, "cost_eur": 10000,
                            "olettama": False, "method": "fifo"}]
    ch = {"AAA": {"method": "lots", "lots": [{k: y1.end_lots[0][k] for k in ("date", "qty", "cost_eur")}]}}
    m = build_personal(load([("y2026.csv", Y2)]), PSettings(opening_choices=ch)).matches[0]
    assert m.cost == 10000 and m.method == "manual"


def test_gap_and_other_account_warnings():
    y24 = statement(2024, [("2024-03-01", "AAA", 100, 100)], positions=[("AAA", 100)])
    st = load([("y2026.csv", Y2), ("y2024.csv", y24)])
    assert any("aukko" in w for w in st.warnings)
    other = statement(2025, [("2025-03-03", "AAA", 100, 100)], positions=[("AAA", 100)], account="UTOINEN")
    st = load([("y2026.csv", Y2), ("other.csv", other)])
    assert st.history_legs == [] and any("Eri tilin" in w for w in st.warnings)


def test_json_roundtrip_report_and_workbook():
    st = load([("y2026.csv", Y2), ("y2025.csv", Y1)])
    st2 = Statement.from_dict(st.to_dict())
    assert st2.history_legs == st.history_legs and st2.history_periods == st.history_periods
    assert recognised(load([("y2026.csv", Y2)]))["opening_lots"][0]["symbol"] == "AAA"
    res, xlsx = personal_report(load([("y2026.csv", Y2)]), PSettings())
    assert res["preliminary"] and "Vuoden alun erät" in res["tabs"]
    wb = load_workbook(io.BytesIO(xlsx))
    assert "Vuoden alun erät" in wb.sheetnames
    lu = wb["Luovutukset (FIFO)"]
    assert any(str(lu.cell(r, 8).value).startswith("RATKAISEMATON") for r in range(1, lu.max_row + 1))
    res, _ = personal_report(st, PSettings())
    assert not res["preliminary"] and res["end_lots"]["lots"] == []
