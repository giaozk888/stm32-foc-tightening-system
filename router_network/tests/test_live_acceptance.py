"""Host-only admission/evidence tests. No serial, LAN, MCU or performance proof."""
import asyncio
from collections import Counter
import contextlib
import io
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from router_network import rpc_live_acceptance as acceptance


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, mode, fail=False):
        instances = []
        sleep = asyncio.sleep
        active = 0
        high = 0

        class FakeNode:
            def __init__(self, identity):
                self.router = SimpleNamespace(node=identity, next_seq=1, stats=Counter())
                self.connections = {"fake": None}
                self.closed = False
                self.active = self.high = 0
                instances.append(self)

            async def start(self):
                pass

            async def connect(self, *_):
                pass

            async def wait_route(self, *_):
                pass

            async def rpc_request(self, method, payload):
                nonlocal active, high
                active += 1
                high = max(high, active)
                self.active += 1
                self.high = max(self.high, self.active)
                try:
                    await sleep(.003)
                    if fail and self.router.node == 5 and method == "Ping":
                        raise TimeoutError("injected host failure")
                    self.router.stats["rx"] += 1
                    if method == "Ping":
                        return payload
                    if method == "GetStatus":
                        return struct.pack("<8I", 1, 100, 0, 4, 0, 1, 0, 0)
                    if method == "GetParams":
                        return struct.pack("<19I", 1, *range(18))
                    return struct.pack("<10I", 1, *([0] * 9))
                finally:
                    self.active -= 1
                    active -= 1

            async def close(self):
                self.closed = True
                self.connections.clear()

        async def short_sleep(_):
            await sleep(.005)

        progress = {}
        args = SimpleNamespace(node=5, rounds=1, tcp=("127.0.0.1", 1),
                               usb_serial=None, rpc_mode=mode, progress=progress)
        with patch.object(acceptance, "Node", FakeNode), \
                patch.object(acceptance.asyncio, "sleep", short_sleep), \
                contextlib.redirect_stdout(io.StringIO()):
            if fail:
                with self.assertRaises(TimeoutError):
                    await acceptance.run(args)
            else:
                summary = await acceptance.run(args)
                self.assertEqual(summary["rpc_queries"], 8)
                self.assertTrue(progress["pass_"])
                self.assertEqual(progress["completed"], 8)
        self.assertTrue(all(node.closed for node in instances))
        self.assertEqual(active, 0)
        return instances, high, progress

    async def test_paced_has_one_in_flight_each_but_two_concurrent_peers(self):
        nodes, high, progress = await self.exercise("paced")
        self.assertEqual([node.high for node in nodes], [1, 1])
        self.assertEqual(high, 2)
        self.assertTrue(all(call["ok"] for call in progress["calls"]))

    async def test_burst_retains_eight_simultaneous_calls(self):
        nodes, high, _ = await self.exercise("burst")
        self.assertEqual([node.high for node in nodes], [4, 4])
        self.assertEqual(high, 8)

    async def test_timeout_retains_identity_evidence_and_closes_nodes(self):
        _, _, progress = await self.exercise("paced", fail=True)
        failed = [call for call in progress["calls"] if call.get("ok") is False]
        self.assertEqual(len(failed), 1)
        self.assertEqual((failed[0]["node"], failed[0]["method"], failed[0]["error_type"]),
                         (5, "Ping", "TimeoutError"))
        self.assertFalse(progress["pass_"])
        self.assertEqual(set(progress["node_stats"]), {"5", "6"})
