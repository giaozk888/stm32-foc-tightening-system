"""Local-only browser dashboard for the STM32G474 serial console.

Run from the project root: python -m upper_computer.server
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import queue
import re
import secrets
import threading
import time
import webbrowser
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import serial
from serial.tools import list_ports

from upper_computer.protocol import BAUD_RATE, number, parse_line, request_line


ASSETS = Path(__file__).resolve().parent
POLL_COMMANDS = (
    "STATUS", "FW STATUS", "ROUTER STATUS", "ROUTER NODES", "ANALOG VOLT"
)


def available_ports() -> list[dict[str, str]]:
    return [
        {"device": port.device, "description": port.description}
        for port in list_ports.comports()
    ]


class Monitor:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.commands: queue.Queue[bytes] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.connected = False
        self.port = ""
        self.error = ""
        self.request_id = 1000
        self.log_seq = 0
        self.logs: deque[dict[str, object]] = deque(maxlen=2000)
        self.samples: deque[dict[str, float | str]] = deque(maxlen=120)
        self.node_seen = False
        self.fields: dict[str, object] = {
            "mode": "—", "fault": "—", "position_deg": None,
            "iq_ma": None, "foc_hz": None, "slot": "—",
            "confirmed": "—", "pending": "—", "vbus_v": None,
            "vtemp_v": None, "analog_valid": "—", "esp": "未查询",
            "discovery_rx": "—", "discovery_tx": "—",
            "parse_errors": "—", "ping": "未测试", "last_rx": "—",
        }

    def connect(self, port: str) -> None:
        if not re.fullmatch(r"COM[1-9][0-9]*", port.upper()):
            raise ValueError("只接受 Windows COM 端口名，例如 COM5")
        with self.lock:
            if self.worker is not None and self.worker.is_alive():
                raise RuntimeError("串口已经连接或正在断开")
            self.port = port.upper()
            self.error = ""
            self.connected = False
            self.stop_event = threading.Event()
            self.worker = threading.Thread(
                target=self._run, args=(self.port, self.stop_event), daemon=True
            )
            self.worker.start()

    def disconnect(self) -> None:
        with self.lock:
            self.stop_event.set()

    def send(self, command: str) -> int:
        with self.lock:
            if not self.connected:
                raise RuntimeError("尚未连接 STM32 串口")
            request_id = self.request_id
            self.request_id = 1000 if request_id == 65535 else request_id + 1
            encoded = request_line(request_id, command)
            if command == "ROUTER NODES":
                self.node_seen = False
            if command == "ESP PING":
                self.fields["ping"] = f"请求 {request_id} 等待 ESP 回复"
            self.commands.put(encoded)
            return request_id

    def refresh(self) -> None:
        for command in POLL_COMMANDS:
            self.send(command)

    def snapshot(self, after: int = 0) -> dict[str, object]:
        with self.lock:
            return {
                "connected": self.connected,
                "port": self.port,
                "error": self.error,
                "fields": dict(self.fields),
                "samples": list(self.samples),
                "logs": [entry for entry in list(self.logs)[-400:]
                         if int(entry["seq"]) > after],
                "latest_seq": self.log_seq,
            }

    def csv_bytes(self) -> bytes:
        with self.lock:
            rows = list(self.logs)
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(("timestamp", "raw_line"))
        for row in rows:
            writer.writerow((row["timestamp"], row["line"]))
        return output.getvalue().encode("utf-8-sig")

    def _add_log(self, line: str) -> None:
        stamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        with self.lock:
            self.log_seq += 1
            self.logs.append({"seq": self.log_seq, "timestamp": stamp,
                              "line": line})
            self.fields["last_rx"] = stamp[11:19]

    def _handle_line(self, raw: str) -> None:
        message = parse_line(raw)
        self._add_log(raw)
        fields = message.fields
        with self.lock:
            target = self.fields
            if message.kind in ("telemetry", "status"):
                if "MODE" in fields:
                    target["mode"] = fields["MODE"]
                if "FLT" in fields:
                    target["fault"] = fields["FLT"]
                position = number(fields.get("POS"))
                if position is not None:
                    target["position_deg"] = position
                if message.kind == "telemetry":
                    iq = number(fields.get("Iq"))
                    foc = number(fields.get("FOC/s"))
                    if iq is not None:
                        target["iq_ma"] = iq
                    if foc is not None:
                        target["foc_hz"] = foc
                    if position is not None and iq is not None:
                        self.samples.append({"time": time.strftime("%H:%M:%S"),
                                             "position": position, "iq": iq})
            elif message.kind == "firmware":
                for source, destination in (
                    ("CURRENT", "slot"), ("CONFIRMED", "confirmed"),
                    ("PENDING", "pending")
                ):
                    if source in fields:
                        target[destination] = fields[source]
            elif message.kind == "router":
                for source, destination in (
                    ("DRX", "discovery_rx"), ("DTX", "discovery_tx"),
                    ("PARSE", "parse_errors")
                ):
                    if source in fields:
                        target[destination] = fields[source]
            elif message.kind == "nodes" and fields.get("ID") == "2":
                self.node_seen = True
                target["esp"] = f"在线 · {fields.get('AGE_MS', '?')} ms"
            elif message.kind == "nodes_end" and not self.node_seen:
                target["esp"] = "未发现节点 2"
            elif message.kind == "analog":
                bus = number(fields.get("VBUS_EST_MV"))
                temp = number(fields.get("VTEMP_MV"))
                target["vbus_v"] = bus / 1000 if bus is not None else None
                target["vtemp_v"] = temp / 1000 if temp is not None else None
                target["analog_valid"] = fields.get("VALID", "—")
            elif message.kind == "esp_ping":
                if "ESP32 PONG" in raw and message.ok:
                    target["ping"] = f"请求 {message.request_id} 成功"
                elif message.ok is False:
                    target["ping"] = raw

    def _run(self, port: str, stop_event: threading.Event) -> None:
        try:
            with serial.Serial(
                port, BAUD_RATE, bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                timeout=0.2, write_timeout=1,
            ) as device:
                with self.lock:
                    self.connected = True
                self.refresh()
                last_poll = time.monotonic()
                buffer = bytearray()
                while not stop_event.is_set():
                    for _ in range(8):
                        try:
                            outbound = self.commands.get_nowait()
                        except queue.Empty:
                            break
                        device.write(outbound)
                        device.flush()
                    if time.monotonic() - last_poll >= 5:
                        self.refresh()
                        last_poll = time.monotonic()
                    chunk = device.read(min(max(device.in_waiting, 1), 1024))
                    if not chunk:
                        continue
                    buffer.extend(chunk)
                    while b"\n" in buffer:
                        line, _, remainder = buffer.partition(b"\n")
                        buffer = bytearray(remainder)
                        text = line.decode("utf-8", "replace").strip("\r")
                        if text:
                            self._handle_line(text)
                    if len(buffer) > 4096:
                        buffer.clear()
                        self._add_log("[上位机] 超长串口行已丢弃")
        except (serial.SerialException, OSError, RuntimeError) as exc:
            with self.lock:
                self.error = str(exc)
            self._add_log(f"[上位机] 串口错误：{exc}")
        finally:
            with self.lock:
                self.connected = False
                self.fields["esp"] = "串口未连接"


class DashboardHandler(BaseHTTPRequestHandler):
    monitor: Monitor
    token: str
    port_number: int

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def _allowed_host(self) -> bool:
        return self.headers.get("Host", "") in (
            f"127.0.0.1:{self.port_number}", f"localhost:{self.port_number}"
        )

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; "
                         "style-src 'self'; script-src 'self'; connect-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: object) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:
        if not self._allowed_host():
            self._json(403, {"error": "invalid host"})
            return
        parsed = urlsplit(self.path)
        if parsed.path == "/api/state":
            try:
                after = max(0, int(parse_qs(parsed.query).get("after", ["0"])[0]))
            except ValueError:
                after = 0
            self._json(200, self.monitor.snapshot(after))
        elif parsed.path == "/api/ports":
            self._json(200, available_ports())
        elif parsed.path == "/api/log.csv":
            self._send(200, self.monitor.csv_bytes(), "text/csv; charset=utf-8")
        elif parsed.path in ("/", "/style.css", "/app.js"):
            filename = {"/": "index.html", "/style.css": "style.css",
                        "/app.js": "app.js"}[parsed.path]
            body = (ASSETS / filename).read_bytes()
            if filename == "index.html":
                body = body.replace(b"__PANEL_TOKEN__", self.token.encode("ascii"))
            content_type = ("text/html" if filename.endswith(".html") else
                            "text/css" if filename.endswith(".css") else
                            "text/javascript")
            self._send(200, body, content_type + "; charset=utf-8")
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._allowed_host() or self.headers.get("X-Panel-Token") != self.token:
            self._json(403, {"error": "forbidden"})
            return
        origin = self.headers.get("Origin")
        if origin and origin not in (
            f"http://127.0.0.1:{self.port_number}",
            f"http://localhost:{self.port_number}"
        ):
            self._json(403, {"error": "invalid origin"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 4096 or length < 0:
                raise ValueError("请求过长")
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("请求必须是 JSON 对象")
            if self.path == "/api/connect":
                self.monitor.connect(str(payload.get("port", "")))
                result: object = {"ok": True}
            elif self.path == "/api/disconnect":
                self.monitor.disconnect()
                result = {"ok": True}
            elif self.path == "/api/refresh":
                self.monitor.refresh()
                result = {"ok": True}
            elif self.path == "/api/esp-ping":
                result = {"ok": True, "request_id": self.monitor.send("ESP PING")}
            else:
                self._json(404, {"error": "not found"})
                return
            self._json(200, result)
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})


def main() -> None:
    parser = argparse.ArgumentParser(description="STM32G474 local-only dashboard")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    monitor = Monitor()
    handler = type(
        "BoundDashboardHandler", (DashboardHandler,),
        {"monitor": monitor, "token": secrets.token_urlsafe(24),
         "port_number": args.port},
    )
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        url = f"http://127.0.0.1:{args.port}/"
        print(f"上位机已启动：{url}", flush=True)
        print("仅监听本机；按 Ctrl+C 退出。", flush=True)
        if not args.no_browser:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass
        finally:
            monitor.disconnect()


if __name__ == "__main__":
    main()
