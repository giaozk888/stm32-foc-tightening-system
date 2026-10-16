import asyncio
import contextlib
import random
import queue
import subprocess
import unittest
from unittest.mock import patch
from pathlib import Path
from router_network.core import Router
from router_network.node import Node
from router_network.wire import Decoder, Frame, parse, message


class WireTests(unittest.TestCase):
    def test_bytewise_and_coalesced(self):
        decoder = Decoder()
        frames = [Frame(4, 1, 7, 1, 8, "PING 42"), Frame(1, 4, 7, 2, 8, "PONG 42 1")]
        data = b"".join(frame.encode() for frame in frames)
        got = []
        for byte in data:
            got.extend(decoder.feed(bytes([byte])))
        self.assertEqual(got, frames)
        self.assertEqual(Decoder().feed(data), frames)

    def test_overflow_invalid_byte_and_recovery(self):
        decoder = Decoder()
        valid = Frame(4, 1, 7, 1, 8, "PING 1")
        self.assertEqual(decoder.feed(b"x" * 10000), [])
        self.assertEqual(len(decoder.buffer), 0)
        self.assertEqual(decoder.feed(b"\nPING\x00 1\n" + valid.encode()), [valid])
        self.assertEqual(decoder.rejected, 2)

    def test_commands_are_not_a_router_console(self):
        for command in ("START", "STOP", "FW BEGIN 32 0", "FW END", "CONFIRM",
                        "PARAM SAVE", "RPC", "PING 1 START", "STATUS 1 FW END"):
            for kind in (1, 2, 4, 5, 6, 7, 255):
                with self.assertRaises(ValueError):
                    Frame(4, 1, kind, 1, 8, command).encode()

    def test_ranges_and_reply_source(self):
        for line in ("@R1 4 1 7 1 0 6 PING 1", "@R1 4 1 7 1 9 6 PING 1",
                     "@R1 4 1 7 1 8 7 PING 1", "@R1 4 1 7 1 8 8 PONG 1 2",
                     "@R1 0 1 7 1 8 6 PING 1", "@R1 4 65535 7 1 8 6 PING 1"):
            with self.assertRaises(ValueError):
                parse(line)
        with self.assertRaises(ValueError):
            message("INFO 1 4 4294967296 0 0 0")
        self.assertEqual(message("INFO 1 4 4294967295 0 0 0")[1][2], 4294967295)

    def test_bounded_random_input(self):
        randomizer = random.Random(731)
        decoder = Decoder()
        for _ in range(20000):
            decoder.feed(bytes(randomizer.randrange(256) for _ in range(randomizer.randrange(32))))
            self.assertLessEqual(len(decoder.buffer), 320)
        valid = Frame(4, 1, 7, 1, 8, "PING 1")
        self.assertEqual(decoder.feed(b"\n" + valid.encode()), [valid])

    def test_c_python_policy_parity(self):
        probe = Path(__file__).resolve().parents[2] / "tests/router_network_host/build/router_wire_probe.exe"
        if not probe.exists():
            self.skipTest("build C wire probe first")
        lines = ["@R1 4 1 7 1 8 6 PING 1", "@R1 4 65535 3 1 8 5 HELLO"]
        rng = random.Random(128)
        payloads = ["PING 1", "PONG 12 4", "STATUS 2", "INFO 1 4 0 1 2 3", "FW END",
                    "PING 0", "PING 65536", "HELLO", "ANNOUNCE", "PING  1", "PING +1"]
        for _ in range(2000):
            payload = rng.choice(payloads)
            lines.append(f"@R1 {rng.choice([0,1,4,65535])} {rng.choice([0,1,65535])} "
                         f"{rng.choice([1,3,4,7,256])} 2 {rng.choice([0,1,8,9])} {len(payload)} {payload}")
        result = subprocess.run([str(probe)], input="\n".join(lines) + "\n",
                                text=True, capture_output=True, check=True)
        expected = []
        for line in lines:
            try:
                parse(line)
                expected.append("1")
            except ValueError:
                expected.append("0")
        self.assertEqual(result.stdout.splitlines(), expected)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.router = Router(3, clock=lambda: self.now)
        self.a, self.b = [], []
        self.router.add_port("a", lambda f: self.a.append(f) is None)
        self.router.add_port("b", lambda f: self.b.append(f) is None)

    def test_discovery_multiport_reverse_learning(self):
        self.router.receive("a", Frame(4, 65535, 3, 1, 8, "HELLO"))
        self.router.receive("b", Frame(1, 65535, 3, 1, 8, "HELLO"))
        self.assertEqual(self.router.routes[4].port, "a")
        self.assertEqual(self.router.routes[1].port, "b")
        self.router.receive("a", Frame(4, 1, 7, 2, 8, "PING 1"))
        self.assertEqual(self.b[-1].ttl, 7)
        self.assertEqual(self.b[-1].dst, 1)

    def test_duplicate_ttl_self_loop(self):
        frame = Frame(4, 65535, 3, 1, 8, "HELLO")
        self.router.receive("a", frame)
        self.router.receive("a", frame)
        self.router.receive("a", Frame(4, 1, 7, 2, 1, "PING 1"))
        self.router.receive("a", Frame(3, 65535, 3, 2, 8, "HELLO"))
        self.assertEqual(self.router.stats["duplicate"], 1)
        self.assertEqual(self.router.stats["ttl"], 1)
        self.assertEqual(self.router.stats["self_loop"], 1)

    def test_disconnect_clears_routes_and_duplicate_epoch(self):
        frame = Frame(4, 65535, 3, 1, 8, "HELLO")
        self.router.receive("a", frame)
        self.router.remove_port("a")
        self.assertNotIn(4, self.router.routes)
        self.router.add_port("a", lambda f: True)
        self.router.receive("a", frame)  # Same boot sequence after reconnect.
        self.assertIn(4, self.router.routes)

    def test_aging_and_no_route(self):
        self.router.receive("a", Frame(4, 65535, 3, 1, 8, "HELLO"))
        self.now = 16
        self.router.maintenance()
        self.assertNotIn(4, self.router.routes)
        self.assertFalse(self.router.send(4, 7, "PING 1"))

    def test_invalid_does_not_learn_or_execute(self):
        self.router.receive("a", Frame(8, 3, 7, 1, 8, "START 1"))
        self.assertNotIn(8, self.router.routes)
        self.assertFalse(self.a)
        self.assertFalse(self.b)

    def test_capacity_and_tx_failure(self):
        for n in range(10, 43):
            self.router.receive("a", Frame(n, 65535, 3, 1, 8, "HELLO"))
        self.assertEqual(len(self.router.routes), 32)
        self.assertEqual(self.router.stats["route_full"], 1)
        self.router.add_port("dead", lambda frame: False)
        self.router.receive("dead", Frame(10, 65535, 3, 2, 8, "HELLO"))
        self.assertFalse(self.router.send(10, 7, "PING 1"))


class TCPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.nodes = {n: Node(n) for n in range(1, 6)}
        self.ports = {}
        self.links = {}
        for n, node in self.nodes.items():
            await node.start()
            self.ports[n] = await node.listen()
        for a, b in ((1, 2), (2, 3), (3, 4), (3, 5)):
            self.links[a, b] = await self.nodes[a].connect("127.0.0.1", self.ports[b])
        await self.discover()

    async def discover(self):
        for node in self.nodes.values():
            node.router.send(65535, 3, "HELLO")
        await asyncio.sleep(.1)
        await self.nodes[4].wait_route(1, timeout=2)

    async def asyncTearDown(self):
        await asyncio.gather(*(node.close() for node in self.nodes.values()))

    async def test_five_node_all_pairs_ping_and_status(self):
        for src in self.nodes:
            for dst in self.nodes:
                if src == dst:
                    continue
                await self.nodes[src].wait_route(dst, timeout=2)
                pong = await self.nodes[src].request(dst)
                info = await self.nodes[src].request(dst, status=True)
                self.assertEqual(pong.src, dst)
                self.assertTrue(info.payload.startswith("INFO "))
        self.assertGreater(self.nodes[2].router.stats["forwarded"], 0)
        self.assertGreater(self.nodes[3].router.stats["forwarded"], 0)

    async def test_disconnect_and_reconnect_multi_hop(self):
        middle = self.nodes[2]
        name = self.links[2, 3]
        middle.connections[name].close()
        await asyncio.sleep(.15)
        self.assertNotIn(1, self.nodes[3].router.routes)
        with self.assertRaises((asyncio.TimeoutError, ConnectionError)):
            await self.nodes[4].request(1, timeout=.15)
        await middle.connect("127.0.0.1", self.ports[3])
        await self.discover()
        self.assertEqual((await self.nodes[4].request(1)).src, 1)

    async def test_loop_and_expired_ttl(self):
        await self.nodes[1].connect("127.0.0.1", self.ports[5])
        await self.discover()
        self.assertEqual((await self.nodes[4].request(1)).src, 1)
        self.assertGreater(sum(n.router.stats["duplicate"] + n.router.stats["self_loop"]
                               for n in self.nodes.values()), 0)
        router = self.nodes[4].router
        before = self.nodes[3].router.stats["ttl"]
        router._tx(router.routes[1].port, Frame(4, 1, 7, 60000, 1, "PING 60000"))
        await asyncio.sleep(.1)
        self.assertGreater(self.nodes[3].router.stats["ttl"], before)

    async def test_real_tcp_split_coalesce_and_dangerous_input(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.ports[3])
        try:
            writer.write(b"1 START\r\n@R1 6 1 1 1 8 7 1 START\n@R1 6 1 7 2 8 6 FW END\n")
            hello = Frame(6, 65535, 3, 3, 8, "HELLO").encode()
            for byte in hello:
                writer.write(bytes([byte]))
            writer.write(Frame(6, 1, 7, 4, 8, "PING 77").encode() +
                         Frame(6, 3, 7, 5, 8, "STATUS 78").encode())
            await writer.drain()
            decoder = Decoder()
            replies = []
            for _ in range(10):
                replies.extend(decoder.feed(await asyncio.wait_for(reader.read(512), 2)))
                if any(f.payload == "PONG 77 1" for f in replies) and any(
                        f.payload.startswith("INFO 78 3 ") for f in replies):
                    break
            self.assertTrue(any(f.payload == "PONG 77 1" for f in replies))
            self.assertTrue(any(f.payload.startswith("INFO 78 3 ") for f in replies))
            self.assertGreaterEqual(self.nodes[3].router.stats["parse_error"], 3)
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_flood_closes_peer(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.ports[3])
        writer.write(b"BAD\n" * 65)
        await writer.drain()
        with contextlib.suppress(ConnectionError):
            while await asyncio.wait_for(reader.read(512), 2):
                pass
        self.assertGreater(self.nodes[3].router.stats["rate_limit"], 0)
        writer.close()
        with contextlib.suppress(ConnectionError):
            await writer.wait_closed()

    async def test_wrong_nonce_source_and_type_do_not_complete_request(self):
        node = self.nodes[4]
        future = asyncio.get_running_loop().create_future()
        node.pending[1, 123, "PONG"] = future
        try:
            node._response(Frame(1, 4, 7, 1, 8, "PONG 124 1"))
            node._response(Frame(2, 4, 7, 2, 8, "PONG 123 2"))
            node._response(Frame(1, 4, 7, 3, 8, "INFO 123 1 0 0 0 0"))
            self.assertFalse(future.done())
            node._response(Frame(1, 4, 7, 4, 8, "PONG 123 1"))
            self.assertEqual(future.result().src, 1)
        finally:
            node.pending.pop((1, 123, "PONG"), None)
            if not future.done():
                future.cancel()

    async def test_slow_peer_tx_queue_is_bounded_and_removed(self):
        node = self.nodes[3]
        previous = set(node.connections)
        reader, writer = await asyncio.open_connection("127.0.0.1", self.ports[3])
        try:
            await asyncio.sleep(.02)
            name = (set(node.connections) - previous).pop()
            for seq in range(1000, 1040):
                node.router._tx(name, Frame(3, 65535, 3, seq, 8, "HELLO"))
            await asyncio.sleep(.1)
            self.assertNotIn(name, node.router.ports)
            self.assertGreater(node.router.stats["tx_fail"], 0)
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()


