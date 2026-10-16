"""Read-only STM32 preflight. No reset/flash/motion commands or control-line toggles."""
import argparse
import json
import re
import time
from pathlib import Path
import serial

ALLOWED = {"PING", "FW STATUS", "STATUS", "ANALOG SAFE STATUS", "ENC DIAG"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "safety_backups"
    evidence = Path(args.evidence).resolve()
    if not evidence.is_relative_to(root.resolve()):
        parser.error("Evidence directory must be inside workspace safety_backups")
    evidence.mkdir(parents=True, exist_ok=True)
    output = {"port": args.port, "reset_flash_motion": False, "replies": {}}
    connection = serial.Serial(port=None, baudrate=115200, timeout=.1, write_timeout=2)
    connection.dtr = connection.rts = False
    connection.port = args.port
    try:
        connection.open()
        connection.reset_input_buffer()
        for request_id, command in enumerate(("PING", "FW STATUS", "ANALOG SAFE STATUS", "STATUS", "ENC DIAG"), 46001):
            if command not in ALLOWED:
                raise ValueError("Out-of-scope command")
            connection.write(f"{request_id} {command}\r\n".encode())
            deadline = time.monotonic() + 5
            replies = []
            while time.monotonic() < deadline:
                line = connection.readline().decode(errors="replace").strip()
                if re.match(rf"^{request_id} (OK|ERR) ", line):
                    replies.append(line)
                    print(line, flush=True)
                    if command != "ENC DIAG" or "ENC STACK" in line or " ERR " in line:
                        break
            output["replies"][command] = replies
            if not replies:
                raise TimeoutError(f"No reply to {command}; no mutation attempted")
    finally:
        connection.close()
        (evidence / "read-only-preflight.json").write_text(json.dumps(output, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
