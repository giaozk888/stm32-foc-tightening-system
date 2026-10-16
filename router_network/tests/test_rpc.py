import asyncio
import random
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from router_network import rpc
from router_network.node import Node
from router_network.wire import Frame, parse

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "tests/router_rpc_host/build"


class PolicyTests(unittest.TestCase):
    def test_versioned_named_snapshot_decoder(self):
        import struct
        payload = struct.pack("<8I", 1, 123, 0, 6, 2, 1, 0, 0)
        status = rpc.decode_payload("GetStatus", payload)
        self.assertEqual(status["uptime_ms"], 123)
        self.assertFalse(status["foc_enabled"])
        self.assertTrue(status["fault"])
        self.assertTrue(status["encoder_valid"])
        self.assertEqual(len(rpc.decode_payload("GetParams", struct.pack("<19I", 1, *range(18)))), 19)
        self.assertEqual(rpc.decode_payload("GetDiagnostics", struct.pack("<10I", 1, *range(9)))["can_rpc_fifo_overruns"], 8)
        for method, invalid in (("GetStatus", bytes(32)), ("GetParams", bytes(32)),
                                ("Write", bytes(76))):
            with self.assertRaises(ValueError):
                rpc.decode_payload(method, invalid)

    def test_request_reply_and_mtu(self):
        request = rpc.request(4, "GetParams", 0xFFFFFFFF)
        self.assertTrue(Frame(4, 1, 8, 1, 8, request).allowed())
        p = rpc.decode(request)
        reply = rpc.encode(replace(p, type=1, payload=bytes(76)))
        self.assertTrue(Frame(1, 4, 8, 2, 8, reply).allowed())
        self.assertLessEqual(len(reply), 224)
        self.assertFalse(Frame(1, 5, 8, 2, 8, reply).allowed())
        self.assertFalse(Frame(2, 4, 8, 2, 8, reply).allowed())
        self.assertFalse(Frame(4, 65535, 8, 2, 8, request).allowed())
        with self.assertRaises(ValueError):
            rpc.request(4, "Write", 1)
        with self.assertRaises(ValueError):
            rpc.request(4, "Ping", 1, bytes(17))

    def test_reject_writes_streams_and_malformed_protobuf(self):
        p = rpc.decode(rpc.request(4, "Ping", 1))
        for change in (dict(type=2), dict(type=8), dict(service=123),
                       dict(method=rpc.METHODS["Ping"]+1), dict(channel=2),
                       dict(call=0), dict(status=1)):
            self.assertFalse(rpc.allowed(4, 1, rpc.encode(replace(p, **change))))
        for suffix in ("", "00", "0800", "2A7FFF", "FFFFFFFFFF"):
            text = rpc.request(4, "Ping", 1) + suffix
            if suffix:
                self.assertFalse(rpc.allowed(4, 1, text))
        self.assertFalse(rpc.allowed(4, 1, rpc.request(4, "Ping", 1).lower()))
        self.assertFalse(rpc.allowed(4, 1, "RPC " + "00"*111))
        self.assertFalse(rpc.allowed(4, 1, "RPC " + "00"*110 + "FW END"))

    def test_rpc_c_python_policy_parity(self):
        probe = BUILD / "router_rpc_wire_probe.exe"
        if not probe.exists():
            self.fail("build genuine Router RPC C tests first")
        inputs = []
        for src in (0, 1, 2, 4, 5, 65535):
            for dst in (0, 1, 4, 5, 65535):
                for method in rpc.METHODS:
                    p = rpc.decode(rpc.request(4, method, 5))
                    for packet in (p, replace(p, type=1, payload=bytes(rpc.SIZES[p.method])),
                                   replace(p, type=5, status=14), replace(p, type=2)):
                        text = rpc.encode(packet)
                        inputs.append(f"@R1 {src} {dst} 8 2 8 {len(text)} {text}")
        rng = random.Random(89)
        for _ in range(1000):
            text = "RPC " + bytes(rng.randrange(256) for _ in range(rng.randrange(1, 114))).hex().upper()
            inputs.append(f"@R1 4 1 8 3 8 {len(text)} {text}")
        result = subprocess.run([str(probe)], input="\n".join(inputs)+"\n",
                                capture_output=True, text=True, check=True)
        expected = []
        for line in inputs:
            try:
                parse(line)
                expected.append("1")
            except ValueError:
                expected.append("0")
        self.assertEqual(result.stdout.splitlines(), expected)


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_pigweed_server_through_five_tcp_nodes_two_clients(self):
        executable = BUILD / "router_rpc_a_test.exe"
        self.assertTrue(executable.exists(), "build genuine server probe first")
        process = await asyncio.create_subprocess_exec(str(executable), "--probe",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        nodes = {n: Node(n) for n in (1, 2, 3, 4, 5)}
        tasks = set()
        lock = asyncio.Lock()
        async def dispatch(frame):
            async with lock:
                process.stdin.write(frame.encode())
                await process.stdin.drain()
                line = await asyncio.wait_for(process.stdout.readline(), 3)
                response = parse(line.decode("ascii").strip())
                # Actual C Router/Server determines source/destination/payload;
                # the Python port allocates its own monotonically increasing seq.
                self.assertEqual(response.src, 1)
                self.assertEqual(response.dst, frame.src)
                self.assertTrue(nodes[1].router.send(response.dst, rpc.TYPE, response.payload))
        def incoming(frame):
            task = asyncio.create_task(dispatch(frame))
            tasks.add(task)
        nodes[1].router.on_rpc = incoming
        try:
            ports = {}
            for n, node in nodes.items():
                await node.start()
                ports[n] = await node.listen()
            for a, b in ((1, 2), (2, 3), (3, 4), (3, 5)):
                await nodes[a].connect("127.0.0.1", ports[b])
            for n in (4, 5):
                await nodes[n].wait_route(1, 3)
            for method in rpc.METHODS:
                a, b = await asyncio.gather(nodes[4].rpc_request(method), nodes[5].rpc_request(method))
                self.assertEqual(len(a), rpc.SIZES[rpc.METHODS[method]])
                self.assertEqual(a, b)
            replies = await asyncio.gather(*(nodes[4].rpc_request(method) for method in rpc.METHODS))
            self.assertEqual([len(data) for data in replies], [16, 32, 76, 40])
            self.assertFalse(nodes[4].rpc_pending)
            self.assertFalse(nodes[5].rpc_pending)
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for node in nodes.values():
                await node.close()
            process.stdin.close()
            await asyncio.wait_for(process.wait(), 3)

    async def test_wrong_method_call_or_channel_does_not_complete_rpc(self):
        node = Node(4)
        sent = []
        node.router.add_port("capture", lambda frame: sent.append(frame) is None)
        node.router.receive("capture", Frame(1, 65535, 3, 1, 8, "HELLO"))
        request_task = asyncio.create_task(node.rpc_request("Ping", timeout=.05))
        try:
            await asyncio.sleep(0)
            p = rpc.decode(sent[-1].payload)
            for seq, wrong in enumerate((replace(p, call=8), replace(p, channel=65541),
                replace(p, method=rpc.METHODS["GetStatus"], payload=bytes(32))), 5):
                node.router.receive("capture", Frame(1, 4, 8, seq, 8, rpc.encode(replace(wrong, type=1))))
            with self.assertRaises(asyncio.TimeoutError):
                await request_task
            self.assertFalse(node.rpc_pending)
        finally:
            await node.close()
