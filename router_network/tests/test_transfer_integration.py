"""Host-only TCP + actual A/B Router and official native Transfer endpoints."""
import argparse
import asyncio
import contextlib
import os
from pathlib import Path
import tempfile
import unittest
from router_network.node import Node
from router_network.wire import parse
from router_network.transfer_client import run
from router_network.transfer_wire import decode_encoder

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "tests/router_transfer_host/build"


class NativeTcpTransferTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_native_client_and_ab_server_through_tcp_bridge(self):
        suffix = ".exe" if os.name == "nt" else ""
        helper = BUILD / ("router_transfer_client" + suffix)
        if not helper.is_file():
            self.fail("Build tests/router_transfer_host before the integration test")
        for slot in ("a", "b"):
            bridge, stm32 = Node(2), Node(1)
            process = None
            tasks = []
            environment = os.environ.copy()
            if os.name == "nt":
                environment["PATH"] = "D:/Qt/Tools/mingw1310_64/bin;" + environment["PATH"]
            try:
                await bridge.start()
                port = await bridge.listen()
                await stm32.start()
                await stm32.connect("127.0.0.1", port)
                process = await asyncio.create_subprocess_exec(
                    str(BUILD / (f"router_transfer_{slot}_test" + suffix)), "--stdio-server",
                    env=environment, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
                queue = asyncio.Queue(maxsize=16)
                stm32.router.on_transfer = lambda frame: queue.put_nowait(frame.encode())

                async def feed():
                    while True:
                        try:
                            data = await asyncio.wait_for(queue.get(), .02)
                        except asyncio.TimeoutError:
                            data = b"TICK\n"
                        process.stdin.write(data)
                        await process.stdin.drain()

                async def replies():
                    while True:
                        line = await process.stdout.readline()
                        if not line:
                            return
                        frame = parse(line.decode().strip())
                        self.assertEqual(frame.src, 1)
                        self.assertTrue(stm32.router.send(frame.dst, frame.type, frame.payload))

                tasks = [asyncio.create_task(feed()), asyncio.create_task(replies())]
                with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as folder:
                    for resource in (3, 4):
                        output = Path(folder) / f"resource-{resource}.bin"
                        args = argparse.Namespace(helper=str(helper), tcp=("127.0.0.1", port),
                            usb_serial=None, node=4, resource=resource, output=str(output))
                        await asyncio.wait_for(run(args), 20)
                        if resource == 3:
                            self.assertEqual(output.read_bytes(), b"R" * 400 + b"\nRouter official history\n")
                        else:
                            self.assertEqual(decode_encoder(output.read_bytes())["raw"], 1234)
                self.assertEqual(bridge.router.stats["rate_limit"], 0)
                self.assertGreater(bridge.router.stats["forwarded"], 0)
                for task in tasks:
                    if task.done() and not task.cancelled():
                        task.result()
            finally:
                for task in tasks:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, BrokenPipeError):
                        await task
                if process and process.returncode is None:
                    process.stdin.close()
                    try:
                        await asyncio.wait_for(process.wait(), 3)
                    except asyncio.TimeoutError:
                        process.terminate()
                        await process.wait()
                await stm32.close()
                await bridge.close()
