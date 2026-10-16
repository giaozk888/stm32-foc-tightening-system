"""Small, side-effect-free parser for the STM32 Protocol V2 console."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


BAUD_RATE = 115200
ALLOWED_COMMANDS = frozenset(
    {
        "STATUS",
        "FW STATUS",
        "ROUTER STATUS",
        "ROUTER NODES",
        "ANALOG VOLT",
        "ESP PING",
    }
)

_TAGGED = re.compile(r"^(\d+)\s+(OK|ERR)\s+(.*)$")
_TAGGED_DETAIL = re.compile(r"^(\d+)\s+(NODE ID=|END ROUTER NODES)(.*)$")
_FIELD = re.compile(r"\b([A-Za-z][A-Za-z0-9_/]*)=([^\s|]+)")
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)")


@dataclass(frozen=True)
class Message:
    kind: str
    raw: str
    request_id: int | None = None
    ok: bool | None = None
    fields: dict[str, str] = field(default_factory=dict)


def parse_line(line: str) -> Message:
    """Parse known lines while preserving unknown lines for the log view."""
    raw = line.strip("\r\n")
    fields = dict(_FIELD.findall(raw))

    if raw.startswith("RTOS-FOC "):
        return Message("telemetry", raw, fields=fields)

    tagged = _TAGGED.match(raw)
    if tagged:
        request_id = int(tagged.group(1))
        ok = tagged.group(2) == "OK"
        payload = tagged.group(3)
        if payload.startswith("FW "):
            kind = "firmware"
        elif payload.startswith("STATUS "):
            kind = "status"
        elif payload.startswith("ROUTER NODE="):
            kind = "router"
        elif payload.startswith("ROUTER NODES") or payload.startswith("NODE ID="):
            kind = "nodes"
        elif payload.startswith("END ROUTER NODES"):
            kind = "nodes_end"
        elif payload.startswith("ANALOG VOLT "):
            kind = "analog"
        elif ("ESP32 PONG" in payload or "ESP PING" in payload or
              "ESP_PING" in payload or "ESP_NO_ROUTE" in payload):
            kind = "esp_ping"
        else:
            kind = "reply"
        return Message(kind, raw, request_id, ok, fields)

    detail = _TAGGED_DETAIL.match(raw)
    if detail:
        kind = "nodes" if detail.group(2) == "NODE ID=" else "nodes_end"
        return Message(kind, raw, int(detail.group(1)), None, fields)

    return Message("log", raw, fields=fields)


def number(text: str | None) -> float | None:
    """Extract a leading number from firmware values such as '0.02deg'."""
    if text is None:
        return None
    match = _NUMBER.match(text)
    return float(match.group()) if match else None


def request_line(request_id: int, command: str) -> bytes:
    """Construct only commands exposed by this read-only UI."""
    if not 1 <= request_id <= 65535:
        raise ValueError("request ID must be 1..65535")
    if command not in ALLOWED_COMMANDS:
        raise ValueError(f"command is not allowed: {command}")
    return f"{request_id} {command}\r\n".encode("ascii")
