"""Local web app for IBKR-yhteenveto — Python standard library only (no web framework).

    python server.py            # http://127.0.0.1:8501  (opens the browser)
    python server.py --port 9000 --no-browser

Binds to 127.0.0.1 only. Stateless: the server stores nothing — no sessions, no files, no temp files.
Each request carries what it needs (the statements, or the parsed statement the browser holds), is processed
in memory and forgotten when the response is sent. The browser keeps the files, the parsed statement and the
workbook; reloading the page discards them.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import threading
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from ibkr_yhteenveto import __version__, load
from ibkr_yhteenveto.books import Settings
from ibkr_yhteenveto.model import Statement
from ibkr_yhteenveto.personal import PSettings
from ibkr_yhteenveto import report

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_BODY = 150 * 1024 * 1024   # one request: all statements base64-encoded
DEBUG = False                   # --debug: print tracebacks (may contain statement details) to the console
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}


def decode_files(items) -> list[tuple[str, bytes]]:
    """[{name, data(base64)}] from the browser -> [(name, bytes)], kept in memory only."""
    out = []
    for it in items or []:
        name = Path(str(it.get("name", "statement"))).name
        if Path(name).suffix.lower() not in (".pdf", ".csv"):
            raise ValueError(f"{name}: vain IBKR:n PDF- tai CSV-raportit")
        out.append((name, base64.b64decode(it.get("data", ""), validate=True)))
    if not out:
        raise ValueError("Ei tiedostoja")
    return out


def f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


class Handler(BaseHTTPRequestHandler):
    server_version = "IBKR-yhteenveto"

    def log_message(self, fmt, *args):  # quieter console: one line per API call
        if args and "/api/" in str(args[0]):   # args[0] is an HTTPStatus for send_error()
            super().log_message(fmt, *args)

    # ---------------------------------------------------------------- helpers
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, val in (extra or {}).items():
            self.send_header(k, val)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("Tiedostot ovat liian suuria")
        return self.rfile.read(n)

    def _same_origin(self) -> bool:
        """Block cross-site requests from other web pages to this local server."""
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        return origin is None or origin.endswith("//" + host)

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            return self._static("index.html")
        if url.path.startswith("/static/"):
            return self._static(url.path[len("/static/"):])
        self._json({"error": "not found"}, 404)

    def _static(self, rel: str):
        p = (STATIC / rel).resolve()
        if STATIC not in p.parents or not p.is_file():
            return self._json({"error": "not found"}, 404)
        body = p.read_bytes()
        if p.name == "index.html":   # the page shows the version it was served with
            body = body.replace(b"__APP_VERSION__", __version__.encode())
        self._send(200, body, CONTENT_TYPES.get(p.suffix, "application/octet-stream"))

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        if not self._same_origin():
            return self._json({"error": "forbidden"}, 403)
        url = urlparse(self.path)
        try:
            req = json.loads(self._body() or b"{}")
            if url.path == "/api/analyze":     # statements in -> recognised summary + parsed statement out
                st = load(decode_files(req.get("files")))
                return self._json({"recognised": report.recognised(st), "statement": st.to_dict()})
            if url.path == "/api/compute":     # parsed statement + settings in -> result + workbook out
                st = Statement.from_dict(req.get("statement") or {})
                o = req.get("settings", {})
                if req.get("mode") == "personal":
                    res, xlsx = report.personal(st, PSettings(
                        name=o.get("name", ""), loss_carryforward=f(o.get("loss_cf")),
                        include_fx=bool(o.get("include_fx")), credit_interest_wht=bool(o.get("int_credit")),
                        opening_choices=o.get("opening_choices") if isinstance(o.get("opening_choices"), dict) else {}))
                else:
                    ftt = f(o.get("ftt"))
                    res, xlsx = report.company(st, Settings(
                        company=o.get("name", ""), share_category=o.get("share_cat", "muu omaisuus"),
                        transaction_fees_override=-abs(ftt) if ftt else None,
                        opening_writedowns=f(o.get("wd_open")), opening_unbooked_gains=f(o.get("ug_open")),
                        evl8a_carryforward=f(o.get("cf")), credit_interest_wht=bool(o.get("int_credit")),
                        etf_symbols={x.strip() for x in str(o.get("etfs", "")).split(",") if x.strip()}))
                res["xlsx"] = base64.b64encode(xlsx).decode()
                res["version"] = __version__
                return self._json(res)
            return self._json({"error": "not found"}, 404)
        except Exception as e:  # report errors to the page instead of a dead request
            if DEBUG:
                traceback.print_exc()
            else:  # no statement contents in logs: exception type only
                print(f"{url.path}: {type(e).__name__} (lisätiedot: --debug)", file=sys.stderr)
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def main():
    ap = argparse.ArgumentParser(description="IBKR-yhteenveto local web app")
    ap.add_argument("--port", type=int, default=8501)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--debug", action="store_true", help="print tracebacks (may include statement details)")
    a = ap.parse_args()
    global DEBUG
    DEBUG = a.debug
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"IBKR-yhteenveto {__version__} running at {url}  (Ctrl+C to stop)")
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
