import importlib.util
from pathlib import Path
import struct
import unittest
from unittest.mock import patch
import zlib

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("can_fd_probe", root / "tools/can_fd_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
check_spec = importlib.util.spec_from_file_location("can_fd_interface_check", root / "tools/can_fd_interface_check.py")
interface_check = importlib.util.module_from_spec(check_spec)
check_spec.loader.exec_module(interface_check)


class CanFdToolsTest(unittest.TestCase):
    def test_data_filter_is_exact_without_error_subscription(self):
        self.assertEqual(probe.DATA_FILTER_MASK, 0xc00007ff)
        self.assertEqual(probe.DATA_FILTER_MASK & 0x20000000, 0)
        self.assertEqual(probe.REPLY_ID & probe.DATA_FILTER_MASK, probe.REPLY_ID)

    def test_diagnostic_does_not_relax_acceptance(self):
        expected = probe.payload(9, 0xaa)
        raw = probe.FD_FRAME.pack(probe.REPLY_ID, 64, 2, expected)
        diagnostic = probe.describe_reply(raw, expected, False)
        self.assertIn("error_passive_flag", diagnostic["rejected_because"])
        self.assertFalse(probe.decode_reply(raw, expected, False))
        self.assertEqual(probe.describe_reply(raw[:16], expected, False)["rejected_because"],
                         ["frame_size"])

    def test_healthy_requires_fd_and_zero_counters(self):
        interface = {"mtu": 72, "flags": ["UP"], "linkinfo": {"info_data": {
            "ctrlmode": ["FD"], "state": "ERROR-ACTIVE", "berr_counter": {"tx": 0, "rx": 0}}}}
        self.assertTrue(probe.healthy(interface))
        interface["linkinfo"]["info_data"]["berr_counter"]["rx"] = 1
        self.assertFalse(probe.healthy(interface))
        interface["linkinfo"]["info_data"]["berr_counter"]["rx"] = 0
        interface["linkinfo"]["info_data"]["ctrlmode"] = []
        self.assertFalse(probe.healthy(interface))

    def test_layout_and_crc(self):
        for pattern in (0, 255, 0x55, 0xaa):
            data = probe.payload(7, pattern)
            self.assertEqual(len(data), 64)
            self.assertEqual(struct.unpack("<I", data[-4:])[0], zlib.crc32(data[:60]))
            self.assertEqual(len(probe.FD_FRAME.pack(probe.REQUEST_ID, 64, 0, data)), 72)

    def test_bad_input(self):
        for sequence in (0, -1, 0x100000000):
            with self.assertRaises(ValueError):
                probe.payload(sequence, 0)
        with self.assertRaises(ValueError):
            probe.payload(1, 256)

    def test_reply_identity_and_wire_format(self):
        data = probe.payload(1, 0x55)
        frame = probe.FD_FRAME.pack(probe.REPLY_ID, 64, 0, data)
        self.assertTrue(probe.decode_reply(frame, data, False))
        self.assertFalse(probe.decode_reply(frame, data, True))
        for identifier in (probe.REQUEST_ID, probe.REPLY_ID | 0x80000000,
                           probe.REPLY_ID | 0x20000000, probe.REPLY_ID | 0x40000000):
            self.assertFalse(probe.decode_reply(probe.FD_FRAME.pack(identifier, 64, 0, data), data, False))
        for length in (8, 63, 65):
            self.assertFalse(probe.decode_reply(probe.FD_FRAME.pack(probe.REPLY_ID, length, 0, data), data, False))
        self.assertFalse(probe.decode_reply(frame[:16], data, False))
        self.assertFalse(probe.decode_reply(frame, probe.payload(2, 0x55), False))
        self.assertFalse(probe.decode_reply(probe.FD_FRAME.pack(probe.REPLY_ID, 64, 2, data), data, False))
        self.assertTrue(probe.decode_reply(probe.FD_FRAME.pack(probe.REPLY_ID, 64, 1, data), data, True))

    def test_interface_failure_restores_classic(self):
        before = {"flags": ["UP"], "mtu": 16,
                  "linkinfo": {"info_kind": "can", "info_data": {
                      "bittiming": {"bitrate": 500000, "tq": 50, "prop_seg": 17,
                                    "phase_seg1": 17, "phase_seg2": 5, "sjw": 1}, "restart_ms": 100}}}
        rejected = interface_check.subprocess.CompletedProcess([], 2, "", "Operation not supported")
        with patch.object(interface_check, "inspect", return_value=before), \
             patch.object(interface_check, "run") as command, \
             patch.object(interface_check.subprocess, "run", return_value=rejected) as configure:
            report = interface_check.check("can0", True)
        self.assertFalse(report["fd_configured"])
        self.assertTrue(report["restored"])
        self.assertEqual(configure.call_count, 2)
        self.assertEqual(configure.call_args_list[1].args[0],
                         ["ip", "link", "set", "can0", "type", "can", "bitrate", "500000",
                          "dbitrate", "500000", "fd", "on"])
        self.assertEqual(report["fd500k_exit_code"], 2)
        self.assertEqual(command.call_args_list[0].args, ("ip", "link", "set", "can0", "down"))
        self.assertEqual(command.call_args_list[-1].args, ("ip", "link", "set", "can0", "up"))

    def test_interface_read_only_does_not_modify(self):
        before = {"flags": ["UP"], "mtu": 16,
                  "linkinfo": {"info_kind": "can", "info_data": {"bittiming": {"bitrate": 500000}}}}
        with patch.object(interface_check, "inspect", return_value=before), \
             patch.object(interface_check, "run") as command:
            report = interface_check.check("can0", False)
            command.assert_not_called()
        self.assertTrue(report["no_frames_sent"])

    def test_reject_unknown_baseline(self):
        before = {"mtu": 72, "linkinfo": {"info_kind": "can", "info_data": {}}}
        with patch.object(interface_check, "inspect", return_value=before), \
             patch.object(interface_check, "run") as command:
            with self.assertRaises(ValueError):
                interface_check.check("can0", True)
            command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
