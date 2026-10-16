"""Small strict wire codec for pinned Pigweed RpcPacket; not an RPC server.

Type 8, STM32 node 1 only, four unary read-only methods. Business snapshots
remain the project's versioned little-endian words used by its CAN service.
"""
from dataclasses import dataclass
import struct

TYPE = 8
MAX_PACKET = 110
CHANNEL_BASE = 65536
SERVICE = 0x45FA4BE2
METHODS = {"Ping": 0x860C5B16, "GetStatus": 0x87DEA601,
           "GetParams": 0x9C8A06AD, "GetDiagnostics": 0x425E79C4}
SIZES = {METHODS["Ping"]: 16, METHODS["GetStatus"]: 32,
         METHODS["GetParams"]: 76, METHODS["GetDiagnostics"]: 40}


@dataclass(frozen=True)
class Packet:
    type: int = 0
    channel: int = 0
    service: int = 0
    method: int = 0
    call: int = 0
    status: int = 0
    payload: bytes = b""


def varint(value):
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("uint32 range")
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def encode(packet):
    data = (b"\x08" + varint(packet.type) + b"\x10" + varint(packet.channel) +
            b"\x1d" + struct.pack("<I", packet.service) +
            b"\x25" + struct.pack("<I", packet.method) +
            b"\x38" + varint(packet.call))
    if packet.status:
        data += b"\x30" + varint(packet.status)
    if packet.payload:
        data += b"\x2a" + varint(len(packet.payload)) + packet.payload
    if not 0 < len(data) <= MAX_PACKET:
        raise ValueError("RPC MTU exceeded")
    return "RPC " + data.hex().upper()


def decode(text):
    if (not text.startswith("RPC ") or not 0 < len(text)-4 <= 2*MAX_PACKET or
            (len(text)-4) % 2 or any(c not in "0123456789ABCDEF" for c in text[4:])):
        raise ValueError("canonical bounded RPC hex")
    data = bytes.fromhex(text[4:])
    pos = 0
    def take_varint():
        nonlocal pos
        value = 0
        for n in range(5):
            if pos == len(data):
                raise ValueError("truncated varint")
            byte = data[pos]
            pos += 1
            if n == 4 and byte & 0xF0:
                raise ValueError("varint overflow")
            value |= (byte & 127) << (7*n)
            if not byte & 128:
                return value
        raise ValueError("unterminated varint")
    fields, seen = {}, set()
    names = {1: "type", 2: "channel", 3: "service", 4: "method",
             5: "payload", 6: "status", 7: "call"}
    while pos < len(data):
        key = take_varint()
        field, wire = key >> 3, key & 7
        if field not in names or field in seen:
            raise ValueError("unknown or duplicate field")
        seen.add(field)
        if field in (3, 4):
            if wire != 5 or len(data)-pos < 4:
                raise ValueError("fixed32 field")
            value = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        elif field == 5:
            if wire != 2:
                raise ValueError("payload wire type")
            size = take_varint()
            if size > len(data)-pos:
                raise ValueError("truncated payload")
            value = data[pos:pos+size]
            pos += size
        else:
            if wire != 0:
                raise ValueError("varint wire type")
            value = take_varint()
        fields[names[field]] = value
    if not {2, 3, 4, 7}.issubset(seen) or not fields["call"]:
        raise ValueError("explicit RPC identities required")
    return Packet(**fields)


def allowed(src, dst, text):
    try:
        p = decode(text)
    except (ValueError, TypeError):
        return False
    if not 1 <= src < 65535 or not 1 <= dst < 65535 or p.service != SERVICE or p.method not in SIZES:
        return False
    if p.type == 0:
        return (dst == 1 and src != 1 and not p.status and p.channel == CHANNEL_BASE+src and
                (len(p.payload) <= 16 if p.method == METHODS["Ping"] else not p.payload))
    if src != 1 or dst == 1 or p.channel != CHANNEL_BASE+dst or p.status > 16:
        return False
    if p.type == 5:
        return bool(p.status) and not p.payload
    return p.type == 1 and (not p.payload if p.status else
                           (len(p.payload) <= 16 if p.method == METHODS["Ping"] else len(p.payload) == SIZES[p.method]))


def request(src, method, call, payload=b""):
    if method not in METHODS:
        raise ValueError("read-only method only")
    text = encode(Packet(channel=CHANNEL_BASE+src, service=SERVICE,
                         method=METHODS[method], call=call, payload=payload))
    if not allowed(src, 1, text):
        raise ValueError("invalid read-only request")
    return text


def decode_payload(method, payload):
    """Decode the existing version-1 RAM snapshot; never interpret new versions."""
    if method == "Ping":
        return payload.decode("ascii")
    if method not in METHODS or len(payload) != SIZES[METHODS[method]]:
        raise ValueError("read-only snapshot length")
    words = struct.unpack("<" + "I"*(len(payload)//4), payload)
    if words[0] != 1:
        raise ValueError("unsupported snapshot version")
    names = {
        "GetStatus": ("version", "uptime_ms", "motor_mode_id", "flags", "fault_reason",
                      "safety_latched", "firmware_update_active", "can_motion_enabled"),
        "GetParams": ("version", "rundown_rpm", "contact_rpm", "contact_iq_mA", "contact_ms",
                      "rundown_timeout_ms", "max_travel_deg", "seating_iq_mA", "t1_iq_mA",
                      "t2_iq_mA", "t3_iq_mA", "hold_iq_mA", "seating_ms", "t1_ms", "t2_ms",
                      "t3_ms", "hold_ms", "torque_abort_rpm", "post_travel_max_deg"),
        "GetDiagnostics": ("version", "log_ready", "log_enqueued", "log_dropped_full",
                           "log_dropped_uart", "log_dropped_pool", "can_ready", "can_bus_off_events",
                           "can_recoveries", "can_rpc_fifo_overruns"),
    }
    result = dict(zip(names[method], words))
    if method == "GetStatus":
        result.update(foc_enabled=bool(words[3] & 1), fault=bool(words[3] & 2),
                      encoder_valid=bool(words[3] & 4))
    return result
