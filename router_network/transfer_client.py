"""Read-only logs/encoder download using the genuine upstream native Transfer Client."""
import argparse
import asyncio
import contextlib
import json
from pathlib import Path
import os
from .node import Node, endpoint
from .wire import parse
from .transfer_wire import decode_encoder


async def run(args):
    helper = Path(args.helper)
    if not helper.is_file():
        raise RuntimeError("Build tests/router_transfer_host first; native Transfer client missing")
    node = Node(args.node)
    process = None
    feeder = None
    try:
        await node.start()
        if args.tcp:
            await node.connect(*args.tcp)
        else:
            await node.attach_serial(args.usb_serial, usb=True)
        await node.wait_route(1, timeout=25)
        process = await asyncio.create_subprocess_exec(str(helper.resolve()), str(args.node),
            str(args.resource), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
        received = asyncio.Queue(maxsize=16)

        def on_transfer(frame):
            if frame.src != 1:
                return
            try:
                received.put_nowait(frame.encode())
            except asyncio.QueueFull:
                raise RuntimeError("bounded Transfer receive queue full")

        node.router.on_transfer = on_transfer

        async def feed():
            while process.returncode is None:
                try:
                    data = await asyncio.wait_for(received.get(), .02)
                except asyncio.TimeoutError:
                    data = b"TICK\n"
                process.stdin.write(data)
                await process.stdin.drain()

        feeder = asyncio.create_task(feed())
        while True:
            line = (await asyncio.wait_for(process.stdout.readline(), 35)).decode("ascii").strip()
            if line.startswith("@R1 "):
                frame = parse(line)
                if frame.src != args.node or frame.dst != 1 or frame.type != 9:
                    raise RuntimeError("native client frame policy")
                if not node.router.send(frame.dst, frame.type, frame.payload):
                    raise RuntimeError("Router no route/transport")
            elif line.startswith("RESULT OK"):
                data = bytes.fromhex(line[len("RESULT OK"):].strip())
                if args.resource == 4:
                    print(json.dumps(decode_encoder(data), ensure_ascii=False))
                with open(args.output, "xb") as output:
                    output.write(data)
                print(f"TRANSFER READ PASS: {len(data)} bytes saved to {args.output}; no writes/reset/motion")
                break
            else:
                raise RuntimeError(line or "native client closed without completion ACK")
    finally:
        if feeder:
            feeder.cancel()
            with contextlib.suppress(asyncio.CancelledError, BrokenPipeError, ConnectionResetError):
                await feeder
        if process and process.returncode is None:
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), 2)
            except asyncio.TimeoutError:
                process.terminate()
                await process.wait()
        await node.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    connection = parser.add_mutually_exclusive_group(required=True)
    connection.add_argument("--tcp", type=endpoint)
    connection.add_argument("--usb-serial")
    parser.add_argument("--node", type=int, default=4)
    parser.add_argument("--resource", choices=(3, 4), type=int, default=3)
    parser.add_argument("--output", required=True, help="New file only; existing file is not overwritten")
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--helper", default=str(root / "tests/router_transfer_host/build" /
                       ("router_transfer_client.exe" if os.name == "nt" else "router_transfer_client")))
    args = parser.parse_args()
    if not 3 <= args.node < 65535:
        parser.error("client node must be 3..65534")
    if Path(args.output).exists():
        parser.error("output already exists; choose a new file")
    try:
        asyncio.run(run(args))
    except (RuntimeError, OSError, ValueError, asyncio.TimeoutError) as error:
        parser.exit(2, "TRANSFER NOT READY: " + str(error) + "\n")


if __name__ == "__main__":
    main()
