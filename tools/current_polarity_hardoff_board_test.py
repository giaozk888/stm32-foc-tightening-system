"""One staged B current-polarity hard-OFF trial; never sends START.

This is pinned to the 2026-10-18 full-Flash capture and B image. It does not
qualify current polarity for motor operation. Full captures stay in ignored tmp/.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import zlib

from firmware_transfer_iap import fields, image_info
from fast_current_reject_board_test import Console, healthy, sample
from latest_original_fsm_stage import full_compare_commands, off_commands, write_mailbox
from original_closed_loop_trial import emergency_off
from original_closed_loop_updated_stage import debug
from protected_irq_optimized_stage import open_port
from tighten_synthetic_swd_recovery import latest_meta

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "tmp"
BEFORE = TMP / "current-polarity-prewrite-20261018.bin"
STAGED = TMP / "current-polarity-staged-20261018.bin"
IMAGE = ROOT / "foc2_app_b/build/CurrentPolarityReview/ReverseHardOff/foc2.bin"
IMAGE_SHA = "1414d15686290feded880fea9cba30b62c8e3772585ac452dba9905ce4dfaff9"
BEFORE_SHA = "f7562227e89f3124341834e796af9a17a9cd4b3b38e03bfb0514046f062b0f32"
STAGED_SHA = "e17c1601b5f1b65f083cb80d368ced9ac03da0aecdaa1b374de3d77d8b095bdc"
BASE_META = (1112493908, 3, 1, 0, 0, 626, 229364, 3112785379,
             210916, 453748590, 0, 2945252698)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def preflight():
    before, staged, image = BEFORE.read_bytes(), STAGED.read_bytes(), IMAGE.read_bytes()
    if (len(before) != len(staged) or len(before) != 0x80000 or
            digest(before) != BEFORE_SHA or digest(staged) != STAGED_SHA or
            len(image) != 225100 or digest(image) != IMAGE_SHA or
            image_info(image)[0] != "B" or latest_meta(before) != BASE_META or
            latest_meta(staged) != BASE_META):
        raise ValueError("Pinned full-Flash baseline/candidate identity failed")
    end = (0x40000 + len(image) + 0x7ff) & ~0x7ff
    if (before[:0x40000] != staged[:0x40000] or before[end:] != staged[end:] or
            staged[0x40000:0x40000 + len(image)] != image or
            staged[0x40000 + len(image):end] != b"\xff" * (end - 0x40000 - len(image))):
        raise ValueError("Staged B/non-B Flash comparison failed")
    for marker in (b"NAME=FAST_CURRENT_REJECT HARD_OFF=1", b"METHOD=TWO_SAMPLE",
                   b"FILTER=NONE OC=RAW_CONFIRM_4"):
        if marker not in image:
            raise ValueError("Hard-OFF candidate marker missing")
    return image


def trial(row, image):
    live = TMP / "current-polarity-live-trial-20261018.bin"
    final = TMP / "current-polarity-final-20261018.bin"
    ram = TMP / "current-polarity-final-ram-20261018.bin"
    if any(p.exists() for p in (live, final, ram)):
        raise ValueError("One-shot evidence path already exists; no retry")
    body = struct.pack("<7I", 0x584f424d, 1, 2, 1, 2, len(image), zlib.crc32(image))
    words = struct.unpack("<8I", body + struct.pack("<I", zlib.crc32(body)))
    port = uart = None
    try:
        port = open_port()
        uart = Console(port)
        # No application instruction runs before the exact staged image check.
        commands = ["init", "halt", "if {[mrw 0xE000ED08] != 0} {error {Not bootloader}}",
            "mmw 0x4002104C 0x4 0", "mww 0x48000818 0x00400000",
            "mmw 0x48000800 0x1000 0x2000", "mww 0x40012C20 0",
            "mmw 0x40012C44 0 0xC000", "mmw 0x40012C00 0 1",
            "if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20]} {error {Output enabled}}",
            *full_compare_commands(live, STAGED), "reset halt", *off_commands(),
            *write_mailbox(words), "reset run", "shutdown"]
        row["hardware_attempted"] = True
        row["trial_requests"] = 1
        debug(row, commands)
        row["activation_submitted"] = True
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                fw = fields(uart.query("FW STATUS", 0.6))
            except TimeoutError:
                continue
            row["last_fw"] = fw
            if fw.get("CURRENT") == "A" and fw.get("PENDING") == "-":
                raise RuntimeError("B rejected/rolled back; no retry")
            if fw.get("CURRENT") != "B":
                continue
            if all(fw.get(k) == v for k, v in
                   (("CONFIRMED", "B"), ("PENDING", "-"), ("ATTEMPTS", "0"))):
                row["normally_confirmed"] = True
                break
        else:
            raise TimeoutError("B normal health confirmation absent")
        first = sample(uart)
        row["first"] = first
        healthy(first)
        end = time.monotonic() + 10
        while time.monotonic() < end:
            uart.poll(0.05)
        last = sample(uart)
        row["last"] = last
        healthy(last)
        if int(last["adc"].get("PAIRS", "0")) <= int(first["adc"].get("PAIRS", "0")):
            raise RuntimeError("ADC pair count did not advance")
        if (int(last["adc"].get("MISS", "0")) or
                int(last["adc"].get("LATE", "0")) or
                int(last["commit"].get("BOTTOM_LATE", "0")) or
                int(last["timing"].get("LATE", "0"))):
            raise RuntimeError("ADC/FOC or bottom-latch timing warning")
        row["pass_"] = True
    finally:
        try:
            if row.get("hardware_attempted"):
                if uart and row.get("activation_submitted"):
                    try:
                        row["off_ack"] = uart.query("ANALOG SAFE", 0.8)
                    except BaseException as exc:
                        row["off_ack_error"] = str(exc)
                emergency_off(row, final)
                captured = final.read_bytes()
                if (len(captured) != 0x80000 or captured[:0x7e800] != STAGED.read_bytes()[:0x7e800]
                        or captured[0x7f800:] != STAGED.read_bytes()[0x7f800:]):
                    raise RuntimeError("Non-metadata Flash changed after trial")
                row["final_meta"] = list(latest_meta(captured))
                row["final_sha256"] = digest(captured)
                debug(row, ["init", "halt", "if {([mrw 0xE000EDF0] & 0x20000) == 0} {error {CPU not halted}}",
                    f"dump_image {{{ram.as_posix()}}} 0x20000000 0x20000", "shutdown"])
                row["ram_capture"] = str(ram)
        finally:
            if uart:
                row["uart_tail"] = uart.lines[-100:]
                row["host_motor_commands"] = uart.starts
            if port and port.is_open:
                port.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument("--drive-12v-on-motor-disconnected-no-alarm", action="store_true")
    args = parser.parse_args()
    image = preflight()
    if not args.run_once:
        print("OFFLINE PASS: pinned staged hard-OFF B; no device operation")
        return 0
    if not args.drive_12v_on_motor_disconnected_no_alarm:
        parser.error("Actual powered drive, disconnected motor and no alarm required")
    row = dict(pass_=False, trial_requests=0, motor_commands=0, activation_submitted=False,
               image_sha256=IMAGE_SHA, steps=[], automatic_retry=False, forced_confirmation=False)
    try:
        trial(row, image)
    except BaseException as exc:
        row["pass_"] = False
        row["failure"] = str(exc)
    receipt = TMP / "current-polarity-hardoff-trial-20261018.json"
    if receipt.exists():
        raise RuntimeError("One-shot receipt already exists")
    receipt.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(("PASS" if row["pass_"] else "FAIL") + ": hard-OFF B one-shot; evidence " + str(receipt), flush=True)
    if row.get("failure"):
        print(row["failure"], flush=True)
    return 0 if row["pass_"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
