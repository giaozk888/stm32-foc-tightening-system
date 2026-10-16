#!/usr/bin/env python3
"""
STM32G474 A/B IAP UART updater
Protocol:
  <REQ> FW STATUS
  <REQ> FW BEGIN <SIZE_DEC> <CRC32_HEX>
  <REQ> FW DATA <OFFSET_HEX> <HEX_BYTES>
  <REQ> FW END

Designed for the user's STM32G474 Protocol V2 + IAP FW V1 build.
"""

import argparse
import sys
import time
import zlib
from pathlib import Path

try:
    import serial
except ImportError:
    print("ERROR: pyserial is not installed.")
    print("Install it with:  py -m pip install pyserial")
    sys.exit(2)


CHUNK_SIZE = 32
DEFAULT_BAUD = 115200
RESPONSE_TIMEOUT_S = 3.0
BEGIN_TIMEOUT_S = 15.0
END_TIMEOUT_S = 20.0
MAX_RETRIES = 3


class IapError(RuntimeError):
    pass


class IapClient:
    def __init__(self, port: str, baud: int, verbose: bool = False):
        self.port = port
        self.baud = baud
        self.verbose = verbose
        self.req_id = 1000
        self.ser = None

    def open(self):
        self.ser = serial.Serial(
            self.port,
            self.baud,
            timeout=0.10,
            write_timeout=2.0,
        )
        # Do not toggle DTR/RTS intentionally.
        try:
            self.ser.dtr = False
            self.ser.rts = False
        except Exception:
            pass

        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        time.sleep(0.20)

    def close(self):
        if self.ser is not None:
            try:
                self.ser.close()
            finally:
                self.ser = None

    def next_req(self):
        rid = self.req_id
        self.req_id += 1
        if self.req_id > 0x7FFFFFFF:
            self.req_id = 1000
        return rid

    def _read_matching_response(self, req_id: int, timeout_s: float):
        deadline = time.monotonic() + timeout_s
        prefix = f"{req_id} ".encode("ascii")

        while time.monotonic() < deadline:
            raw = self.ser.readline()
            if not raw:
                continue

            line = raw.decode("ascii", errors="replace").strip()

            if self.verbose and line:
                print(f"[RX] {line}")

            # Runtime monitor logs are expected and ignored.
            if raw.startswith(prefix):
                return line

        raise TimeoutError(f"timeout waiting for response to request {req_id}")

    def command(self, command: str, timeout_s: float = RESPONSE_TIMEOUT_S,
                retries: int = MAX_RETRIES):
        last_exc = None

        for attempt in range(1, retries + 1):
            req_id = self.next_req()
            line = f"{req_id} {command}\r\n"

            if self.verbose:
                print(f"[TX] {line.rstrip()}")

            try:
                self.ser.write(line.encode("ascii"))
                self.ser.flush()

                resp = self._read_matching_response(req_id, timeout_s)

                if " OK " in f" {resp} " or resp.startswith(f"{req_id} OK "):
                    return resp

                if resp.startswith(f"{req_id} ERR "):
                    raise IapError(resp)

                raise IapError(f"unexpected response: {resp}")

            except IapError:
                # Explicit device error should not be blindly repeated.
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < retries:
                    print(f"Retry {attempt}/{retries} after: {exc}")
                    time.sleep(0.15)

        raise IapError(str(last_exc) if last_exc else "command failed")

    def status(self):
        return self.command("FW STATUS")

    def begin(self, size: int, crc32: int):
        return self.command(
            f"FW BEGIN {size} {crc32:08X}",
            timeout_s=BEGIN_TIMEOUT_S,
            retries=1,   # Erase is destructive; never blindly replay BEGIN.
        )

    def data(self, offset: int, payload: bytes):
        """
        Send one sequential data packet.

        Special retry handling:
        If the STM32 programmed a packet but its OK reply was lost, a retry of
        the same offset returns FW_SEQUENCE with EXPECT_OFFSET already advanced.
        In that one case, treat the packet as accepted instead of duplicating it.
        """
        command = f"FW DATA {offset:08X} {payload.hex().upper()}"
        next_offset = offset + len(payload)
        last_exc = None

        for attempt in range(1, MAX_RETRIES + 1):
            req_id = self.next_req()
            line = f"{req_id} {command}\r\n"

            if self.verbose:
                print(f"[TX] {line.rstrip()}")

            try:
                self.ser.write(line.encode("ascii"))
                self.ser.flush()
                resp = self._read_matching_response(
                    req_id, RESPONSE_TIMEOUT_S
                )

                if resp.startswith(f"{req_id} OK "):
                    return resp

                if resp.startswith(f"{req_id} ERR "):
                    marker = "EXPECT_OFFSET="
                    if marker in resp:
                        text = resp.split(marker, 1)[1].split()[0]
                        try:
                            expected = int(text, 16)
                        except ValueError:
                            expected = -1

                        if expected == next_offset:
                            # Previous attempt was programmed successfully and
                            # only its reply was lost.
                            return (
                                f"{req_id} OK FW DATA "
                                f"RECOVERED_NEXT_OFFSET={next_offset:08X}"
                            )

                    raise IapError(resp)

                raise IapError(f"unexpected response: {resp}")

            except IapError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    print(
                        f"Retry DATA offset 0x{offset:08X} "
                        f"({attempt}/{MAX_RETRIES}) after: {exc}"
                    )
                    time.sleep(0.15)

        raise IapError(
            str(last_exc) if last_exc else
            f"FW DATA failed at offset 0x{offset:08X}"
        )

    def end(self):
        return self.command(
            "FW END",
            timeout_s=END_TIMEOUT_S,
            retries=1,   # Device resets after a successful END.
        )


