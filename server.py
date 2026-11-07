"""Local web app for IBKR-yhteenveto — Python standard library only (no web framework).

    python server.py            # http://127.0.0.1:8501  (opens the browser)
    python server.py --port 9000 --no-browser

Binds to 127.0.0.1 only: statements are processed in memory on this machine and never leave it.
"""
from __future__ import annotations

import argparse
import json
import secrets
import tempfile
import threading
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from ibkr_yhteenveto import load
from ibkr_yhteenveto.books import Settings
from ibkr_yhteenveto.personal import PSettings
from ibkr_yhteenveto import report

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_FILE = 100 * 1024 * 1024
SESSIONS: dict[str, dict] = {}   # sid -> {"files": {name: bytes}, "stmt": Statement|None, "xlsx": bytes, "fname": str}
LOCK = threading.Lock()
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}


def session(sid: str) -> dict:
    if not sid or len(sid) > 64:
        raise ValueError("bad session")
    with LOCK:
        return SESSIONS.setdefault(sid, {"files": {}, "stmt": None, "xlsx": None, "fname": ""})


def parse_statement(sess: dict):
    if sess["stmt"] is None:
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for name, data in sess["files"].items():
                p = Path(d) / Path(name).name
                p.write_bytes(data)
                paths.append(p)
            sess["stmt"] = load(paths)
    return sess["stmt"]


def f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


class Handler(BaseHTTPRequestHandler):
    server_version = "IBKR-yhteenveto"

    def log_message(self, fmt, *args):  # quieter console: one line per API call
        if "/api/" in (args[0] if args else ""):
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
        if n > MAX_FILE:
            raise ValueError("Tiedosto on liian suuri")
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
        if url.path == "/api/xlsx":
            q = parse_qs(url.query)
            sess = session(q.get("sid", [""])[0])
            if not sess.get("xlsx"):
                return self._json({"error": "Ei laskettua työkirjaa"}, 404)
            return self._send(200, sess["xlsx"],
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                              {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(sess['fname'])}"})
        self._json({"error": "not found"}, 404)

    def _static(self, rel: str):
        p = (STATIC / rel).resolve()
        if STATIC not in p.parents or not p.is_file():
            return self._json({"error": "not found"}, 404)
        self._send(200, p.read_bytes(), CONTENT_TYPES.get(p.suffix, "application/octet-stream"))

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        if not self._same_origin():
            return self._json({"error": "forbidden"}, 403)
        url = urlparse(self.path)
        try:
            if url.path == "/api/upload":      # raw body, one file per request
                sess = session(self.headers.get("X-Session", ""))
                name = Path(unquote(self.headers.get("X-Filename", "statement"))).name
                if Path(name).suffix.lower() not in (".pdf", ".csv"):
                    return self._json({"error": f"{name}: vain IBKR:n PDF- tai CSV-raportit"}, 400)
                data = self._body()
                with LOCK:
                    sess["files"][name] = data
                    sess["stmt"] = None
                return self._json({"ok": True, "files": list(sess["files"])})

            req = json.loads(self._body() or b"{}")
            sess = session(req.get("sid", ""))
            if url.path == "/api/clear":
                with LOCK:
                    sess.update(files={}, stmt=None, xlsx=None, fname="")
                return self._json({"ok": True})
            if url.path == "/api/remove":
                with LOCK:
                    sess["files"].pop(req.get("name", ""), None)
                    sess["stmt"] = None
                return self._json({"ok": True, "files": list(sess["files"])})
            if url.path == "/api/analyze":
                if not sess["files"]:
                    return self._json({"error": "Ei tiedostoja"}, 400)
                return self._json(report.recognised(parse_statement(sess)))
            if url.path == "/api/compute":
                st = parse_statement(sess)
                o = req.get("settings", {})
                if req.get("mode") == "personal":
                    res, xlsx = report.personal(st, PSettings(
                        name=o.get("name", ""), loss_carryforward=f(o.get("loss_cf")),
                        include_fx=bool(o.get("include_fx")), credit_interest_wht=bool(o.get("int_credit"))))
                else:
                    ftt = f(o.get("ftt"))
                    res, xlsx = report.company(st, Settings(
                        company=o.get("name", ""), share_category=o.get("share_cat", "muu omaisuus"),
                        transaction_fees_override=-abs(ftt) if ftt else None,
                        opening_writedowns=f(o.get("wd_open")), opening_unbooked_gains=f(o.get("ug_open")),
                        evl8a_carryforward=f(o.get("cf")), credit_interest_wht=bool(o.get("int_credit")),
                        etf_symbols={x.strip() for x in str(o.get("etfs", "")).split(",") if x.strip()}))
                sess["xlsx"], sess["fname"] = xlsx, res["filename"]
                return self._json(res)
            return self._json({"error": "not found"}, 404)
        except Exception as e:  # report errors to the page instead of a dead request
            traceback.print_exc()
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def main():
    ap = argparse.ArgumentParser(description="IBKR-yhteenveto local web app")
    ap.add_argument("--port", type=int, default=8501)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"IBKR-yhteenveto running at {url}  (Ctrl+C to stop)")
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
