"""Bounded ENC SAMPLE acceptance, only while ANALOG SAFE is already latched."""
import argparse
import json
import re
import time
from pathlib import Path

import serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--count", type=int, default=1000)
    args = parser.parse_args()
    if not 1 <= args.count <= 9000:
        parser.error("Sample count must be 1..9000")
    evidence = Path(args.evidence).resolve()
    root = Path(__file__).resolve().parents[1] / "safety_backups"
    if not evidence.is_relative_to(root.resolve()):
        parser.error("Evidence must be inside workspace safety_backups")
    evidence.mkdir(parents=True, exist_ok=True)
    result = {"reset_flash_motion": False, "samples": [], "replies": {}}
    connection = serial.Serial(port=None, baudrate=115200, timeout=.1, write_timeout=2)
    connection.dtr = connection.rts = False
    connection.port = args.port
    request_id = 48000

    def request(command, multiline=False):
        nonlocal request_id
        if command not in {"ANALOG SAFE STATUS", "FW STATUS", "STATUS", "ENC DIAG", "ENC SAMPLE"}:
            raise ValueError("Out-of-scope command")
        request_id += 1
        connection.write(f"{request_id} {command}\r\n".encode())
        replies = []
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            line = connection.readline().decode(errors="replace").strip()
            if line.startswith(f"{request_id} OK ") or line.startswith(f"{request_id} ERR "):
                replies.append(line)
                if not multiline or "ENC STACK" in line or " ERR " in line:
                    return replies
        raise TimeoutError(f"No complete reply to {command}: {replies}")

    def safe_check():
        reply = request("ANALOG SAFE STATUS")[0]
        if "LATCHED=1 SD=0 MOE=0 FOC=0" not in reply:
            raise RuntimeError(f"Not safely latched; no sample requested: {reply}")
        return reply

    try:
        connection.open()
        connection.reset_input_buffer()
        result["replies"]["safe_before"] = safe_check()
        result["replies"]["dma_before"] = request("ENC DIAG", True)
        for index in range(args.count):
            reply = request("ENC SAMPLE")[0]
            match = re.search(r"ENC SAMPLE HAL=0 RAW=(\d+) US=\d+ SAFE=1 SD=0 MOE=0 FOC=0", reply)
            result["samples"].append(reply)
            if not match or not 0 <= int(match[1]) <= 16383:
                raise RuntimeError(f"Sample failed: {reply}")
            if (index + 1) % 100 == 0:
                safe_check()
                print(f"PASS safe DMA single reads {index + 1}/{args.count}", flush=True)
        result["replies"]["dma_after"] = request("ENC DIAG", True)
        result["replies"]["safe_after"] = safe_check()
        result["replies"]["status_after"] = request("STATUS")
        result["replies"]["fw_after"] = request("FW STATUS")
        result["pass"] = True
        for name, replies in result["replies"].items():
            print(name, replies, flush=True)
    finally:
        connection.close()
        (evidence / "safe-dma-samples.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
