"""LubanCat read-only CAN FD profile setup. No application CAN frames sent.

Default: inspect only. --apply configures only a DOWN interface with the
already-selected, previously tested FD device tree. An unexpected live bus
is never interrupted. This tool does not edit boot files or install services.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

COMPATIBLE_PATH = Path("/sys/firmware/devicetree/base/can@fe580000/compatible")
EXPECTED_COMPATIBLE = b"rockchip,canfd-1.0"


def run(*args):
    return subprocess.check_output(args, text=True)


def inspect():
    return json.loads(run("ip", "-j", "-details", "-statistics", "link", "show", "can0"))[0]


def compatible():
    return COMPATIBLE_PATH.read_bytes().rstrip(b"\0")


def matches_profile(interface):
    info = interface.get("linkinfo", {}).get("info_data", {})
    return (interface.get("linkinfo", {}).get("info_kind") == "can"
            and interface.get("mtu") == 72
            and "UP" in interface.get("flags", [])
            and set(info.get("ctrlmode", [])) == {"FD"}
            and info.get("state") == "ERROR-ACTIVE"
            and info.get("bittiming", {}).get("bitrate") == 500000
            and info.get("data_bittiming", {}).get("bitrate") == 500000
            and info.get("restart_ms") == 0
            and info.get("berr_counter") == {"tx": 0, "rx": 0})


def setup(apply=False):
    before = inspect()
    selected = compatible()
    report = {"compatible": selected.decode(), "before": before,
              "modified": False, "profile_ready": False,
              "application_frames_sent": 0, "boot_files_changed": False}
    if selected != EXPECTED_COMPATIBLE:
        raise RuntimeError("FD device tree not selected; no interface or boot change made")
    if before.get("linkinfo", {}).get("info_kind") != "can":
        raise RuntimeError("Unexpected can0 device type; no change made")
    report["profile_ready"] = matches_profile(before)
    if not apply:
        return report
    if "UP" in before.get("flags", []):
        if report["profile_ready"]:
            return report
        raise RuntimeError("Unexpected live CAN profile/errors; refusing to interrupt bus")
    try:
        # Data timing is explicitly specified even with BRS disabled. Linux
        # requires both timings when enabling FD. Applications must keep BRS off.
        run("ip", "link", "set", "can0", "type", "can", "bitrate", "500000",
            "dbitrate", "500000", "fd", "on", "restart-ms", "0")
        run("ip", "link", "set", "can0", "up")
        after = inspect()
        if not matches_profile(after):
            raise RuntimeError("CAN FD profile did not become healthy")
    except Exception:
        run("ip", "link", "set", "can0", "down")
        raise
    report.update(modified=True, profile_ready=True, after=after)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if sys.platform != "linux" or (args.apply and os.geteuid() != 0):
        parser.error("Run on LubanCat; --apply requires root and deployment approval")
    report = setup(args.apply)
    print(json.dumps(report, indent=2))
    return 0 if report["profile_ready"] else 2


if __name__ == "__main__":
    sys.exit(main())
