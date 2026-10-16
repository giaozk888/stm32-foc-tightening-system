#!/usr/bin/env python3
"""Exercise only the non-actuating 0x220/0x2A0 CAN diagnostic exchange."""

import argparse
import socket
import struct
import sys
import time

REQUEST_ID = 0x220
REPLY_ID = 0x2A0
CAN_FRAME = struct.Struct("=IB3x8s")


def request(sock: socket.socket, opcode: int, sequence: int, value: int,
            expected: int, timeout_s: float) -> None:
    payload = struct.pack("<BBHHBB", 1, opcode, sequence, value, 0xA5, 0x5A)
    sock.send(CAN_FRAME.pack(REQUEST_ID, 8, payload))
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        sock.settimeout(max(0.01, deadline - time.monotonic()))
        try:
            frame = sock.recv(CAN_FRAME.size)
        except socket.timeout:
            continue
        if len(frame) != CAN_FRAME.size:
            continue
        can_id, dlc, data = CAN_FRAME.unpack(frame)
        if can_id != REPLY_ID or dlc != 8:
            continue
        version, reply_op, reply_seq, decision, reserved, guard0, guard1 = (
            struct.unpack("<BBHBBBB", data)
        )
        if (version, reply_op, reply_seq, reserved, guard0, guard1) != (
                1, opcode, sequence, 0, 0x5A, 0xA5):
            continue
        print(f"op={opcode} seq={sequence} value={value} decision={decision}")
        if decision != expected:
            raise RuntimeError(f"expected decision {expected}, got {decision}")
        return
    raise TimeoutError(f"no matching 0x2A0 reply for op={opcode} seq={sequence}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", default="can0")
    parser.add_argument("--timeout-ms", type=int, default=1200)
    args = parser.parse_args()
    if args.timeout_ms < 300 or args.timeout_ms > 10000:
        parser.error("--timeout-ms must be 300..10000")
    if not hasattr(socket, "AF_CAN"):
        parser.error("SocketCAN is required; run this on the LubanCat")

    with socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW) as sock:
        sock.bind((args.interface,))
        timeout_s = args.timeout_ms / 1000.0
        # STOP_TEST only resets the shadow session. It cannot stop a motor.
        request(sock, 3, 0, 0, 3, timeout_s)
        request(sock, 1, 1, 0, 1, timeout_s)
        request(sock, 2, 2, 1000, 2, timeout_s)
        request(sock, 1, 3, 0, 1, timeout_s)
        request(sock, 2, 4, 1001, 4, timeout_s)
        request(sock, 1, 5, 0, 1, timeout_s)
        time.sleep(0.65)
        request(sock, 2, 6, 1, 6, timeout_s)
        request(sock, 3, 0, 0, 3, timeout_s)
    print("PASS: request/reply, bounds, timeout, STOP_TEST; no motor action")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, TimeoutError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
