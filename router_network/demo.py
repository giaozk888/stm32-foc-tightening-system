"""Five software nodes over real loopback TCP, never opens COM/CAN/hardware."""
import asyncio
import json
from .node import Node


async def run():
    roles = {1: "STM32-main-SIM", 2: "ESP32-SIM", 3: "LubanCat-control-box-SIM",
             4: "PC-SIM", 5: "fixture-SIM"}
    nodes = {n: Node(n) for n in roles}
    try:
        ports = {}
        for number, node in nodes.items():
            await node.start()
            ports[number] = await node.listen()
        for a, b in ((1, 2), (2, 3), (3, 4), (3, 5)):
            await nodes[a].connect("127.0.0.1", ports[b])
        for node in nodes.values():
            node.router.send(65535, 3, "HELLO")
        await nodes[4].wait_route(1)
        pairs = 0
        for src in nodes:
            for dst in nodes:
                if src != dst:
                    await nodes[src].wait_route(dst)
                    await nodes[src].request(dst)
                    await nodes[src].request(dst, status=True)
                    pairs += 1
        print(json.dumps({"result": "PASS", "hardware": False, "transport": "loopback TCP",
            "directed_pairs": pairs, "ping_and_status_exchanges": pairs * 2,
            "nodes": [{"id": n, "role": roles[n], "routes": sorted(node.router.routes),
                       "forwarded": node.router.stats["forwarded"]}
                      for n, node in nodes.items()]}, ensure_ascii=False, indent=2))
    finally:
        await asyncio.gather(*(node.close() for node in nodes.values()))


if __name__ == "__main__":
    asyncio.run(run())
