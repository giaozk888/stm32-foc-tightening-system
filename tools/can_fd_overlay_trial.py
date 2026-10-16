"""One bounded LubanCat stock-overlay experiment; never send CAN frames.

Upload only this script to the exact ROOT/controller.py path. Commands are
prepare, probe, restore [--reboot], watchdog. Root/serial recovery is required.
The watchdog counts elapsed time, not the board's possibly unset wall clock.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


WIRE_ROOT = Path("/root/codex-canfd-wire-test-20261006")
WIRE_TRIAL = Path(__file__).resolve().parent == WIRE_ROOT
ROOT = WIRE_ROOT if WIRE_TRIAL else Path("/root/codex-canfd-overlay-test-20261006")
# This board's verified stock symlink must remain intact. Edit its exact target,
# never replace uEnv.txt with a regular file or resolve an arbitrary user path.
BOOT_LINK = Path("/boot/uEnv/uEnv.txt")
BOOT = Path("/boot/uEnv/uEnvLubanCat2H.txt")
CLASSIC = b"dtoverlay=/dtb/overlay/rk3568-lubancat-can1-m0-overlay.dtbo"
FD = b"dtoverlay=/dtb/overlay/rk3568-lubancat-canfd1-m0-overlay.dtbo"
UNIT_NAME = ("codex-canfd-wire-rollback-20261006.service" if WIRE_TRIAL
             else "codex-canfd-rollback-20261006.service")
UNIT = Path("/etc/systemd/system") / UNIT_NAME
DROP_NAME = ("zzzzzzzz-codex-fd-wire-trial-20261006.conf" if WIRE_TRIAL
             else "zzzzzzzz-codex-fd-trial-20261006.conf")
DROPS = [Path("/etc/systemd/system") / (name + ".d") / DROP_NAME
         for name in ("lubancat-can0.service", "lubancat-hmi.service")]
MARKER = ROOT / "trial-active"
TIMEOUT = 900 if WIRE_TRIAL else 300
DROP_DATA = ("[Unit]\nConditionPathExists=!" + str(MARKER) + "\n").encode()
UNIT_DATA = ("[Unit]\nDescription=Bounded stock CAN FD overlay trial rollback\n"
             "After=local-fs.target\n[Service]\nType=simple\nExecStart=/usr/bin/python3 "
             + str(ROOT / "controller.py") + " watchdog\nTimeoutStopSec=5\n"
             "[Install]\nWantedBy=multi-user.target\n").encode()


def run(*args, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check,
                          timeout=20)


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data, mode=0o600):
    if path.is_symlink():
        raise RuntimeError("Refusing symlink target: " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".canfd-trial-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
        parent_fd = os.open(str(path.parent), os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def record(name, value):
    atomic_write(ROOT / name, (json.dumps(value, indent=2) + "\n").encode())


def inspect():
    return json.loads(run("ip", "-j", "-details", "-statistics", "link", "show",
                          "can0").stdout)[0]


def candidate(data):
    # Exact active line only; preserve all unrelated overlays/boot arguments.
    lines = data.splitlines(keepends=True)
    if sum(line.rstrip(b"\r\n") == CLASSIC for line in lines) != 1:
        raise RuntimeError("Expected exactly one active classic can1-m0 line")
    if any(line.startswith(b"dtoverlay=") and b"canfd1-" in line for line in lines):
        raise RuntimeError("A CAN FD overlay is already active")
    return b"".join(line.replace(CLASSIC, FD, 1)
                    if line.rstrip(b"\r\n") == CLASSIC else line for line in lines)


def prepare():
    if (ROOT / "manifest.json").exists():
        raise RuntimeError("Existing trial manifest: do not overwrite backup")
    if any(path.exists() or path.is_symlink() for path in [UNIT] + DROPS):
        raise RuntimeError("Trial service/drop-in already exists")
    if BOOT_LINK.resolve() != BOOT:
        raise RuntimeError("Unexpected boot configuration symlink target")
    if BOOT.is_symlink() or not BOOT.is_file():
        raise RuntimeError("Boot configuration must be a regular file")
    if not Path("/boot/dtb/overlay/rk3568-lubancat-canfd1-m0-overlay.dtbo").is_file():
        raise RuntimeError("Stock FD overlay not installed")
    if not (ROOT / "controller.py").is_file():
        raise RuntimeError("Recovery script not uploaded to its required path")
    before = inspect()
    info = before["linkinfo"]["info_data"]
    if before["mtu"] != 16 or info["bittiming"]["bitrate"] != 500000:
        raise RuntimeError("Unexpected classic CAN baseline")
    services = {}
    for name in ("lubancat-can0.service", "lubancat-hmi.service"):
        services[name] = run("systemctl", "show", name, "-p", "UnitFileState",
                             "-p", "ActiveState").stdout
        if "UnitFileState=enabled" not in services[name]:
            raise RuntimeError("Unexpected service enablement; stop for review")
    data = BOOT.read_bytes()
    changed = candidate(data)
    shutil.copy2(BOOT, ROOT / "uEnv.original")
    atomic_write(ROOT / "uEnv.trial", changed, BOOT.stat().st_mode & 0o777)
    manifest = {"original_boot_id": boot_id(), "boot_target": str(BOOT),
                "original_sha256": digest(data),
                "trial_sha256": digest(changed), "boot_mode": BOOT.stat().st_mode & 0o777,
                "services": services, "before": before, "timeout_seconds": TIMEOUT}
    record("manifest.json", manifest)
    try:
        for path in DROPS:
            atomic_write(path, DROP_DATA, 0o644)
        atomic_write(UNIT, UNIT_DATA, 0o644)
        atomic_write(MARKER, b"active\n")
        run("systemctl", "daemon-reload")
        run("systemctl", "enable", UNIT_NAME)
        # Enable watchdog for the next boot, but do not start it in this boot.
        atomic_write(BOOT, changed, manifest["boot_mode"])
        run("sync")
    except Exception:
        restore(False)
        raise
    print("PREPARE PASS: exact boot backup; stock FD overlay; CAN/HMI gated; "
          + str(TIMEOUT) + "-second next-boot rollback; no CAN frames sent", flush=True)


def probe():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    if boot_id() == manifest["original_boot_id"] or not MARKER.exists():
        raise RuntimeError("Not in the temporary trial boot")
    before = inspect()
    if "UP" in before.get("flags", []):
        raise RuntimeError("Trial CAN unexpectedly UP: do not configure or transmit")
    node = Path("/sys/firmware/devicetree/base/can@fe580000/compatible")
    compatible = node.read_bytes().rstrip(b"\0").decode()
    if compatible != "rockchip,canfd-1.0":
        raise RuntimeError("Stock FD overlay did not select expected compatible")
    results = []
    for data_rate in (500000, 2000000):
        reply = run("ip", "link", "set", "can0", "type", "can", "bitrate", "500000",
                    "dbitrate", str(data_rate), "fd", "on", check=False)
        results.append({"nominal": 500000, "data": data_rate,
                        "exit_code": reply.returncode,
                        "message": (reply.stdout + reply.stderr).strip(),
                        "interface": inspect()})
    report = {"boot_id": boot_id(), "compatible": compatible, "before": before,
              "attempts": results, "after": inspect(), "no_frames_sent": True,
              "fd_capability_enabled": any(item["exit_code"] == 0 and
                  item["interface"]["mtu"] == 72 for item in results)}
    record("probe.json", report)
    print(json.dumps(report, indent=2), flush=True)


def remove_owned(path, expected):
    if path.is_symlink():
        raise RuntimeError("Unexpected symlink: " + str(path))
    if path.exists():
        if path.read_bytes() != expected:
            raise RuntimeError("Trial file edited externally; preserve it: " + str(path))
        path.unlink()


def restore(reboot):
    manifest = json.loads((ROOT / "manifest.json").read_text())
    original = (ROOT / "uEnv.original").read_bytes()
    if digest(original) != manifest["original_sha256"]:
        raise RuntimeError("Backup checksum mismatch; no restore performed")
    if digest(BOOT.read_bytes()) not in (manifest["trial_sha256"], manifest["original_sha256"]):
        raise RuntimeError("Boot file edited externally; do not overwrite user changes")
    if BOOT_LINK.resolve() != BOOT:
        raise RuntimeError("Boot symlink edited externally; do not overwrite user changes")
    atomic_write(BOOT, original, manifest["boot_mode"])
    run("sync")
    for path in DROPS:
        remove_owned(path, DROP_DATA)
    run("systemctl", "disable", UNIT_NAME)
    remove_owned(UNIT, UNIT_DATA)
    if MARKER.exists():
        MARKER.unlink()
    record("restore.json", {"original_boot_config_restored": True,
                             "boot_sha256": digest(BOOT.read_bytes()),
                             "boot_id": boot_id(), "reboot_requested": reboot})
    print("RESTORE PASS: exact original boot configuration restored; "
          "only trial gating/watchdog files removed; backups retained", flush=True)
    # Avoid starting the original services until the original DT is running.
    if reboot:
        run("sync")
        run("systemctl", "reboot")


def watchdog():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    if boot_id() == manifest["original_boot_id"] or not MARKER.exists():
        return
    print("Trial rollback armed: " + str(TIMEOUT)
          + " elapsed seconds, independent of wall clock", flush=True)
    deadline = time.monotonic() + TIMEOUT
    while MARKER.exists() and time.monotonic() < deadline:
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    if MARKER.exists():
        restore(True)


def wire_test(count, permit):
    if not WIRE_TRIAL or not permit or count not in (1, 4, 20):
        raise RuntimeError("Explicit isolated two-node traffic approval required")
    manifest = json.loads((ROOT / "manifest.json").read_text())
    if boot_id() == manifest["original_boot_id"] or not MARKER.exists():
        raise RuntimeError("Not in temporary FD trial boot")
    interface = inspect()
    already_up = "UP" in interface["flags"]
    if already_up:
        info = interface["linkinfo"]["info_data"]
        if (interface["mtu"] != 72 or "FD" not in info.get("ctrlmode", []) or
                info.get("bittiming", {}).get("bitrate") != 500000 or
                info.get("data_bittiming", {}).get("bitrate") != 500000):
            raise RuntimeError("Unexpected live interface profile; no frame sent")
    compatible = Path("/sys/firmware/devicetree/base/can@fe580000/compatible").read_bytes()
    if compatible.rstrip(b"\0") != b"rockchip,canfd-1.0":
        raise RuntimeError("FD device tree not running")
    result = {"count_requested": count, "pass": False}
    try:
        if not already_up:
            run("ip", "link", "set", "can0", "type", "can", "bitrate", "500000",
                "dbitrate", "500000", "fd", "on", "restart-ms", "0")
            run("ip", "link", "set", "can0", "up")
        result["before"] = inspect()
        # Count one is first-stage proof, NOT authorization for a longer flood.
        reply = run("python3", str(ROOT / "probe.py"), "--interface", "can0",
                    "--permit-read-only-test", "--count", str(count), check=False)
        result["exit_code"] = reply.returncode
        result["stdout"] = reply.stdout
        result["stderr"] = reply.stderr
        result["after"] = inspect()
        result["pass"] = reply.returncode == 0
    finally:
        # Stop queued retransmissions even if the probe crashes/times out.
        run("ip", "link", "set", "can0", "down")
        result["stopped"] = inspect()
        record("wire-" + str(count) + ".json", result)
    print(json.dumps(result, indent=2), flush=True)
    if not result["pass"]:
        raise RuntimeError("FD echo failed; interface stopped; do not continue to BRS")


def wire_ready(permit):
    if not WIRE_TRIAL or not permit:
        raise RuntimeError("Explicit isolated two-node approval required")
    manifest = json.loads((ROOT / "manifest.json").read_text())
    if boot_id() == manifest["original_boot_id"] or not MARKER.exists():
        raise RuntimeError("Not in temporary trial boot")
    if "UP" in inspect()["flags"]:
        raise RuntimeError("Expected interface DOWN")
    try:
        run("ip", "link", "set", "can0", "type", "can", "bitrate", "500000",
            "dbitrate", "500000", "fd", "on", "restart-ms", "0")
        run("ip", "link", "set", "can0", "up")
        record("wire-ready.json", inspect())
        print("WIRE READY: FD 500k/no BRS; no application frame sent; HMI gated", flush=True)
    except Exception:
        run("ip", "link", "set", "can0", "down")
        raise


def verify_restored():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    interface = inspect()
    services = {name: run("systemctl", "is-active", name, check=False).stdout.strip()
                for name in ("lubancat-can0.service", "lubancat-hmi.service",
                             "tightening-cloud-tunnel.service", "NetworkManager.service")}
    passive = run("timeout", "5", "candump", "-n", "6",
                  "can0,180:7FF,181:7FF,182:7FF", check=False)
    node = Path("/sys/firmware/devicetree/base/can@fe580000/compatible")
    info = interface["linkinfo"]["info_data"]
    hashes_match = digest(BOOT.read_bytes()) == manifest["original_sha256"]
    report = {"boot_id": boot_id(), "original_boot_config_restored": hashes_match,
              "boot_sha256": digest(BOOT.read_bytes()),
              "boot_symlink_preserved": BOOT_LINK.resolve() == BOOT,
              "compatible": node.read_bytes().rstrip(b"\0").decode(),
              "interface": interface, "services": services,
              "hotspot_devices": run("nmcli", "device", "status").stdout,
              "passive_receive_exit_code": passive.returncode,
              "passive_frames": passive.stdout.splitlines(),
              "trial_files_removed": not any(path.exists() for path in DROPS + [UNIT, MARKER]),
              "no_test_frames_sent": True}
    report["classic_restored_pass"] = (
        hashes_match and report["boot_symlink_preserved"] and report["trial_files_removed"]
        and interface["mtu"] == 16 and "UP" in interface["flags"]
        and info["bittiming"]["bitrate"] == 500000 and not info.get("ctrlmode")
        and info["berr_counter"] == {"tx": 0, "rx": 0}
        and interface["stats64"]["tx"]["packets"] == 0
        and interface["stats64"]["tx"]["errors"] == 0
        and interface["stats64"]["rx"]["errors"] == 0
        and passive.returncode == 0 and len(report["passive_frames"]) == 6
        and all(value == "active" for value in services.values()))
    record("recovery.json", report)
    print(json.dumps(report, indent=2), flush=True)
    if not report["classic_restored_pass"]:
        raise RuntimeError("Classic restoration verification incomplete; inspect recovery.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "probe", "restore", "watchdog", "verify",
                                            "wire-ready", "wire-test"])
    parser.add_argument("--reboot", action="store_true")
    parser.add_argument("--permit-isolated-two-node-test", action="store_true")
    parser.add_argument("--count", type=int, choices=(1, 4, 20), default=1)
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0:
        parser.error("Run only on LubanCat as root after explicit recovery/isolation approval")
    if args.reboot and args.command != "restore":
        parser.error("--reboot is accepted only for restore")
    {"prepare": prepare, "probe": probe, "restore": lambda: restore(args.reboot),
     "watchdog": watchdog, "verify": verify_restored,
     "wire-ready": lambda: wire_ready(args.permit_isolated_two_node_test),
     "wire-test": lambda: wire_test(args.count, args.permit_isolated_two_node_test)}[args.command]()


if __name__ == "__main__":
    main()
