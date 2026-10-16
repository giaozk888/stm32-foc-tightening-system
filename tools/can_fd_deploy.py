"""Guarded, source-only CAN FD communication deployment on the verified board.

Timeout restores the boot configuration but KEEPS CAN/HMI gated DOWN until the
operator restores the untouched STM32 A and runs release-classic. It cannot
roll back MCU firmware by itself. Never enable a mismatched classic peer.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import subprocess
import threading
import can_fd_overlay_trial as base
import can_fd_communication_setup as setup

ROOT = Path("/root/codex-canfd-communication-20261007")
base.ROOT = ROOT
base.UNIT_NAME = "codex-canfd-communication-guard-20261007.service"
base.UNIT = Path("/etc/systemd/system") / base.UNIT_NAME
base.DROP_NAME = "zzzzzzzzzzzz-codex-canfd-guard-20261007.conf"
base.DROPS = [Path("/etc/systemd/system") / (name + ".d") / base.DROP_NAME
              for name in ("lubancat-can0.service", "lubancat-hmi.service")]
base.MARKER = ROOT / "trial-active"
base.TIMEOUT = 1800
base.DROP_DATA = ("[Unit]\nConditionPathExists=!" + str(base.MARKER) + "\n").encode()
base.UNIT_DATA = ("[Unit]\nDescription=CAN FD deployment fail-closed guard\nAfter=local-fs.target\n"
                  "[Service]\nType=simple\nExecStart=/usr/bin/python3 " + str(ROOT / "controller.py") +
                  " watchdog\nTimeoutStopSec=5\n[Install]\nWantedBy=multi-user.target\n").encode()
SERVICES = ("lubancat-can0.service", "lubancat-hmi.service")
SETUP_FILE = Path("/usr/local/libexec/lubancat-canfd-setup.py")
NAME = "zzzzzzzzzz-canfd-communication-20261007.conf"
CAN_DROP = Path("/etc/systemd/system/lubancat-can0.service.d") / NAME
HMI_DROP = Path("/etc/systemd/system/lubancat-hmi.service.d") / NAME
SOURCE = Path("/home/cat/lubancat_hmi_canfd/lubancat_hmi/systemd")
BINARY = Path("/home/cat/lubancat_hmi_canfd/build-gcc10/lubancat_hmi")


def owned_files():
    return [(SETUP_FILE, (ROOT / "can_fd_communication_setup.py").read_bytes()),
            (CAN_DROP, (SOURCE / "can-fd.conf").read_bytes()),
            (HMI_DROP, (SOURCE / NAME).read_bytes())]


def stop_peers():
    base.run("systemctl", "stop", "lubancat-hmi.service", check=False)
    base.run("ip", "link", "set", "can0", "down", check=False)
    base.run("systemctl", "stop", "lubancat-can0.service", check=False)


def prepare():
    if Path(__file__).resolve() != ROOT / "controller.py":
        raise RuntimeError("Controller must be uploaded to its exact independent path")
    if not BINARY.is_file() or not os.access(BINARY, os.X_OK):
        raise RuntimeError("Linux HMI must be completely built before arming guard")
    for path, _ in owned_files():
        if path.exists() or path.is_symlink():
            raise RuntimeError("Never overwrite an existing deployment path: " + str(path))
    for service in SERVICES:
        base.atomic_write(ROOT / (service + ".original.txt"),
                          base.run("systemctl", "cat", service).stdout.encode())
    base.prepare()
    print("RECOVERY: on timeout boot restores classic but CAN/HMI stay gated; "
          "restore original MCU A before release-classic", flush=True)


def rollback(reboot):
    manifest = json.loads((ROOT / "manifest.json").read_text())
    original = (ROOT / "uEnv.original").read_bytes()
    if base.digest(original) != manifest["original_sha256"]:
        raise RuntimeError("Backup mismatch: preserve all files")
    if base.BOOT_LINK.resolve() != base.BOOT or base.digest(base.BOOT.read_bytes()) not in (
            manifest["trial_sha256"], manifest["original_sha256"]):
        raise RuntimeError("Boot configuration changed externally: preserve it")
    # Even a partially committed setup must fail closed, never start classic
    # while the MCU is still FD. Retain recovery marker/gates across reboot.
    for path in base.DROPS:
        if path.exists() and path.read_bytes() != base.DROP_DATA:
            raise RuntimeError("Guard modified externally")
        base.atomic_write(path, base.DROP_DATA, 0o644)
    base.atomic_write(base.MARKER, b"rollback-awaiting-classic-mcu\n")
    base.run("systemctl", "daemon-reload")
    stop_peers()
    for path, expected in owned_files():
        base.remove_owned(path, expected)
    base.atomic_write(base.BOOT, original, manifest["boot_mode"])
    base.run("systemctl", "disable", base.UNIT_NAME, check=False)
    base.record("rollback.json", {"boot_restored": True, "can_hmi_gated": True,
                "mcu_restore_required": True, "reboot": reboot})
    base.run("sync")
    print("ROLLBACK SAFE: original boot restored; CAN/HMI gated DOWN. "
          "Restore STM32 original A, then release-classic.", flush=True)
    if reboot:
        base.run("systemctl", "reboot")


def watchdog():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    if base.boot_id() == manifest["original_boot_id"] or not base.MARKER.exists():
        return
    deadline = time.monotonic() + base.TIMEOUT
    while base.MARKER.exists() and time.monotonic() < deadline:
        time.sleep(2)
    if base.MARKER.exists():
        rollback(True)


def ready():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    if base.boot_id() == manifest["original_boot_id"] or not base.MARKER.exists():
        raise RuntimeError("Not in guarded FD boot")
    for service in SERVICES:
        if base.run("systemctl", "is-active", service, check=False).stdout.strip() == "active":
            raise RuntimeError("Old application service unexpectedly active")
    report = setup.setup(True)
    base.record("fd-ready.json", report)
    print("FD READY: 500k/500k, BRS OFF; no application TX; HMI gated", flush=True)


def check_errors():
    interface = setup.inspect()
    if not setup.matches_profile(interface):
        raise RuntimeError("Live FD profile/state/error counters failed")
    if any(interface.get("stats64", {}).get(direction, {}).get("errors", 0)
           for direction in ("rx", "tx")):
        raise RuntimeError("Kernel RX/TX errors exist")
    if any(interface["linkinfo"].get("info_xstats", {}).get(name, 0)
           for name in ("bus_error", "error_warning", "error_passive", "bus_off")):
        raise RuntimeError("Kernel CAN error events exist")
    return interface


def echo():
    check_errors()
    reply = base.run("python3", str(ROOT / "can_fd_probe.py"),
                     "--permit-read-only-test", "--count", "20", check=False)
    try:
        report = json.loads(reply.stdout)
    except ValueError:
        stop_peers()
        raise RuntimeError("Echo probe output invalid: " + reply.stderr)
    base.record("echo20.json", report)
    if reply.returncode or not report.get("pass"):
        stop_peers()
        raise RuntimeError("Echo failed; CAN stopped: " + str(report.get("error")))
    check_errors()
    print("ECHO PASS: 20/20 64-byte exact responses, BRS OFF, max RTT ms=" +
          str(report["max_rtt_ms"]), flush=True)


def business():
    check_errors()
    output = ROOT / "business.txt"
    history = ROOT / "history.bin"
    if output.exists() or history.exists():
        raise RuntimeError("Do not overwrite previous business proof/history")
    command = [str(BINARY.parent / "can_fd_business_probe"),
               "--permit-read-only-test", str(history)]
    with output.open("x") as evidence:
        with subprocess.Popen(command, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL) as process:
            timer = threading.Timer(270, process.kill)
            timer.daemon = True
            timer.start()
            try:
                for line in process.stdout:
                    evidence.write(line)
                    evidence.flush()
                    print(line, end="", flush=True)
                code = process.wait()
            finally:
                timer.cancel()
    if code:
        stop_peers()
        raise RuntimeError("Business test failed; CAN stopped, proof retained")
    check_errors()
    base.record("business-interface.json", check_errors())


def commit():
    if not base.MARKER.exists():
        raise RuntimeError("Guard not active")
    echo = json.loads((ROOT / "echo20.json").read_text())
    business = (ROOT / "business.txt").read_text()
    if not (echo.get("pass") and echo.get("echoes") == 20 and not echo.get("brs") and
            "BUSINESS PASS FD=1 BRS=0 RPC=4 TRANSFER_READ_RESOURCE=3" in business):
        raise RuntimeError("Both 64-byte echo and official business acceptance required")
    before = check_errors()
    # Abort before any write if another administrator installed an override.
    files = owned_files()
    for path, _ in files:
        if path.exists() or path.is_symlink():
            raise RuntimeError("Deployment file already exists: " + str(path))
    try:
        for path, data in files:
            base.atomic_write(path, data, 0o644)
        for path in base.DROPS:
            base.remove_owned(path, base.DROP_DATA)
        base.MARKER.unlink()
        base.run("systemctl", "daemon-reload")
        effective = base.run("systemctl", "show", "lubancat-hmi.service", "-p", "ExecStart").stdout
        if str(BINARY) + " --can-fd" not in effective:
            raise RuntimeError("HMI ExecStart override did not win; no UI start")
        base.run("systemctl", "restart", "lubancat-can0.service")
        base.run("systemctl", "start", "lubancat-hmi.service")
        after = check_errors()
        for service in SERVICES:
            base.run("systemctl", "is-active", service)
        base.run("systemctl", "disable", "--now", base.UNIT_NAME)
        base.remove_owned(base.UNIT, base.UNIT_DATA)
        base.run("systemctl", "daemon-reload")
        base.record("commit.json", {"pass": True, "before": before, "after": after,
                    "hmi_execstart": effective, "guard_removed": True,
                    "profile": "FD 500k no BRS", "control_locked": True})
        print("COMMIT PASS: FD CAN service + paired HMI persistent; "
              "old firmware A/services/backups retained; no motion TX", flush=True)
    except Exception:
        rollback(False)
        raise


def release_classic(permit):
    manifest = json.loads((ROOT / "manifest.json").read_text())
    if not permit or base.digest(base.BOOT.read_bytes()) != manifest["original_sha256"]:
        raise RuntimeError("Require explicit original MCU A confirmation and restored boot")
    if setup.compatible() == setup.EXPECTED_COMPATIBLE:
        raise RuntimeError("Reboot to original classic overlay before releasing services")
    for path, expected in owned_files():
        base.remove_owned(path, expected)
    for path in base.DROPS:
        base.remove_owned(path, base.DROP_DATA)
    if base.MARKER.exists():
        base.MARKER.unlink()
    base.run("systemctl", "disable", "--now", base.UNIT_NAME, check=False)
    base.remove_owned(base.UNIT, base.UNIT_DATA)
    base.run("systemctl", "daemon-reload")
    for service in SERVICES:
        base.run("systemctl", "start", service)
    print("CLASSIC SERVICES RELEASED: verify passive telemetry next", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "ready", "echo", "business", "commit", "rollback", "watchdog", "release-classic", "verify-classic"])
    parser.add_argument("--reboot", action="store_true")
    parser.add_argument("--original-mcu-a-confirmed", action="store_true")
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0:
        parser.error("Run only on the explicitly approved LubanCat as root")
    if args.reboot and args.command != "rollback":
        parser.error("Only rollback accepts --reboot")
    {"prepare": prepare, "ready": ready, "echo": echo, "business": business,
     "commit": commit, "watchdog": watchdog,
     "rollback": lambda: rollback(args.reboot),
     "release-classic": lambda: release_classic(args.original_mcu_a_confirmed),
     "verify-classic": base.verify_restored}[args.command]()


if __name__ == "__main__":
    main()
