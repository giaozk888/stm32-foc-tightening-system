"""64-byte read-only CAN FD echo test; never configures an interface or flashes."""
import argparse
import json
import secrets
import socket
import struct
import subprocess
import sys
import time
import zlib

REQUEST_ID, REPLY_ID = 0x702, 0x703
CANFD_BRS, CANFD_ESI = 1, 2
DATA_FILTER_MASK = 0x80000000 | 0x40000000 | 0x7ff
FD_FRAME = struct.Struct("=IBB2x64s")


def payload(sequence, pattern):
    if not 0 < sequence <= 0xffffffff:
        raise ValueError("Nonzero 32-bit transaction required")
    if not 0 <= pattern <= 255:
        raise ValueError("Byte pattern required")
    head = b"CFD1" + struct.pack("<I", sequence) + bytes([pattern]) * 52
    return head + struct.pack("<I", zlib.crc32(head) & 0xffffffff)


def decode_reply(raw, expected, brs):
    if len(raw) != FD_FRAME.size:
        return False
    identifier, length, flags, data = FD_FRAME.unpack(raw)
    return (identifier == REPLY_ID and length == 64 and
            not flags & ~(CANFD_BRS | CANFD_ESI | 4) and not flags & CANFD_ESI and
            bool(flags & CANFD_BRS) == brs and data == expected)


def describe_reply(raw, expected, brs):
    result = {"raw_length": len(raw), "raw_hex": raw.hex()}
    if len(raw) != FD_FRAME.size:
        result["rejected_because"] = ["frame_size"]
        return result
    identifier, length, flags, data = FD_FRAME.unpack(raw)
    reasons = []
    if identifier != REPLY_ID:
        reasons.append("identifier")
    if length != 64:
        reasons.append("payload_length")
    if flags & ~(CANFD_BRS | CANFD_ESI | 4):
        reasons.append("unknown_flags")
    if flags & CANFD_ESI:
        reasons.append("error_passive_flag")
    if bool(flags & CANFD_BRS) != brs:
        reasons.append("brs_flag")
    if data != expected:
        reasons.append("payload_mismatch")
    result.update(identifier=identifier, length=length, flags=flags,
                  expected_hex=expected.hex(), rejected_because=reasons)
    return result


def inspect_interface(name):
    return json.loads(subprocess.check_output(
        ["ip", "-j", "-details", "-statistics", "link", "show", name], text=True))[0]


def healthy(interface):
    info = interface["linkinfo"]["info_data"]
    return (interface["mtu"] == 72 and "UP" in interface["flags"] and
            "FD" in info.get("ctrlmode", []) and info["state"] == "ERROR-ACTIVE" and
            not any(info.get("berr_counter", {}).values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", default="can0")
    parser.add_argument("--brs", action="store_true")
    parser.add_argument("--permit-read-only-test", action="store_true")
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()
    if sys.platform != "linux" or not args.permit_read_only_test:
        parser.error("Linux and explicit approval required; no sockets opened")
    if not 1 <= args.count <= 40:
        parser.error("Count must be 1..40")
    before = inspect_interface(args.interface)
    info = before["linkinfo"]["info_data"]
    if (not healthy(before) or
            info["bittiming"]["bitrate"] != 500000):
        parser.error("An already configured, healthy 500k CAN FD interface is required")
    if args.brs and info.get("data_bittiming", {}).get("bitrate") != 2000000:
        parser.error("BRS test requires matching 2M data timing")
    counters = info.get("berr_counter", {})
    if counters.get("tx", 0) or counters.get("rx", 0):
        parser.error("Existing CAN errors; test refused")
    seed = secrets.randbelow(0xffffffff - args.count) + 1
    latencies = []
    queued = 0
    received_frames = []
    error = None
    try:
        with socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW) as bus:
            bus.setsockopt(socket.SOL_CAN_RAW, 5, 1)  # CAN_RAW_FD_FRAMES
            # Exact standard data frame filter. CAN_ERR_FLAG belongs to the
            # separate CAN_RAW_ERR_FILTER option, not this data-frame mask.
            bus.setsockopt(socket.SOL_CAN_RAW, 1, struct.pack("=II", REPLY_ID, DATA_FILTER_MASK))
            bus.bind((args.interface,))
            for i in range(args.count):
                if not healthy(inspect_interface(args.interface)):
                    raise RuntimeError("CAN errors before next request; stop test")
                expected = payload(seed + i, (0x00, 0xff, 0x55, 0xaa)[i % 4])
                started = time.monotonic()
                if bus.send(FD_FRAME.pack(REQUEST_ID, 64, CANFD_BRS if args.brs else 0, expected)) != 72:
                    raise RuntimeError("CAN FD frame not locally queued")
                queued += 1
                deadline = started + 1.0
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeError("Echo timeout; stop test, do not enable motor")
                    bus.settimeout(remaining)
                    raw = bus.recv(72)
                    if len(received_frames) < 4:
                        received_frames.append(describe_reply(raw, expected, args.brs))
                    if decode_reply(raw, expected, args.brs):
                        break
                latencies.append((time.monotonic() - started) * 1000)
                time.sleep(0.2)
    except Exception as exc:
        error = type(exc).__name__ + ": " + str(exc)
    after = inspect_interface(args.interface)
    stats_before, stats_after = before.get("stats64", {}), after.get("stats64", {})
    new_errors = any(stats_after.get(direction, {}).get("errors", 0) >
                     stats_before.get(direction, {}).get("errors", 0) for direction in ("rx", "tx"))
    old_xstats = before["linkinfo"].get("info_xstats", {})
    new_xstats = after["linkinfo"].get("info_xstats", {})
    new_errors |= any(new_xstats.get(name, 0) > old_xstats.get(name, 0)
                      for name in ("bus_error", "error_warning", "error_passive", "bus_off"))
    passed = error is None and len(latencies) == args.count and healthy(after) and not new_errors
    print(json.dumps({"pass": passed, "error": error, "requested": args.count,
                      "locally_queued": queued, "echoes": len(latencies),
                      "bytes_per_frame": 64, "brs": args.brs,
                      "max_rtt_ms": max(latencies) if latencies else None,
                      "latencies_ms": latencies, "before": before, "after": after,
                      "received_frames": received_frames,
                      "new_can_errors": new_errors, "power_stage_tested": False,
                      "firmware_written": False}, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
