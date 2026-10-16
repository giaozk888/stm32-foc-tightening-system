"""SAFE-only RX-IRQ-loss test. Temporarily masks IRQ14, always restores it.

This does not prove a powered motor shutdown delay or simulate unplugging MISO.
No firmware, metadata, protection threshold, motion command or GPIO is written.
"""
import argparse
import json
import re
import subprocess
import time
from pathlib import Path

import serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--permit-irq-fault", action="store_true")
    args = parser.parse_args()
    if not args.permit_irq_fault:
        parser.error("Explicit controlled IRQ-loss test required")
    evidence = Path(args.evidence).resolve()
    root = Path(__file__).resolve().parents[1] / "safety_backups"
    if not evidence.is_relative_to(root.resolve()):
        parser.error("Evidence must be inside workspace safety_backups")
    evidence.mkdir(parents=True, exist_ok=True)
    result = {"motion_flash_reset": False, "programmer": [], "replies": {}}
    connection = serial.Serial(port=None, baudrate=115200, timeout=.1, write_timeout=2)
    connection.dtr = connection.rts = False
    connection.port = "COM5"
    request_id = 59000
    restore_required = False

    def programmer(*operations):
        completed = subprocess.run(
            [r"D:\software\cubeprogrammer\bin\STM32_Programmer_CLI.exe",
             "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", *operations],
            capture_output=True, text=True, timeout=20)
        output = completed.stdout + completed.stderr
        result["programmer"].append({"operations": operations,
                                     "returncode": completed.returncode, "output": output})
        if completed.returncode:
            raise RuntimeError(f"Programmer failed: {output}")
        return output

    def enabled_mask():
        output = programmer("-r32", "0xE000E100", "1")
        match = re.search(r"0xE000E100\s*:\s*([0-9A-Fa-f]{8})", output)
        if not match:
            raise RuntimeError("NVIC enable-mask readback unavailable")
        return int(match[1], 16)

    def request(command):
        nonlocal request_id
        if command not in {"ANALOG SAFE STATUS", "ENC DIAG", "ENC SAMPLE", "STATUS"}:
            raise ValueError("Out-of-scope command")
        request_id += 1
        connection.write(f"{request_id} {command}\r\n".encode())
        deadline = time.monotonic() + 5
        replies = []
        while time.monotonic() < deadline:
            line = connection.readline().decode(errors="replace").strip()
            if line.startswith(f"{request_id} OK ") or line.startswith(f"{request_id} ERR "):
                replies.append(line)
                print(line, flush=True)
                if command != "ENC DIAG" or "ENC STACK" in line or " ERR " in line:
                    return replies
        raise TimeoutError(f"Incomplete reply to {command}: {replies}")

    def stats(replies):
        line = next(line for line in replies if "ENC DMA " in line)
        return {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", line)}

    try:
        connection.open()
        connection.reset_input_buffer()
        safe = request("ANALOG SAFE STATUS")
        result["replies"]["safe_before"] = safe
        if "LATCHED=1 SD=0 MOE=0 FOC=0" not in safe[0]:
            raise RuntimeError("SAFE not proven; no injection performed")
        before = request("ENC DIAG")
        result["replies"]["diag_before"] = before
        before_stats = stats(before)
        if before_stats["ACTIVE"] or not enabled_mask() & 0x4000:
            raise RuntimeError("Driver not idle or IRQ14 not originally enabled")
        # NVIC ICER/ISER are write-one registers. Do not use read-modify-write
        # or generic memory-write verification; inspect ISER after each action.
        restore_required = True
        programmer("-w32", "0xE000E180", "0x00004000", "-nv")
        if enabled_mask() & 0x4000:
            raise RuntimeError("IRQ14 did not become masked")
        failed_sample = request("ENC SAMPLE")
        result["replies"]["injected_sample"] = failed_sample
        after = request("ENC DIAG")
        result["replies"]["diag_injected"] = after
        after_stats = stats(after)
        if "ENC SAMPLE HAL=1 " not in failed_sample[0] or after_stats["ST"] != 2:
            raise RuntimeError("Expected rejected sample and AS_DMA_TIMEOUT")
        if after_stats["FAIL"] != before_stats["FAIL"] + 1 or after_stats["TIMEOUT"] != before_stats["TIMEOUT"] + 1:
            raise RuntimeError("Expected exactly one failure/timeout")
        programmer("-w32", "0xE000E100", "0x00004000", "-nv")
        if not enabled_mask() & 0x4000:
            raise RuntimeError("IRQ14 restore not proven")
        restore_required = False
        recovered = request("ENC SAMPLE")
        result["replies"]["recovered_sample"] = recovered
        if "ENC SAMPLE HAL=0 " not in recovered[0]:
            raise RuntimeError("Normal sample did not recover")
        result["replies"]["diag_recovered"] = request("ENC DIAG")
        result["replies"]["safe_after"] = request("ANALOG SAFE STATUS")
        result["replies"]["status_after"] = request("STATUS")
        if "LATCHED=1 SD=0 MOE=0 FOC=0" not in result["replies"]["safe_after"][0]:
            raise RuntimeError("Final safe latch not proven")
        result["pass"] = True
        print("PASS: SAFE-only missing RX IRQ timed out and normal DMA read recovered", flush=True)
    finally:
        try:
            if restore_required:
                programmer("-w32", "0xE000E100", "0x00004000", "-nv")
                result["emergency_irq_restore"] = bool(enabled_mask() & 0x4000)
        finally:
            connection.close()
            (evidence / "safe-irq-loss.json").write_text(
                json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
