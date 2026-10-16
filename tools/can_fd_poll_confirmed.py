"""Wait for normal B trial confirmation; read-only UART, never force confirm."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.router_transfer_concurrency_live import Console


async def poll(args, evidence):
    console = Console(args.port, evidence)
    try:
        deadline = time.monotonic() + 80
        while time.monotonic() < deadline:
            try:
                fw = (await console.request("FW STATUS"))[0]
            except TimeoutError:
                continue
            if all(field in fw for field in ("CURRENT=B", "CONFIRMED=B", "PENDING=-", "ATTEMPTS=0", "ACTIVE=0")):
                safe = (await console.request("ANALOG SAFE STATUS"))[0]
                if "LATCHED=1 SD=0 MOE=0 FOC=0" not in safe:
                    raise RuntimeError("Trial confirmed but power-off safe latch failed")
                await console.request("STATUS")
                await console.request("BENCH STATUS")
                (evidence / "confirmed.json").write_text(json.dumps({"pass": True, "fw": fw,
                    "safe": safe, "forced_confirmation": False}, indent=2), encoding="utf-8")
                print("NORMAL B CONFIRMATION PASS: no force-confirm, SD=MOE=FOC=0", flush=True)
                return
            await asyncio.sleep(.5)
        raise RuntimeError("Normal B confirmation not proven; restore original A, no force-confirm")
    finally:
        console.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    if not evidence.is_relative_to((ROOT / "safety_backups").resolve()) or evidence.exists():
        parser.error("Fresh workspace safety_backups evidence directory required")
    evidence.mkdir(parents=True)
    asyncio.run(poll(args, evidence))
