"""The web server keeps nothing: no sessions, no files on disk. Synthetic fixture only."""
from __future__ import annotations

import base64
import builtins
import io
import json
import os
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import server
from ibkr_yhteenveto import load, report
from ibkr_yhteenveto.books import Settings
from ibkr_yhteenveto.model import Statement

FIXTURE = Path(__file__).parent / "fixtures" / "esimerkki_oy_2025.csv"


def test_in_memory_load_matches_path_load():
    a = load([FIXTURE])
    b = load([(FIXTURE.name, FIXTURE.read_bytes())])
    assert a.to_dict() == b.to_dict()


def test_statement_json_round_trip_gives_same_result():
    st = load([FIXTURE])
    back = Statement.from_dict(json.loads(json.dumps(st.to_dict())))
    assert back.to_dict() == st.to_dict()
    r1, _ = report.company(st, Settings())
    r2, _ = report.company(back, Settings())
    assert r1 == r2


@pytest.fixture
def live_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_server_writes_nothing_and_keeps_no_state(live_server, monkeypatch, tmp_path):
    writes = []
    real_open, real_os_open = builtins.open, os.open

    def guard_open(file, mode="r", *a, **k):
        if any(c in mode for c in "wax+"):
            writes.append(str(file))
        return real_open(file, mode, *a, **k)

    def guard_os_open(path, flags, *a, **k):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
            writes.append(str(path))
        return real_os_open(path, flags, *a, **k)

    monkeypatch.setattr(builtins, "open", guard_open)
    monkeypatch.setattr(io, "open", guard_open)
    monkeypatch.setattr(os, "open", guard_os_open)

    files = [{"name": FIXTURE.name, "data": base64.b64encode(FIXTURE.read_bytes()).decode()}]
    a = _post(live_server, "/api/analyze", {"files": files})
    assert a["recognised"]["account"] and a["statement"]["nav"]
    c = _post(live_server, "/api/compute", {"mode": "company", "settings": {}, "statement": a["statement"]})
    xlsx = base64.b64decode(c["xlsx"])
    assert xlsx[:2] == b"PK" and c["filename"].endswith(".xlsx")

    assert writes == [], f"server wrote files: {writes}"
    # no module-level storage left in the server
    assert not any(isinstance(v, dict) and v and k.isupper() and k not in ("CONTENT_TYPES",)
                   for k, v in vars(server).items())
    assert not hasattr(server, "SESSIONS")


def test_removed_stateful_endpoints(live_server):
    for path in ("/api/upload", "/api/remove", "/api/clear"):
        with pytest.raises(urllib.error.HTTPError) as e:
            _post(live_server, path, {})
        assert e.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(live_server + "/api/xlsx?sid=x")
    assert e.value.code == 404
