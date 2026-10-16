"""Generic bounded binary fragments. CRC detects corruption, not a hostile peer."""
from dataclasses import dataclass
import re
import struct
import zlib

TYPE = 9
MAX_PACKET = 1024
FRAGMENT = 88
CHANNEL_BASE = 131072
_WIRE = re.compile(r"XFER ([0-9A-F]{8}) ([0-9A-F]{4}) ([0-9A-F]{4}) ([0-9A-F]{8}) ([0-9A-F]+)")


@dataclass(frozen=True)
class Fragment:
    packet_id: int
    offset: int
    total: int
    crc: int
    data: bytes


def parse(text):
    if len(text) > 209:
        raise ValueError("Transfer fragment MTU")
    match = _WIRE.fullmatch(text)
    if not match or len(match[5]) % 2:
        raise ValueError("canonical Transfer fragment")
    packet_id, offset, total, crc = (int(match[i], 16) for i in range(1, 5))
    data = bytes.fromhex(match[5])
    if (not packet_id or not 1 <= total <= MAX_PACKET or offset >= total or
            offset % FRAGMENT or len(data) != min(FRAGMENT, total - offset)):
        raise ValueError("Transfer fragment geometry")
    return Fragment(packet_id, offset, total, crc, data)


def fragments(packet_id, data):
    if not 1 <= packet_id <= 0xFFFFFFFF or not 1 <= len(data) <= MAX_PACKET:
        raise ValueError("bounded nonempty packet/id")
    crc = zlib.crc32(data)
    return [f"XFER {packet_id:08X} {offset:04X} {len(data):04X} {crc:08X} " +
            data[offset:offset + FRAGMENT].hex().upper()
            for offset in range(0, len(data), FRAGMENT)]


def allowed(src, dst, text):
    if not 1 <= src < 65535 or not 1 <= dst < 65535 or src == dst:
        return False
    try:
        parse(text)
        return True
    except ValueError:
        return False


def decode_encoder(data):
    if (len(data) != 40 or data[:4] != b"ENC1" or
            zlib.crc32(data[:36]) != struct.unpack_from("<I", data, 36)[0]):
        raise ValueError("encoder snapshot magic/size/CRC32")
    version, sequence, sample_us, completed_us, now_us, status, raw_response, errors = struct.unpack_from("<8I", data, 4)
    if version != 1:
        raise ValueError("encoder snapshot version")
    return dict(sequence=sequence, sample_us=sample_us, completed_us=completed_us,
                age_us=(now_us - sample_us) & 0xFFFFFFFF, status=status,
                raw=raw_response & 65535, response=raw_response >> 16,
                errfl=errors & 65535, errfl_valid=(errors >> 16) & 255,
                recovered=errors >> 24, spi_check="AS5047P parity (not sensor CRC)")
