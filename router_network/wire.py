"""R1 framing, type-7 diagnostics and opt-in type-8 read-only RPC policy."""
from __future__ import annotations
from dataclasses import dataclass, replace
import re
from .rpc import TYPE as RPC, allowed as rpc_allowed
from .transfer_wire import TYPE as TRANSFER, allowed as transfer_allowed

MAX_LINE = 320
MAX_PAYLOAD = 224
BROADCAST = 65535
DISCOVERY = 3
DIAGNOSTIC = 7
_FRAME = re.compile(r"@R1 ([0-9]+) ([0-9]+) ([0-9]+) ([0-9]+) ([0-9]+) ([0-9]+) (.*)", re.ASCII)


def message(payload: str) -> tuple[str, tuple[int, ...]]:
    parts = payload.split(" ")
    lengths = {"PING": 1, "PONG": 2, "STATUS": 1, "INFO": 6}
    kind = parts[0]
    if kind not in lengths or len(parts) != lengths[kind] + 1:
        raise ValueError("diagnostic grammar")
    if any(not p or not p.isascii() or not p.isdecimal() for p in parts[1:]):
        raise ValueError("numeric fields only")
    values = tuple(int(p) for p in parts[1:])
    if not 1 <= values[0] <= 65535:
        raise ValueError("nonce range")
    if kind in ("PONG", "INFO") and not 1 <= values[1] <= 65534:
        raise ValueError("node range")
    if any(v > 0xFFFFFFFF for v in values[2:]):
        raise ValueError("counter range")
    return kind, values


@dataclass(frozen=True)
class Frame:
    src: int
    dst: int
    type: int
    seq: int
    ttl: int
    payload: str

    def allowed(self) -> bool:
        if (not 1 <= self.src < BROADCAST or not 1 <= self.dst <= BROADCAST or
                not 0 <= self.seq <= 65535 or not 1 <= self.ttl <= 8 or
                len(self.payload) > MAX_PAYLOAD or
                any(not 32 <= ord(c) <= 126 for c in self.payload)):
            return False
        if self.type == DISCOVERY:
            return ((self.payload == "HELLO" and self.dst == BROADCAST) or
                    (self.payload == "ANNOUNCE" and self.dst != BROADCAST))
        if self.type == RPC:
            return rpc_allowed(self.src, self.dst, self.payload)
        if self.type == TRANSFER:
            return transfer_allowed(self.src, self.dst, self.payload)
        if self.type != DIAGNOSTIC or self.dst == BROADCAST:
            return False
        try:
            kind, values = message(self.payload)
        except ValueError:
            return False
        return kind not in ("PONG", "INFO") or values[1] == self.src

    def encode(self) -> bytes:
        if not self.allowed():
            raise ValueError("not an allowed read-only Router frame")
        return (f"@R1 {self.src} {self.dst} {self.type} {self.seq} {self.ttl} "
                f"{len(self.payload)} {self.payload}\r\n").encode("ascii")

    def forwarded(self) -> "Frame":
        if self.ttl <= 1:
            raise ValueError("TTL exhausted")
        return replace(self, ttl=self.ttl - 1)


def parse(line: str) -> Frame:
    if len(line) > MAX_LINE:
        raise ValueError("line too long")
    matched = _FRAME.fullmatch(line)
    if not matched:
        raise ValueError("not R1")
    src, dst, kind, seq, ttl, length = map(int, matched.groups()[:6])
    frame = Frame(src, dst, kind, seq, ttl, matched.group(7))
    if length != len(frame.payload) or not frame.allowed():
        raise ValueError("length/policy")
    return frame


class Decoder:
    """Bounded resynchronization, including after a partial/invalid UART line."""
    def __init__(self):
        self.buffer = bytearray()
        self.dropping = False
        self.rejected = 0

    def feed(self, data: bytes) -> list[Frame]:
        frames = []
        for c in data:
            if c in (10, 13):
                if self.buffer and not self.dropping:
                    try:
                        frames.append(parse(self.buffer.decode("ascii")))
                    except ValueError:
                        self.rejected += 1
                self.buffer.clear()
                self.dropping = False
            elif not self.dropping:
                if not 32 <= c <= 126 or len(self.buffer) >= MAX_LINE:
                    self.buffer.clear()
                    self.dropping = True
                    self.rejected += 1
                else:
                    self.buffer.append(c)
        return frames
