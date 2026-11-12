"""62N-92: crypto assets — FIFO per coin, own OmaVero section, olettama, combined 1 000 € limit (synthetic data)."""
import io

import pytest
from openpyxl import load_workbook

from ibkr_yhteenveto import Settings, build, load
from ibkr_yhteenveto.excel_personal import write_personal_workbook
from ibkr_yhteenveto.personal import PSettings, build_personal, omavero_fields, opening_lots
from test_options import HEAD, STK, t

CR = "Crypto"
RU = ("Realized & Unrealized Performance Summary,Header,Asset Category,Symbol,Cost Adj.,Realized S/T Profit,"
      "Realized S/T Loss,Realized L/T Profit,Realized L/T Loss,Realized Total,Unrealized S/T Profit,"
      "Unrealized S/T Loss,Unrealized L/T Profit,Unrealized L/T Loss,Unrealized Total,Total,Code\n")
BTC = (HEAD + t(CR, "BTC.EUR-PAXOS", "2026-02-02", 0.1, 30000, -3000, -3, 3003, "O")
       + t(CR, "BTC.EUR-PAXOS", "2026-05-04", -0.1, 50000, 5000, -5, -3003, "C")
       + RU + "Realized & Unrealized Performance Summary,Data,Crypto,BTC.EUR-PAXOS,0,1992,0,0,0,1992,0,0,0,0,0,1992,\n")


def build_p(data, **kw):
    return build_personal(load([("s.csv", data.encode() if isinstance(data, str) else data)]), PSettings(**kw))


def test_crypto_fifo_and_omavero_section():
    pb = build_p(BTC)
    (m,) = pb.crypto_matches
    assert (m.proceeds, m.cost, m.result) == (pytest.approx(5000), pytest.approx(3008), pytest.approx(1992))
    assert pb.matches == [] and pb.v["capital_income"] == pytest.approx(1992)
    assert not any("Tuntemattomat omaisuusluokat" in w for w in pb.warnings)
    f = {k: v for sec, k, v, _ in omavero_fields(pb) if sec == "Virtuaalivaluutat (OmaVero)"}
    assert f["Kryptovarat — luovutushinnat yhteensä"] == pytest.approx(5000)
    assert f["Kryptovarat — luovutusvoitot"] == pytest.approx(1992)


def test_crypto_olettama_and_usd_conversion():
    data = (HEAD + t(CR, "ETH.USD-PAXOS", "2026-02-02", 1, 100, -100, 0, 100, "O", ccy="USD")
            + t(CR, "ETH.USD-PAXOS", "2026-05-04", -1, 2000, 2000, 0, -100, "C", ccy="USD")
            + "Trades,Total,,Crypto,USD,,,,,,1900,-10,0,1900,0,\nTrades,Total,,Crypto,EUR,,,,,,1710,-9,0,1710,0,\n")
    (m,) = build_p(data).crypto_matches
    assert m.proceeds == pytest.approx(1800) and m.presumption_used and m.result == pytest.approx(1440)


def test_small_disposal_limit_counts_securities_and_crypto_together():
    data = (HEAD + t(STK, "AAA", "2026-01-05", 1, 100, -100, 0, 100, "O") + t(STK, "AAA", "2026-03-05", -1, 600, 600, 0, -100, "C")
            + t(CR, "BTC.EUR-PAXOS", "2026-02-02", 0.01, 10000, -100, 0, 100, "O")
            + t(CR, "BTC.EUR-PAXOS", "2026-05-04", -0.01, 30000, 300, 0, -100, "C"))
    pb = build_p(data, use_presumption=False)
    assert pb.v["small_exempt"] == 1.0 and pb.v["capital_income"] == 0          # 600 + 300 ≤ 1 000 €
    more = data.replace(t(CR, "BTC.EUR-PAXOS", "2026-05-04", -0.01, 30000, 300, 0, -100, "C"),
                        t(CR, "BTC.EUR-PAXOS", "2026-05-04", -0.01, 50000, 500, 0, -100, "C"))
    pb = build_p(more, use_presumption=False)
    assert pb.v["small_exempt"] == 0.0 and pb.v["capital_income"] == pytest.approx(500 + 400)


def test_crypto_bought_last_year_needs_decision():
    data = HEAD + t(CR, "BTC.EUR-PAXOS", "2026-05-04", -0.1, 50000, 5000, 0, -3000, "C")
    st = load([("s.csv", data.encode())])
    (o,) = [x for x in opening_lots(st) if x["kind"] == "crypto"]
    assert o["symbol"] == "BTC.EUR-PAXOS" and o["opening_qty"] == pytest.approx(0.1)
    assert build_personal(st, PSettings()).preliminary
    ch = {"BTC.EUR-PAXOS": {"method": "lots", "lots": [{"date": "2014-01-02", "qty": 0.1, "olettama": True}]}}
    m = build_personal(st, PSettings(opening_choices=ch)).crypto_matches[0]
    assert m.deduction == pytest.approx(2000)                                   # 40 %: held ≥ 10 years


def test_workbook_sheet_and_company_mode():
    pb = build_p(BTC)
    wb = load_workbook(io.BytesIO(write_personal_workbook(pb)))
    assert "Kryptovarat (FIFO)" in wb.sheetnames
    po = wb["Pääomatulo & vero"]
    assert any(po.cell(r, 1).value == "Kryptovarojen voitot" for r in range(1, po.max_row + 1))
    build(load([("s.csv", BTC.encode())]), Settings())                          # company mode: muu omaisuus via R&U
