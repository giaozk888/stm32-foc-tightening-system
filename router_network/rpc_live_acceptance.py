"""Hardware read-only RPC probe; no motion, parameter writes, Flash or reset commands."""
import argparse
import asyncio
import json
import time
from .node import Node, endpoint
from .rpc import METHODS, decode_payload


async def run(args):
    ids = [args.node] if args.usb_serial else [args.node, args.node+1]
    nodes = [Node(n) for n in ids]
    completed = 0
    uptimes = {}
    reference_params = None
    progress = getattr(args, "progress", None)
    if progress is None:
        progress = {}
    mode = getattr(args, "rpc_mode", "burst")
    progress.update(mode=mode, clients=ids, completed=0, calls=[], pass_=False)

    async def query(node, method, turn):
        started = time.monotonic()
        record = {"node": node.router.node, "method": method, "round": turn + 1}
        progress["calls"].append(record)
        try:
            payload = await node.rpc_request(method,
                ("N%d-R%d" % (node.router.node, turn)).encode() if method == "Ping" else b"")
            record.update(ok=True, elapsed_ms=round((time.monotonic() - started) * 1000, 3))
            return payload
        except asyncio.CancelledError:
            record.update(cancelled=True, elapsed_ms=round((time.monotonic() - started) * 1000, 3))
            raise
        except Exception as error:
            record.update(ok=False, error_type=type(error).__name__, error=str(error),
                          elapsed_ms=round((time.monotonic() - started) * 1000, 3))
            raise

    async def paced_peer(node, turn):
        # Explicit application-level admission control: two peers still run
        # concurrently, but each has at most one in-flight unary call. This is
        # NOT proof that the eight-call burst mode can sustain mixed traffic.
        replies = []
        for method in METHODS:
            replies.append(await query(node, method, turn))
            await asyncio.sleep(.1)
        return replies

    async def round_replies(coroutines):
        requests = [asyncio.create_task(coroutine) for coroutine in coroutines]
        try:
            return await asyncio.gather(*requests)
        finally:
            # A failed request must not leave siblings still transmitting after
            # the acceptance runner has begun its stop/close sequence.
            for request in requests:
                if not request.done():
                    request.cancel()
            await asyncio.gather(*requests, return_exceptions=True)
    try:
        for index, node in enumerate(nodes):
            # Explicit test-only sequence ranges: avoid a recently restarted
            # CLI's sequence=1 colliding with the existing 30-second cache.
            # This does not fix/generalize peer restart identity in the protocol.
            node.router.next_seq = 10000 + index*10000
            await node.start()
            if args.usb_serial:
                await node.attach_serial(args.usb_serial, usb=True)
            else:
                await node.connect(*args.tcp)
            await node.wait_route(1, 25)
        for turn in range(args.rounds):
            jobs = [(node, method) for node in nodes for method in METHODS]
            if mode == "paced":
                peer_replies = await round_replies(paced_peer(node, turn) for node in nodes)
                responses = [payload for replies in peer_replies for payload in replies]
            else:
                responses = await round_replies(query(node, method, turn) for node, method in jobs)
            for (node, method), payload in zip(jobs, responses):
                value = decode_payload(method, payload)
                if method == "Ping":
                    assert value == "N%d-R%d" % (node.router.node, turn), "reply mixed between clients"
                elif method == "GetStatus":
                    assert value["safety_latched"] == 1 and not value["foc_enabled"]
                    assert not value["fault"] and value["motor_mode_id"] == 0
                    assert not value["firmware_update_active"] and not value["can_motion_enabled"]
                    previous = uptimes.get(node.router.node, 0)
                    assert value["uptime_ms"] >= previous, "MCU reset during RPC load"
                    uptimes[node.router.node] = value["uptime_ms"]
                elif method == "GetParams":
                    if reference_params is None:
                        reference_params = payload
                    assert reference_params == payload, "read-only parameter snapshot changed"
                elif method == "GetDiagnostics":
                    assert value["can_rpc_fifo_overruns"] == 0
                completed += 1
                progress["completed"] = completed
            print("PASS round=%d peers=%s queries=%d" % (turn+1, ids, completed), flush=True)
            await asyncio.sleep(.35)
        summary = {"result": "PASS", "hardware": True, "clients": ids, "rpc_mode": mode,
            "transport": "USB VCP" if args.usb_serial else "PC-LubanCat-WiFi-ESP32-UART-STM32",
            "rpc_queries": completed, "uptimes_ms": uptimes, "parameters_unchanged_during_test": True,
            "motor_flash_reset_commands_sent": False}
        progress["pass_"] = True
        print(json.dumps(summary), flush=True)
        return summary
    finally:
        progress["node_stats"] = {str(node.router.node): dict(node.router.stats) for node in nodes}
        progress["connected_ports"] = {str(node.router.node): list(node.connections) for node in nodes}
        for node in nodes:
            await node.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tcp", type=endpoint)
    group.add_argument("--usb-serial")
    parser.add_argument("--node", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--rpc-mode", choices=("burst", "paced"), default="burst")
    args = parser.parse_args()
    if not 3 <= args.node < 65534 or not 1 <= args.rounds <= 20:
        parser.error("node=3..65533; rounds=1..20")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
