"""Build a source-only zipapp, excluding credentials, firmware and caches."""
from pathlib import Path
import argparse
import hashlib
import zipfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--rpc", action="store_true", help="create a separate RPC-enabled bridge bundle")
parser.add_argument("--transfer", action="store_true", help="create the generic binary Transfer bridge bundle")
args = parser.parse_args()
name = ("router-transfer-acceptance-20261006.zip" if args.transfer else
        "router-rpc-acceptance-20261005.zip" if args.rpc else "router-acceptance-20261005.zip")
destination = root / "router_network" / name
with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    entry = "from router_network.luban_acceptance import main\nmain()\n"
    if args.rpc or args.transfer:
        entry = "import sys\nsys.argv.append('--rpc')\n" + entry
    archive.writestr("__main__.py", entry)
    for name in ("__init__.py", "wire.py", "transfer_wire.py", "core.py", "node.py", "rpc.py", "luban_acceptance.py"):
        archive.write(root / "router_network" / name, "router_network/" + name)
print(str(destination))
print("SHA256=" + hashlib.sha256(destination.read_bytes()).hexdigest())
print("Source only; no credentials or hardware writes.")
