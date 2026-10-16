"""One authorized reset of exact locked A, followed by one bounded zero test.

Never activates staged B, commits an upgrade, writes Flash, clears a motor
fault, or unlocks outputs. All image/metadata captures exclude private KVS.
The 4 A normal B is retained but not executed: it does not change zero gates.
"""
import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
import time
from pathlib import Path

from zero_retest_deploy import CLI, SN, DiagnosticUart, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers
from zero_injected_control_acceptance import (
    ROOT, PINNED, PATH_ADDRESSES, require_injected_registers, require_fresh_owner,
)
from zero_injected_control_sample import require_handover
from zero_async_clock_sample import main as sample_main
from phase_current_4a_stage import target_image, require_staged

OUTPUT = ROOT / "safety_backups/zero-injected-recalibrate-20261012"
HANDOVER = ROOT / "safety_backups/zero-injected-control-off-20261012/deployment-1791779559226027600.json"


def metadata(data):
    import zlib
    if len(data) != 4096:
        raise RuntimeError("Two complete metadata pages required")
    valid = []
    for offset in (0, 2048):
        w = struct.unpack_from("<12I", data, offset)
        if w[:2] == (0x424F4F54, 3) and w[-1] == zlib.crc32(data[offset:offset + 44]):
            valid.append(w)
    if not valid:
        raise RuntimeError("Missing valid boot metadata")
    w = max(valid, key=lambda v: v[5])
    if w[2:6] != (1, 0, 0, 405):
        raise RuntimeError("Only confirmed A without trial at generation 405 admitted")
    return w


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("--allow-reset-and-one-sample", "--motor-leads-disconnected",
                 "--supply-12v-0p5a-no-alarm"):
        parser.add_argument(flag, action="store_true")
    args = parser.parse_args()
    if not all(vars(args).values()):
        parser.error("One-reset/one-sample authorization and current physical conditions required")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    run_id = str(time.time_ns())
    record = {"reset_commands": 0, "flash_write": False, "activation": False,
              "motion_commands": False, "zero_gates_changed": False,
              "four_amp_threshold_used_for_zero": False, "steps": [], "pass": False}
    port = None

    def cli(*op):
        if op != ("-rst",) and op[0] not in ("-u", "-r32"):
            raise ValueError("Reset or read-only SWD only")
        proc = subprocess.run([CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000",
                               "sn=" + SN, *map(str, op)], capture_output=True,
                              text=True, errors="replace", timeout=30)
        out = proc.stdout + proc.stderr
        record["steps"].append({"args": list(map(str, op)), "code": proc.returncode,
                                "output": out})
        if proc.returncode or "Error:" in out:
            raise RuntimeError("SWD operation failed; no automatic retry")
        return out

    def capture(label, address, size):
        path = OUTPUT / f"{run_id}-{label}.bin"
        cli("-u", hex(address), hex(size), path)
        data = path.read_bytes()
        if len(data) != size:
            raise RuntimeError("Incomplete public image/metadata capture")
        return data

    def hardware():
        def read(addresses):
            op = tuple(v for a in addresses for v in ("-r32", hex(a), "4"))
            return cli(*op)
        return {"outputs": require_registers(read(ADDRESSES), "A"),
                "adc": require_injected_registers(read(PATH_ADDRESSES))}

    def open_uart():
        import serial
        p = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=1)
        p.dtr = p.rts = False
        p.port = "COM5"
        p.open()
        return p, DiagnosticUart(p)

    try:
        require_handover(json.loads(HANDOVER.read_text(encoding="utf-8")))
        _, expected_b = target_image()
        expected_a = (ROOT / "foc2_app_a/build/ZeroInjectedControlOff20261012/foc2.bin").read_bytes()
        before_a = capture("before-A", 0x08008000, len(expected_a))
        before_b = capture("before-B", 0x08040000, len(expected_b))
        before_meta = capture("before-metadata", 0x0807E800, 4096)
        meta = metadata(before_meta)
        if before_a != expected_a or hashlib.sha256(before_a).hexdigest() != PINNED["A"]:
            raise RuntimeError("Exact hard-locked A required before reset")
        if before_b != expected_b:
            raise RuntimeError("Staged 4 A B identity changed; stop")
        import zlib
        if meta[6:8] != (len(before_a), zlib.crc32(before_a)):
            raise RuntimeError("Confirmed A CRC/size mismatch")
        record["before_hardware"] = hardware()
        # Four-byte reads have one word per line in CubeProgrammer; a 32-byte
        # request prints several words per line, which must not be silently
        # treated as missing mailbox data.
        mailbox = cli(*(v for a in range(0x2001FFC0, 0x2001FFE0, 4)
                        for v in ("-r32", hex(a), "4")))
        words = re.findall(r"(?im)^0x([0-9A-F]+)\s*:\s*([0-9A-F]{8})\s*$", mailbox)
        regs = {int(a, 16): int(v, 16) for a, v in words}
        if len(regs) != 8 or regs.get(0x2001FFC0) != 0:
            raise RuntimeError("Mailbox must have no valid boot request; do not reset")
        port, uart = open_uart()
        record["before_fw"] = require_staged(uart.query("FW STATUS", 3), 405, expected_b)
        record["before_zero"] = require_service(uart.query("ZERO STATUS", 3))
        port.close()
        port = None
        record["reset_commands"] = 1
        cli("-rst")
        port, uart = open_uart()
        deadline = time.monotonic() + 45
        while True:
            try:
                fw = uart.query("FW STATUS", .8)
                break
            except TimeoutError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("No A console after one reset; do not retry reset")
                time.sleep(.2)
        record["after_reset_fw"] = require_confirmed(fw, "A")
        if record["after_reset_fw"]["GEN"] != "405":
            raise RuntimeError("Boot metadata changed; no sample")
        record["fresh_zero"] = require_fresh_owner(uart.query("ZERO STATUS", 3))
        port.close()
        port = None
        record["fresh_hardware"] = hardware()
        print("RESET CHECK PASS: fresh exact locked A; staged B not activated", flush=True)
        old_argv = sys.argv
        sys.argv = [old_argv[0], "--deployment-evidence", str(HANDOVER),
                    "--allow-zero-sample", "--motor-leads-disconnected",
                    "--supply-12v-0p5a-no-alarm"]
        try:
            sample_main(handover_checker=require_handover, image_hashes=PINNED,
                        output_dir=OUTPUT, clock_addresses=PATH_ADDRESSES,
                        clock_checker=require_injected_registers,
                        fresh_checker=require_fresh_owner, sample_label="INJECTED ZERO RETEST")
        finally:
            sys.argv = old_argv
        after_a = capture("after-A", 0x08008000, len(expected_a))
        after_b = capture("after-B", 0x08040000, len(expected_b))
        after_meta = capture("after-metadata", 0x0807E800, 4096)
        if (before_a, before_b, before_meta) != (after_a, after_b, after_meta):
            raise RuntimeError("Public APP/metadata changed during reset/sample")
        record["images_and_metadata_unchanged"] = True
        record["pass"] = True  # Orchestration only, not zero qualification.
    except BaseException as error:
        record["failure"] = str(error)
        raise
    finally:
        if port is not None:
            port.close()
        target = OUTPUT / f"recalibrate-{run_id}.json"
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Reset/orchestration evidence: " + str(target), flush=True)


if __name__ == "__main__":
    main()
