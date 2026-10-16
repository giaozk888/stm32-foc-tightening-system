"""Read-only Router/Pigweed unary client. Does not reset, flash, or control motors."""
import argparse
import asyncio
import json
from .node import Node, endpoint
from .rpc import METHODS, decode_payload


def client_node(value):
    number = int(value)
    if not 3 <= number < 65535:
        raise argparse.ArgumentTypeError("client node must be 3..65534")
    return number


async def run(args):
    node = Node(args.node)
    try:
        await node.start()
        if args.tcp:
            await node.connect(*args.tcp)
        else:
            await node.attach_serial(args.usb_serial, usb=True)
        await node.wait_route(1, timeout=25)
        for method in METHODS:
            payload = await node.rpc_request(method)
            print(json.dumps({"node": 1, "method": method,
                              "value": decode_payload(method, payload)}), flush=True)
        print("READ_ONLY ROUTER RPC PASS: 4 real unary replies; no writes", flush=True)
    finally:
        await node.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tcp", type=endpoint)
    group.add_argument("--usb-serial")
    parser.add_argument("--node", type=client_node, metavar="3..65534", default=4)
    try:
        asyncio.run(run(parser.parse_args()))
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, ValueError, asyncio.TimeoutError) as error:
        parser.exit(2, "ROUTER RPC NOT READY: " + str(error) + "\n")


if __name__ == "__main__":
    main()
