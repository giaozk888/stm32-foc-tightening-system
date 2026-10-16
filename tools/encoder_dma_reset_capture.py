"""Authorized reset capture; no flash or motion commands, then latch ANALOG SAFE."""
import argparse
import json
import subprocess
import time
from pathlib import Path

import serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--permit-reset", action="store_true")
    parser.add_argument("--capture-seconds", type=int, default=15)
    args = parser.parse_args()
    if not args.permit_reset:
        parser.error("Explicit reset permission required")
    if not 5 <= args.capture_seconds <= 45:
        parser.error("Capture duration must be 5..45 seconds")
    evidence = Path(args.evidence).resolve()
    root = Path(__file__).resolve().parents[1] / "safety_backups"
    if not evidence.is_relative_to(root.resolve()):
        parser.error("Evidence must be inside workspace safety_backups")
    evidence.mkdir(parents=True, exist_ok=True)
    result = {"reset": True, "flash": False, "motion": False, "startup": [], "replies": {}}
    connection = serial.Serial(port=None, baudrate=115200, timeout=.1, write_timeout=2)
    connection.dtr = connection.rts = False
    connection.port = args.port
    try:
        connection.open()
        connection.reset_input_buffer()
        reset = subprocess.run(
            [r"D:\software\cubeprogrammer\bin\STM32_Programmer_CLI.exe",
             "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "-rst"],
            capture_output=True, text=True, timeout=20)
        result["programmer"] = {"returncode": reset.returncode,
                                "output": reset.stdout + reset.stderr}
        print(result["programmer"]["output"], flush=True)
        if reset.returncode:
            raise RuntimeError("Reset failed")
        deadline = time.monotonic() + args.capture_seconds
        while time.monotonic() < deadline:
            line = connection.readline().decode(errors="replace").strip()
            if line:
                result["startup"].append(line)
                print(line, flush=True)
        for request_id, command in enumerate(
                ("PING", "ANALOG SAFE", "ANALOG SAFE STATUS", "FW STATUS", "STATUS", "ENC DIAG"), 47001):
            connection.write(f"{request_id} {command}\r\n".encode())
            deadline = time.monotonic() + 5
            replies = []
            while time.monotonic() < deadline:
                line = connection.readline().decode(errors="replace").strip()
                if line:
                    print(line, flush=True)
                if line.startswith(f"{request_id} OK ") or line.startswith(f"{request_id} ERR "):
                    replies.append(line)
                    if command != "ENC DIAG" or "ENC STACK" in line or " ERR " in line:
                        result["replies"][command] = replies if command == "ENC DIAG" else line
                        break
            else:
                raise TimeoutError(f"No reply: {command}")
        if "LATCHED=1 SD=0 MOE=0 FOC=0" not in result["replies"]["ANALOG SAFE STATUS"]:
            raise RuntimeError("Safe latch not proven")
    finally:
        connection.close()
        (evidence / "reset-capture.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
