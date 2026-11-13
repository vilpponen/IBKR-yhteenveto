"""62N-97: unreadable input stops the calculation with file / section / line / value; amounts are exact Decimals;
no network during the calculation. Synthetic data only."""
import ast
import base64
import json
import socket
import threading
import urllib.error
import urllib.request
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import server
from ibkr_yhteenveto import InputError, Settings, build, load, write_workbook
from ibkr_yhteenveto.__main__ import main
from ibkr_yhteenveto.excel_personal import write_personal_workbook
from ibkr_yhteenveto.num import loads, money, to_jsonable
from ibkr_yhteenveto.personal import PSettings, build_personal
from test_options import HEAD, STK, t

FIXTURE = Path(__file__).parent / "fixtures" / "esimerkki_oy_2025.csv"
GOOD = t(STK, "AAA", "2026-01-05", 100, 10, -1000, -1, 1001, "O")


def bad(proceeds="-1000", date="2026-01-05"):
    return (HEAD + f'Trades,Data,Order,Stocks,EUR,AAA,"{date}, 10:00:00",100,10,10,{proceeds},-1,1001,0,0,O\n').encode()


@pytest.mark.parametrize("value", ["NaN", "inf", "-Infinity", "12,3x", "abc"])
def test_unreadable_number_stops_with_location(value):
    with pytest.raises(InputError) as e:
        load([("raportti.csv", bad(proceeds=f'"{value}"'))])
    msg = str(e.value)
    assert "raportti.csv" in msg and "Trades" in msg and "rivi 10" in msg and value in msg
    assert e.value.file == "raportti.csv" and e.value.section == "Trades" and e.value.line == 10


def test_invalid_date_stops():
    with pytest.raises(InputError, match="päivämäärä"):
        load([("raportti.csv", bad(date="2026-13-45"))])


def test_empty_cells_and_dashes_are_zero_and_amounts_exact():
    st = load([("r.csv", (HEAD + GOOD.replace(",-1,1001,", ",--,1001,")).encode())])
    (leg,) = st.stock_legs
    assert leg["eur"] == Decimal("1000") and isinstance(leg["eur"], Decimal)
    assert sum([Decimal("0.1")] * 3) == Decimal("0.3")          # what floats get wrong (0.30000000000000004)


def test_opening_lot_negative_quantity_or_cost_stops():
    st = load([("r.csv", (HEAD + t(STK, "AAA", "2026-03-05", -10, 12, 120, 0, -100, "C")).encode())])
    for lot in ({"date": "2020-01-01", "qty": -10, "cost_eur": 100}, {"date": "2020-01-01", "qty": 10, "cost_eur": -1},
                {"date": "2020-02-30", "qty": 10, "cost_eur": 100}):
        with pytest.raises(InputError):
            build_personal(st, PSettings(opening_choices={"AAA": {"method": "lots", "lots": [lot]}}))


def test_json_nan_rejected_and_round_trip_exact():
    with pytest.raises(InputError):
        loads('{"x": NaN}')
    x = Decimal("123.4567890123456789012345")
    assert loads(json.dumps(to_jsonable({"v": x})))["v"] == x       # browser round trip keeps every digit


def test_output_rounding_is_half_even():
    assert money(Decimal("10.005")) == Decimal("10.00") and money(Decimal("10.015")) == Decimal("10.02")


def test_cli_reports_input_error(tmp_path, capsys):
    f = tmp_path / "raportti.csv"
    f.write_bytes(bad(proceeds="abc"))
    assert main([str(f), "--personal", "-o", str(tmp_path / "x.xlsx")]) == 3
    assert "VIRHE" in capsys.readouterr().err and not (tmp_path / "x.xlsx").exists()


@pytest.fixture
def live_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_server_returns_readable_error(live_server):
    files = [{"name": "raportti.csv", "data": base64.b64encode(bad(proceeds="abc")).decode()}]
    code, j = _post(live_server, "/api/analyze", {"files": files})
    assert code == 400 and "Virheellinen syöte" in j["error"] and "rivi 10" in j["error"]
    files = [{"name": FIXTURE.name, "data": base64.b64encode(FIXTURE.read_bytes()).decode()}]
    _, a = _post(live_server, "/api/analyze", {"files": files})
    code, j = _post(live_server, "/api/compute", {"mode": "company", "settings": {"wd_open": "-5"}, "statement": a["statement"]})
    assert code == 400 and "negatiivinen" in j["error"]
    code, j = _post(live_server, "/api/compute", {"mode": "company", "settings": {"wd_open": "1,5"}, "statement": a["statement"]})
    assert code == 200


# ---------------------------------------------------------------- local only (no network)
PKG = Path(__file__).resolve().parents[1] / "ibkr_yhteenveto"
NETWORK_MODULES = {"socket", "ssl", "urllib.request", "http.client", "requests", "httpx", "ftplib", "smtplib",
                   "urllib3", "aiohttp", "asyncio"}


def test_calculation_code_imports_no_network_modules():
    for py in PKG.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                     [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for n in names:
                assert not any(n == m or n.startswith(m + ".") for m in NETWORK_MODULES), f"{py.name} imports {n}"


def test_full_calculation_with_network_blocked(monkeypatch):
    def blocked(*a, **k):
        raise AssertionError("network access during calculation")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    st = load([FIXTURE])
    assert write_workbook(build(st, Settings()))[:2] == b"PK"
    assert write_personal_workbook(build_personal(st, PSettings()))[:2] == b"PK"
