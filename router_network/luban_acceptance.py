"""Foreground, read-only LubanCat acceptance bridge. No credentials or service changes."""
from __future__ import annotations
import argparse
import asyncio
import glob
import ipaddress
import json
import subprocess
from pathlib import Path
from .node import Node
from . import rpc

ESP_MAC = "b8:1f:3f:c4:56:28"
AP_NET = ipaddress.ip_network("192.168.50.0/24")


def peer_address():
    candidates = set()
    paths = glob.glob("/var/lib/NetworkManager/*lease*")
    paths += glob.glob("/var/lib/misc/*lease*")
    for path in paths:
        try:
            for line in Path(path).read_text().splitlines():
                fields = line.split()
                if len(fields) >= 3 and fields[1].lower() == ESP_MAC:
                    candidates.add(fields[2])
        except (OSError, UnicodeError):
            pass
    try:
        neighbors = json.loads(subprocess.check_output(
            ["ip", "-j", "-4", "neigh", "show"], timeout=3))
        candidates.update(n["dst"] for n in neighbors
                          if n.get("lladdr", "").lower() == ESP_MAC)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    valid = []
    for candidate in candidates:
        try:
            address = ipaddress.ip_address(candidate)
            if address in AP_NET and str(address) != "192.168.50.1":
                valid.append(str(address))
        except ValueError:
            pass
    if len(valid) != 1:
        raise RuntimeError("ESP address not unique in hotspot leases; use --esp <actual IP>")
    return valid[0]


async def serve(args):
    addresses = json.loads(subprocess.check_output(["ip", "-j", "-4", "addr"], timeout=3))
    local = {a["local"] for interface in addresses for a in interface.get("addr_info", [])}
    if args.listen not in local or args.listen != "192.168.137.10":
        raise ValueError("Expected existing private wired address 192.168.137.10; network not modified")
    esp = args.esp or peer_address()
    if ipaddress.ip_address(esp) not in AP_NET or esp == "192.168.50.1":
        raise ValueError("ESP must be an existing hotspot client in 192.168.50.0/24")
    node = Node(3)
    await node.start()
    try:
        await node.listen(args.listen, 21000)
        node._spawn(node.connect_forever(esp, 21000))
        print("READ_ONLY bridge node=3; listener=" + args.listen + ":21000; ESP=" + esp,
              flush=True)
        print("No passwords, firewall changes, cloud changes, Flash or motor commands.", flush=True)
        for target in (2, 1):
            await node.wait_route(target, 30)
            for status in (False, True):
                frame = await node.request(target, status, timeout=5)
                print(json.dumps({"source": frame.src, "reply": frame.payload}), flush=True)
        print("LUBAN BRIDGE PASS: nodes 1/2 reached; keep this window open for PC acceptance.",
              flush=True)
        if args.rpc:
            for method in rpc.METHODS:
                payload = await node.rpc_request(method)
                print(json.dumps({"rpc_method": method, "value": rpc.decode_payload(method, payload)}), flush=True)
            print("LUBAN RPC BRIDGE PASS: four read-only unary replies from STM32.", flush=True)
        await asyncio.Event().wait()
    finally:
        await node.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", default="192.168.137.10")
    parser.add_argument("--esp", help="Actual ESP hotspot DHCP address; no network scan")
    parser.add_argument("--rpc", action="store_true", help="also verify four read-only Router RPC methods")
    args = parser.parse_args()
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, ValueError, asyncio.TimeoutError) as error:
        parser.exit(2, "BRIDGE NOT READY: " + str(error) + "\n")


if __name__ == "__main__":
    main()
