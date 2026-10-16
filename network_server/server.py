from __future__ import annotations
import argparse
import json
import os
import secrets
import socket
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from network_server.store import Store, Conflict

ASSETS = Path(__file__).parent
MAX_BODY = 2048

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    store: Store
    token: str

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, fmt, *args):
        # Do not log headers, request bodies, URL query tokens or secrets.
        pass

    def send(self, status, body, content_type="application/json; charset=utf-8", headers=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items(): self.send_header(key, value)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        expected = "Bearer " + self.token
        actual = self.headers.get("Authorization", "")
        return secrets.compare_digest(actual.encode(), expected.encode())

    def require_auth(self):
        if self.authorized(): return True
        self.close_connection = True
        self.send(401, {"error": "authentication required"})
        return False

    def do_GET(self):
        u = urlsplit(self.path)
        if u.path == "/health":
            self.send(200, {"v": 1, "control_enabled": False})
            return
        if u.path in ("/", "/app.js", "/style.css"):
            name = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}[u.path]
            ctype = {"/": "text/html", "/app.js": "text/javascript", "/style.css": "text/css"}[u.path]
            self.send(200, (ASSETS / name).read_bytes(), ctype + "; charset=utf-8")
            return
        if not self.require_auth(): return
        try:
            q = parse_qs(u.query)
            after = int(q.get("after", ["0"])[0]); limit = int(q.get("limit", ["100"])[0])
            kind = int(q["kind"][0]) if "kind" in q else None
            if u.path == "/api/v1/summary":
                self.send(200, self.store.summary())
            elif u.path == "/api/v1/observations":
                self.send(200, {"records": self.store.records(after, limit, kind)})
            elif u.path == "/api/v1/export.csv":
                self.send(200, self.store.csv_bytes(after, limit, kind), "text/csv; charset=utf-8")
            else: self.send(404, {"error": "not found"})
        except ValueError as e:
            self.send(400, {"error": str(e)})
        except sqlite3.Error:
            self.send(503, {"error": "storage unavailable"})

    def do_POST(self):
        if not self.require_auth(): return
        if self.path != "/api/v1/observations":
            self.close_connection = True
            self.send(404, {"error": "no command endpoint"}); return
        try:
            if self.headers.get("Transfer-Encoding") or self.headers.get_content_type() != "application/json":
                raise ValueError("JSON with Content-Length required")
            n = int(self.headers.get("Content-Length", "0"))
            if not 1 <= n <= MAX_BODY: raise ValueError("invalid body length")
            raw = self.rfile.read(n)
            if len(raw) != n: raise ValueError("incomplete body")
            ack = self.store.ingest(json.loads(raw))
            self.send(201 if ack["inserted"] else 200, ack, headers={
                "X-Observation-Ack": f"{ack['ack']['session']}:{ack['ack']['seq']}"})
        except Conflict as e:
            self.send(409, {"error": str(e)})
        except (ValueError, UnicodeError) as e:
            self.close_connection = True
            self.send(400, {"error": str(e)})
        except (TimeoutError, socket.timeout):
            self.close_connection = True
        except sqlite3.Error:
            self.send(503, {"error": "storage unavailable; retry same event key"})

def make_server(address, db_path, token):
    if not 24 <= len(token) <= 128 or any(not 33 <= ord(c) <= 126 for c in token):
        raise ValueError("TIGHTEN_API_TOKEN must be a printable ASCII secret of 24..128 characters without whitespace")
    handler = type("BoundHandler", (Handler,), {"store": Store(db_path), "token": token})
    return ThreadingHTTPServer(address, handler)

def main():
    p = argparse.ArgumentParser(description="Observation server; no motor controls")
    p.add_argument("--bind", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8088)
    p.add_argument("--db", default="network_data/observations.sqlite3")
    p.add_argument("--allow-lan-http", action="store_true", help="Explicit trusted-LAN demo only; use TLS reverse proxy in production")
    args = p.parse_args()
    if args.bind not in ("127.0.0.1", "localhost", "::1") and not args.allow_lan_http:
        p.error("LAN binding needs TLS reverse proxy or explicit --allow-lan-http")
    try:
        server = make_server((args.bind, args.port), args.db, os.environ.get("TIGHTEN_API_TOKEN", ""))
    except ValueError as e: p.error(str(e))
    print(f"Observation server: {args.bind}:{args.port}; motor controls locked", flush=True)
    with server:
        try: server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt: pass

if __name__ == "__main__": main()
