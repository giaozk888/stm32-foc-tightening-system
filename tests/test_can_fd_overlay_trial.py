import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "can_fd_overlay_trial", Path(__file__).resolve().parents[1] / "tools/can_fd_overlay_trial.py")
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class OverlayTrialTest(unittest.TestCase):
    def test_replace_only_exact_active_overlay(self):
        original = (b"cmdline=keep\r\n#" + trial.CLASSIC + b"\r\n" + trial.CLASSIC
                    + b"\r\ndtoverlay=/dtb/overlay/rk3568-lubancat-can2-m0-overlay.dtbo\r\n")
        expected = original.replace(b"\r\n" + trial.CLASSIC + b"\r\n",
                                    b"\r\n" + trial.FD + b"\r\n")
        self.assertEqual(trial.candidate(original), expected)

    def test_reject_missing_duplicate_or_existing_fd(self):
        for data in (b"#" + trial.CLASSIC, trial.CLASSIC + b"\n" + trial.CLASSIC,
                     trial.CLASSIC + b"\n" + trial.FD):
            with self.assertRaises(RuntimeError):
                trial.candidate(data)

    def test_probe_never_bring_up_or_send(self):
        manifest = json.dumps({"original_boot_id": "old"})
        before = {"flags": [], "mtu": 16}
        reply = subprocess.CompletedProcess([], 2, "", "Operation not supported")
        with patch.object(trial.Path, "read_text", return_value=manifest), \
             patch.object(trial.Path, "read_bytes", return_value=b"rockchip,canfd-1.0\0"), \
             patch.object(trial.Path, "exists", return_value=True), \
             patch.object(trial, "boot_id", return_value="new"), \
             patch.object(trial, "inspect", return_value=before), \
             patch.object(trial, "run", return_value=reply) as command, \
             patch.object(trial, "record") as record, patch("builtins.print"):
            trial.probe()
        self.assertEqual(command.call_count, 2)
        for call in command.call_args_list:
            self.assertNotIn("up", call.args)
            self.assertIn("dbitrate", call.args)
            self.assertEqual(call.args[:5], ("ip", "link", "set", "can0", "type"))
        self.assertFalse(record.call_args.args[1]["fd_capability_enabled"])
        self.assertTrue(record.call_args.args[1]["no_frames_sent"])

    def test_probe_abort_if_can_already_up(self):
        with patch.object(trial.Path, "read_text", return_value='{"original_boot_id":"old"}'), \
             patch.object(trial.Path, "exists", return_value=True), \
             patch.object(trial, "boot_id", return_value="new"), \
             patch.object(trial, "inspect", return_value={"flags": ["UP"]}), \
             patch.object(trial, "run") as command:
            with self.assertRaises(RuntimeError):
                trial.probe()
        command.assert_not_called()

    def test_restore_preserve_external_boot_edits(self):
        original = b"original"
        manifest = {"original_sha256": trial.digest(original),
                    "trial_sha256": trial.digest(b"trial")}
        with patch.object(trial.Path, "read_text", return_value=json.dumps(manifest)), \
             patch.object(trial.Path, "read_bytes", side_effect=[original, b"user edit"]), \
             patch.object(trial, "atomic_write") as write:
            with self.assertRaises(RuntimeError):
                trial.restore(False)
        write.assert_not_called()

    def test_gates_and_watchdog_are_separate_and_bounded(self):
        self.assertIn(b"ConditionPathExists=!", trial.DROP_DATA)
        self.assertIn(b"controller.py watchdog", trial.UNIT_DATA)
        self.assertEqual(trial.TIMEOUT, 300)
        self.assertNotIn(b"Restart=", trial.UNIT_DATA)

    def test_wire_failure_stops_interface_without_mode_reset(self):
        live = {"flags": ["UP"], "mtu": 72,
                "linkinfo": {"info_data": {"ctrlmode": ["FD"],
                    "bittiming": {"bitrate": 500000}, "data_bittiming": {"bitrate": 500000}}}}
        failed = subprocess.CompletedProcess([], 2, '{"pass":false}', "")
        with patch.object(trial, "WIRE_TRIAL", True), \
             patch.object(trial.Path, "read_text", return_value='{"original_boot_id":"old"}'), \
             patch.object(trial.Path, "read_bytes", return_value=b"rockchip,canfd-1.0\0"), \
             patch.object(trial.Path, "exists", return_value=True), \
             patch.object(trial, "boot_id", return_value="new"), \
             patch.object(trial, "inspect", side_effect=[live, live, live, {"flags": []}]), \
             patch.object(trial, "run", return_value=failed) as command, \
             patch.object(trial, "record") as record, patch("builtins.print"):
            with self.assertRaises(RuntimeError):
                trial.wire_test(20, True)
        self.assertEqual(command.call_count, 2)
        self.assertEqual(command.call_args_list[-1].args, ("ip", "link", "set", "can0", "down"))
        self.assertFalse(record.call_args.args[1]["pass"])
        self.assertEqual(record.call_args.args[1]["stopped"]["flags"], [])

    def test_wire_traffic_requires_explicit_approval(self):
        with patch.object(trial, "WIRE_TRIAL", True), patch.object(trial, "run") as command:
            with self.assertRaises(RuntimeError):
                trial.wire_test(20, False)
        command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
