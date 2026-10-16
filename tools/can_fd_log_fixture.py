"""Emit four RAM-only test logs; never write parameters or enable power."""
import argparse
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.router_transfer_concurrency_live import Console, ALLOWED


async def emit(evidence):
    console = Console("COM5", evidence)
    try:
        safe = (await console.request("ANALOG SAFE STATUS"))[0]
        if "LATCHED=1 SD=0 MOE=0 FOC=0" not in safe:
            raise RuntimeError("Power-off latch not proven; refuse fixture")
        ALLOWED.add("LOG TEST 4")  # Exact RAM logging fixture, no generic shell/control entry.
        reply = (await console.request("LOG TEST 4"))[0]
        if "REQUESTED=4 ACCEPTED=4 NOT_ENQUEUED=0" not in reply:
            raise RuntimeError("Four test logs not accepted")
    finally:
        console.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    if not evidence.is_relative_to((ROOT / "safety_backups").resolve()) or evidence.exists():
        parser.error("Fresh workspace evidence directory required")
    evidence.mkdir(parents=True)
    asyncio.run(emit(evidence))