def main():
    ap = argparse.ArgumentParser(
        description="STM32G474 A/B UART IAP updater"
    )
    ap.add_argument("port", help="Serial port, e.g. COM5")
    ap.add_argument("image", help="Inactive-slot .bin image")
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument(
        "--no-status",
        action="store_true",
        help="Skip initial FW STATUS query",
    )
    args = ap.parse_args()

    image_path = Path(args.image)
    if not image_path.is_file():
        print(f"ERROR: file not found: {image_path}")
        return 2

    image = image_path.read_bytes()
    size = len(image)

    if size < 8:
        print("ERROR: image is too small.")
        return 2

    crc = zlib.crc32(image) & 0xFFFFFFFF

    print("========================================")
    print("STM32G474 UART IAP")
    print(f"Port : {args.port}")
    print(f"Baud : {args.baud}")
    print(f"Image: {image_path}")
    print(f"Size : {size} bytes")
    print(f"CRC32: 0x{crc:08X}")
    print(f"Chunk: {CHUNK_SIZE} bytes")
    print("========================================")

    client = IapClient(args.port, args.baud, args.verbose)

    try:
        client.open()

        if not args.no_status:
            status = client.status()
            print(status)

            # Safety hint only; the device itself enforces inactive-slot writing.
            if "CURRENT=A" in status:
                print("Device is running APP A; target should be APP B.")
            elif "CURRENT=B" in status:
                print("Device is running APP B; target should be APP A.")

        resp = client.begin(size, crc)
        print(resp)

        total_chunks = (size + CHUNK_SIZE - 1) // CHUNK_SIZE
        start = time.monotonic()

        offset = 0
        chunk_index = 0

        while offset < size:
            payload = image[offset:offset + CHUNK_SIZE]
            resp = client.data(offset, payload)

            offset += len(payload)
            chunk_index += 1

            if (
                chunk_index == 1
                or chunk_index == total_chunks
                or chunk_index % 100 == 0
            ):
                elapsed = max(time.monotonic() - start, 0.001)
                rate = offset / elapsed
                percent = 100.0 * offset / size
                print(
                    f"\rDATA {offset}/{size} bytes "
                    f"({percent:6.2f}%) "
                    f"{rate/1024.0:6.1f} KiB/s",
                    end="",
                    flush=True,
                )

        print()

        resp = client.end()
        print(resp)

        print()
        print("FW END accepted.")
        print("The MCU should now reset and the Bootloader should trial the new slot.")
        print("After the new APP is fully up, send:")
        print("  2000 FW STATUS")
        print("Then, only after confirming the new APP is healthy:")
        print("  2001 FW CONFIRM")

        return 0

    except KeyboardInterrupt:
        print("\nAborted by user.")
        return 130
    except (serial.SerialException, IapError, TimeoutError) as exc:
        print(f"\nERROR: {exc}")
        print("Do not issue FW END unless all DATA packets were acknowledged.")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
