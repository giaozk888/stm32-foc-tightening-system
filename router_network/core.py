"""Single-owner Router state. Adapter callbacks must be bounded/nonblocking."""
from __future__ import annotations
from collections import Counter, OrderedDict
from dataclasses import dataclass
from typing import Callable
import time
from .wire import BROADCAST, DISCOVERY, DIAGNOSTIC, Frame, message
from .rpc import TYPE as RPC
from .transfer_wire import TYPE as TRANSFER, parse as parse_transfer


@dataclass
class Route:
    port: str
    refreshed: float


class Router:
    def __init__(self, node: int, clock=time.monotonic):
        if not 1 <= node < BROADCAST:
            raise ValueError("node must be 1..65534")
        self.node = node
        self.clock = clock
        self.ports: dict[str, Callable[[Frame], bool]] = {}
        self.routes: dict[int, Route] = {}
        self.seen: OrderedDict[tuple[int, int, int], float] = OrderedDict()
        self.stats = Counter()
        self.next_seq = 1
        self.last_hello = -5.0
        self.on_response: Callable[[Frame], None] = lambda frame: None
        self.on_rpc: Callable[[Frame], None] = lambda frame: None
        self.on_transfer: Callable[[Frame], None] = lambda frame: None

    def add_port(self, name: str, send: Callable[[Frame], bool]):
        if name in self.ports or len(self.ports) >= 8:
            raise ValueError("duplicate port or eight-port capacity")
        self.ports[name] = send

    def remove_port(self, name: str):
        self.ports.pop(name, None)
        lost = {n for n, r in self.routes.items() if r.port == name}
        self.routes = {n: r for n, r in self.routes.items() if r.port != name}
        self.seen = OrderedDict((key, stamp) for key, stamp in self.seen.items()
                                if key[0] not in lost)

    def _tx(self, port: str, frame: Frame) -> bool:
        send = self.ports.get(port)
        if send and send(frame):
            self.stats["tx"] += 1
            return True
        self.stats["tx_fail"] += 1
        return False

    def send(self, destination: int, kind: int, payload: str) -> bool:
        frame = Frame(self.node, destination, kind, self.next_seq, 8, payload)
        if not frame.allowed():
            raise ValueError("only exact discovery, numeric diagnostics and bounded read-only RPC")
        self.next_seq = (self.next_seq + 1) & 65535
        if destination == self.node:
            self._local(frame)
            return True
        if destination == BROADCAST:
            sent = False
            for port in tuple(self.ports):
                sent = self._tx(port, frame) or sent
            return sent
        route = self.routes.get(destination)
        if not route or self.clock() - route.refreshed > 15:
            self.routes.pop(destination, None)
            self.stats["no_route"] += 1
            return False
        return self._tx(route.port, frame)

    def receive(self, ingress: str, frame: Frame):
        self.stats["rx"] += 1
        if ingress not in self.ports or not frame.allowed():
            self.stats["invalid"] += 1
            return
        if frame.src == self.node:
            self.stats["self_loop"] += 1
            return
        now = self.clock()
        key = (frame.src, frame.seq, frame.type)
        if frame.type == TRANSFER:
            fragment = parse_transfer(frame.payload)
            key = (frame.src, frame.type, fragment.packet_id, fragment.offset, fragment.crc)
        if key in self.seen and now - self.seen[key] <= 30:
            self.stats["duplicate"] += 1
            return
        self.seen[key] = now
        self.seen.move_to_end(key)
        while len(self.seen) > 256:
            self.seen.popitem(last=False)
        if frame.src in self.routes or len(self.routes) < 32:
            self.routes[frame.src] = Route(ingress, now)
        else:
            self.stats["route_full"] += 1
        if frame.type == DISCOVERY and frame.payload == "HELLO":
            self.send(frame.src, DISCOVERY, "ANNOUNCE")
        elif frame.dst == self.node:
            self._local(frame)
        if frame.dst == self.node:
            return
        if frame.ttl <= 1:
            self.stats["ttl"] += 1
            return
        if frame.dst == BROADCAST:
            for port in tuple(self.ports):
                if port != ingress and self._tx(port, frame.forwarded()):
                    self.stats["forwarded"] += 1
        else:
            route = self.routes.get(frame.dst)
            if not route or now - route.refreshed > 15:
                self.routes.pop(frame.dst, None)
                self.stats["no_route"] += 1
            elif route.port == ingress:
                self.stats["same_port"] += 1
            elif self._tx(route.port, frame.forwarded()):
                self.stats["forwarded"] += 1

    def _local(self, frame: Frame):
        if frame.type == TRANSFER:
            self.on_transfer(frame)
            return
        if frame.type == RPC:
            self.on_rpc(frame)
            return
        if frame.type != DIAGNOSTIC:
            return
        kind, values = message(frame.payload)
        nonce = values[0]
        if kind == "PING":
            self.send(frame.src, DIAGNOSTIC, f"PONG {nonce} {self.node}")
        elif kind == "STATUS":
            counters = " ".join(str(self.stats[k] & 0xFFFFFFFF)
                                for k in ("rx", "tx", "no_route", "duplicate"))
            self.send(frame.src, DIAGNOSTIC, f"INFO {nonce} {self.node} {counters}")
        else:
            self.on_response(frame)

    def maintenance(self):
        now = self.clock()
        expired = [n for n, r in self.routes.items() if now - r.refreshed > 15]
        for node in expired:
            del self.routes[node]
            self.stats["aged"] += 1
        while self.seen and now - next(iter(self.seen.values())) > 30:
            self.seen.popitem(last=False)
        if now - self.last_hello >= 5:
            self.last_hello = now
            self.send(BROADCAST, DISCOVERY, "HELLO")