class SerialTests(unittest.IsolatedAsyncioTestCase):
    async def test_usb_serial_adapter_without_hardware(self):
        import serial
        remote = Router(1)

        class FakeSerial:
            def __init__(self, **kwargs):
                self.queue = queue.Queue()
                self.decoder = Decoder()
                self.is_open = False
                self.dtr = self.rts = True
                self.writes = []
                self.baudrate = kwargs["baudrate"]

            def open(self):
                self.open_levels = self.dtr, self.rts
                self.is_open = True
                remote.add_port("uart", self.inject)
                remote.send(65535, 3, "HELLO")

            def inject(self, frame):
                self.queue.put(frame.encode())
                return True

            def read(self, count):
                if not self.is_open:
                    raise serial.SerialException("closed")
                try:
                    return self.queue.get(timeout=.02)
                except queue.Empty:
                    return b""

            def write(self, data):
                if not self.is_open:
                    raise serial.SerialException("closed")
                self.writes.append(data)
                for frame in self.decoder.feed(data):
                    remote.receive("uart", frame)
                return len(data)

            def close(self):
                self.is_open = False

        node = Node(3)
        try:
            await node.start()
            with patch("serial.Serial", FakeSerial):
                await node.attach_serial("SIM-USB", usb=True)
            await node.wait_route(1, timeout=2)
            self.assertEqual((await node.request(1)).payload, "PONG 1 1")
            port = node.serial_ports[0]
            self.assertEqual(port.open_levels, (False, False))
            self.assertEqual(port.baudrate, 115200)
            for data in port.writes:
                self.assertTrue(Decoder().feed(data))
            self.assertIn("usb-serial:SIM-USB", node.router.ports)
        finally:
            await node.close()


if __name__ == "__main__":
    unittest.main()
