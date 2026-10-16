"""Read-only Router hardware probe. Sends only numeric PING/STATUS/discovery."""
from __future__ import annotations
import argparse
import asyncio
import json
import time
from .node import Node, endpoint
from .wire import Frame


async def exercise(node, targets, rounds, replies):
    for target in targets:
        await node.wait_route(target, timeout=25)
        for status in (False, True):
            reply = await node.request(target, status, timeout=5)
            replies.append({"origin": node.router.node, "source": reply.src,
                            "reply": reply.payload})
            print(json.dumps(replies[-1]), flush=True)
    completed = 0
    for _ in range(rounds):
        for target in targets:
            for status in (False, True):
                await node.request(target, status, timeout=5)
                completed += 1
                await asyncio.sleep(.08)
    return completed


async def run(args):
    node = Node(4)
    fixture = Node(5) if args.fixture_sim else None
    replies = []
    started = time.monotonic()
    try:
        await node.start()
        if args.usb_serial:
            await node.attach_serial(args.usb_serial, usb=True)
        else:
            await node.connect(*args.tcp)
        targets = list(args.target or [1, 2])
        completed = await exercise(node, targets, args.rounds, replies)

        # Identical safe PING frames must produce exactly one PONG. Count actual
        # replies, not merely whether a future was completed at least once.
        observed = []
        original = node.router.on_response
        def response(frame):
            if frame.payload == "PONG 60000 1":
                observed.append(frame)
            original(frame)
        node.router.on_response = response
        port = node.router.routes[1].port
        ping = Frame(4, 1, 7, 60000, 8, "PING 60000")
        if not node.router._tx(port, ping) or not node.router._tx(port, ping):
            raise AssertionError("duplicate test TX rejected")
        await asyncio.sleep(1)
        if len(observed) != 1:
            raise AssertionError("duplicate test PONG count=" + str(len(observed)))
        print("PASS duplicate suppression: two identical PINGs, one PONG", flush=True)

        # TTL=1 can reach the first router, but must not reach a downstream MCU
        # (TCP path) or ESP (USB path). No invalid or actuator command is sent.
        ttl_target = 2 if args.usb_serial else 1
        if ttl_target in targets:
            ttl_reply = []
            def ttl_response(frame):
                if frame.payload == "PONG 60001 " + str(ttl_target):
                    ttl_reply.append(frame)
                original(frame)
            node.router.on_response = ttl_response
            frame = Frame(4, ttl_target, 7, 60001, 1, "PING 60001")
            if not node.router._tx(node.router.routes[ttl_target].port, frame):
                raise AssertionError("TTL test TX rejected")
            await asyncio.sleep(1)
            if ttl_reply:
                raise AssertionError("expired TTL reached downstream node")
            await node.request(ttl_target, timeout=5)
            print("PASS TTL=1: no downstream response; normal TTL still works", flush=True)
        node.router.on_response = original

        if fixture:
            await fixture.start()
            await fixture.connect(*args.tcp)
            await node.wait_route(5, timeout=15)
            await fixture.wait_route(4, timeout=15)
            completed += await exercise(fixture, [1, 2, 3, 4], 0, replies)
            completed += await exercise(node, [5], 0, replies)

        result = {"result": "PASS", "hardware": True,
                  "transport": "USB-STLink-VCP + MCU UART" if args.usb_serial else "PC TCP to LubanCat",
                  "initial_replies": replies, "additional_stress_exchanges": completed,
                  "rounds": args.rounds, "fixture_is_simulated": bool(fixture),
                  "elapsed_seconds": round(time.monotonic() - started, 2),
                  "local_routes": sorted(node.router.routes),
                  "local_stats": dict(node.router.stats),
                  "commands": "discovery and numeric PING/STATUS only; no motor or Flash commands"}
        print(json.dumps(result, indent=2), flush=True)
    finally:
        await node.close()
        if fixture:
            await fixture.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    transport = parser.add_mutually_exclusive_group(required=True)
    transport.add_argument("--usb-serial")
    transport.add_argument("--tcp", type=endpoint)
    parser.add_argument("--target", action="append", type=int)
    parser.add_argument("--rounds", type=int, choices=range(0, 51), default=10)
    parser.add_argument("--fixture-sim", action="store_true")
    args = parser.parse_args()
    if args.fixture_sim and not args.tcp:
        parser.error("fixture SIM requires TCP; it is not a physical board")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
