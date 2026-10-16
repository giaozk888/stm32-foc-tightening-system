"""Temporary FD configuration check, no CAN frames sent; always restore can0."""
import argparse
import json
import os
import subprocess
import sys


def run(*args):
    return subprocess.run(args, text=True, capture_output=True, check=True).stdout


def inspect(name):
    return json.loads(run("ip", "-j", "-details", "-statistics", "link", "show", name))[0]


def check(name, permit):
    before = inspect(name)
    info = before["linkinfo"]["info_data"]
    if before["linkinfo"]["info_kind"] != "can" or before["mtu"] != 16:
        raise ValueError("Only an existing classic CAN interface is accepted")
    if info["bittiming"]["bitrate"] != 500000 or info.get("ctrlmode"):
        raise ValueError("Unexpected baseline; no configuration change made")
    report = {"before": before, "fd_configured": False, "no_frames_sent": True}
    if not permit:
        return report
    changed = False
    result = None
    try:
        run("ip", "link", "set", name, "down")
        changed = True
        result = subprocess.run(
            ["ip", "link", "set", name, "type", "can", "bitrate", "500000",
             "dbitrate", "2000000", "fd", "on"], text=True, capture_output=True)
        report["configuration_exit_code"] = result.returncode
        report["configuration_message"] = (result.stdout + result.stderr).strip()
        report["data2m_configured"] = result.returncode == 0
        if result.returncode != 0:
            # Linux 4.19 validates that FD requests include BOTH bit timings.
            # Keep a complete request and lower the data timing to nominal;
            # "bitrate 500000 fd on" alone is not a valid capability test.
            fd_low_rate = subprocess.run(
                ["ip", "link", "set", name, "type", "can", "bitrate", "500000",
                 "dbitrate", "500000", "fd", "on"], text=True, capture_output=True)
            report["fd500k_exit_code"] = fd_low_rate.returncode
            report["fd500k_message"] = (fd_low_rate.stdout + fd_low_rate.stderr).strip()
            result = fd_low_rate
        configured = inspect(name)
        report["during"] = configured
        report["fd_configured"] = result.returncode == 0 and configured["mtu"] == 72
        # Deliberately never bring an FD-configured interface up in this check.
    finally:
        if changed:
            if inspect(name)["mtu"] != 16:
                run("ip", "link", "set", name, "type", "can", "fd", "off")
            timing = info["bittiming"]
            run("ip", "link", "set", name, "type", "can",
                "tq", str(timing["tq"]), "prop-seg", str(timing["prop_seg"]),
                "phase-seg1", str(timing["phase_seg1"]),
                "phase-seg2", str(timing["phase_seg2"]), "sjw", str(timing["sjw"]),
                "restart-ms", str(info.get("restart_ms", 0)))
            if "UP" in before["flags"]:
                run("ip", "link", "set", name, "up")
            after = inspect(name)
            report["after"] = after
            after_info = after["linkinfo"]["info_data"]
            report["restored"] = (
                after["mtu"] == before["mtu"] and
                ("UP" in after["flags"]) == ("UP" in before["flags"]) and
                after_info["bittiming"] == info["bittiming"] and
                after_info.get("restart_ms", 0) == info.get("restart_ms", 0))
            if not report["restored"]:
                raise RuntimeError("RESTORE FAILED; keep power stage isolated and inspect can0")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", choices=["can0"], default="can0")
    parser.add_argument("--permit-interface-change", action="store_true")
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0:
        parser.error("Run on LubanCat as root, after explicit isolation approval")
    report = check(args.interface, args.permit_interface_change)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["fd_configured"] else 2


if __name__ == "__main__":
    sys.exit(main())
