"""Read-only local console snapshot for the isolated CAN FD acceptance."""
import argparse
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.router_transfer_concurrency_live import Console


async def snapshot(port, evidence):
    console = Console(port, evidence)
    try:
        for command in ("PING", "FW STATUS", "STATUS", "ANALOG SAFE STATUS", "BENCH STATUS"):
            await console.request(command)
    finally:
        console.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    if not evidence.is_relative_to((ROOT / "safety_backups").resolve()):
        parser.error("Evidence must stay under the workspace safety_backups")
    if (evidence / "console.json").exists():
        parser.error("Use a new evidence directory; do not overwrite old snapshots")
    evidence.mkdir(parents=True, exist_ok=True)
    asyncio.run(snapshot(args.port, evidence))
