import struct
import unittest
import zlib
from router_network.core import Router, Route
from router_network.wire import Frame, parse as parse_frame
from router_network.transfer_wire import fragments, parse, decode_encoder


class TransferTests(unittest.TestCase):
    def test_binary_geometry(self):
        for size in (1, 87, 88, 89, 255, 1024):
            packet = bytes(i % 256 for i in range(size))
            pieces = fragments(0xFFFFFFFF, packet)
            self.assertEqual(b"".join(parse(p).data for p in pieces), packet)
            for index, piece in enumerate(pieces):
                frame = Frame(4, 1, 9, index, 8, piece)
                self.assertEqual(parse_frame(frame.encode().decode().strip()), frame)
        for size in (0, 1025):
            with self.assertRaises(ValueError):
                fragments(1, bytes(size))

    def test_actual_router_forward_and_ttl(self):
        middle = Router(2, clock=lambda: 1.0)
        delivered = []
        middle.add_port("pc", lambda f: True)
        middle.add_port("stm32", lambda f: delivered.append(f) or True)
        middle.routes[1] = Route("stm32", 1.0)
        packet = bytes(range(256)) * 4
        for seq, piece in enumerate(fragments(9, packet)):
            middle.receive("pc", Frame(4, 1, 9, seq, 8, piece))
        self.assertEqual(len(delivered), 12)
        self.assertTrue(all(f.ttl == 7 for f in delivered))
        self.assertEqual(b"".join(parse(f.payload).data for f in delivered), packet)
        middle.receive("pc", Frame(4, 1, 9, 100, 1, fragments(10, b"x")[0]))
        self.assertEqual(middle.stats["ttl"], 1)

    def test_invalid_and_broadcast(self):
        piece = fragments(1, b"abc")[0]
        for value in (piece.lower(), piece + "00", piece.replace("0003", "0401"),
                      piece.replace("00000001", "00000000"), "XFER "):
            with self.assertRaises(ValueError):
                parse(value)
        self.assertFalse(Frame(4, 65535, 9, 1, 8, piece).allowed())
        self.assertFalse(Frame(4, 4, 9, 1, 8, piece).allowed())

    def test_transfer_dedupe_uses_packet_identity_not_restarted_r1_seq(self):
        endpoint = Router(1, clock=lambda: 1.0)
        endpoint.add_port("host", lambda f: True)
        got = []
        endpoint.on_transfer = got.append
        endpoint.receive("host", Frame(4, 1, 9, 3, 8, fragments(100, b"first")[0]))
        endpoint.receive("host", Frame(4, 1, 9, 3, 8, fragments(101, b"new")[0]))
        endpoint.receive("host", Frame(4, 1, 9, 40, 8, fragments(101, b"new")[0]))
        self.assertEqual(len(got), 2)
        self.assertEqual(endpoint.stats["duplicate"], 1)

    def test_sample_crc_is_not_sensor_crc(self):
        data = b"ENC1" + struct.pack("<8I", 1, 9, 100, 130, 150, 0, 123, 0)
        data += struct.pack("<I", zlib.crc32(data))
        self.assertEqual(decode_encoder(data)["age_us"], 50)
        self.assertEqual(decode_encoder(data)["raw"], 123)
        with self.assertRaises(ValueError):
            decode_encoder(data[:12] + b"x" + data[13:])
