"""Read-only live reconnect probe; closes only this process's own TCP link."""
from __future__ import annotations

import argparse
import asyncio
import json
import time

from .node import Node, endpoint


async def run(args):
    # Separate host probe ID, not another physical board. Keep sequence state
    # across reconnects rather than restarting/reusing a peer's sequence IDs.
    node = Node(6)
    started = time.monotonic()
    cycles = []
    try:
        await node.start()
        node._spawn(node.connect_forever(*args.tcp))
        await node.wait_route(1, timeout=25)
        await node.request(1, timeout=5)
        for _ in range(args.cycles):
            previous = node.router.routes[1].port
            node.connections[previous].close()
            deadline = time.monotonic() + 3
            while previous in node.connections and time.monotonic() < deadline:
                await asyncio.sleep(.01)
            if previous in node.connections:
                raise AssertionError("closed TCP port was not detached")
            if any(route.port == previous for route in node.router.routes.values()):
                raise AssertionError("route still points to disconnected TCP port")
            await node.wait_route(1, timeout=25)
            replacement = node.router.routes[1].port
            if replacement == previous:
                raise AssertionError("recovery reused detached port")
            replies = []
            for target in (1, 2, 3):
                await node.wait_route(target, timeout=15)
                for status in (False, True):
                    reply = await node.request(target, status, timeout=5)
                    replies.append({"source": reply.src, "reply": reply.payload})
                    await asyncio.sleep(.08)
            result = {"old_port": previous, "new_port": replacement,
                      "old_port_routes_removed": True, "replies": replies}
            cycles.append(result)
            print(json.dumps(result), flush=True)
        print(json.dumps({"result": "PASS", "hardware": True,
                          "scope": "PC-LubanCat TCP reconnect; downstream MCU/ESP remain running",
                          "probe_node": 6, "probe_is_host_process": True,
                          "cycles": cycles,
                          "elapsed_seconds": round(time.monotonic() - started, 2),
                          "commands": "discovery and numeric PING/STATUS only"}, indent=2),
              flush=True)
    finally:
        await node.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tcp", type=endpoint, required=True)
    parser.add_argument("--cycles", type=int, choices=range(1, 4), default=2)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
