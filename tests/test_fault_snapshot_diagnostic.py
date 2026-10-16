"""Offline tests; no serial/SWD/Flash/motor access."""
import struct
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from fault_snapshot_diagnostic import (
    SNAP_FORMAT, SNAP_KEYS, SNAP_SIZE, decode_snapshot, images, mailbox, trial_commands,
)


class FaultSnapshotTest(unittest.TestCase):
    def snapshot(self, **overrides):
        row = dict.fromkeys(SNAP_KEYS, 0)
        row.update(tick_ms=3000, adc_seq=65000, zero_u=1564, zero_v=1562,
                   accepted_u=1200, accepted_v=1562, physical_u=1200, physical_v=1562,
                   filter_on=1, median_count=1, valid_count=1, valid=1,
                   iu_mA=int((1564 - 1200) * 3300 / (4095 * 120) * 1000),
                   iv_mA=0,
                   iw_mA=-int((1564 - 1200) * 3300 / (4095 * 120) * 1000))
        row.update(overrides)
        return struct.pack(SNAP_FORMAT, *(row[k] for k in SNAP_KEYS))

    def test_actual_pinned_artifacts(self):
        a, b = images()
        self.assertEqual(len(a), 145236)
        self.assertEqual(len(b), 199144)

    def test_valid_last_offset_and_padded_size(self):
        data = self.snapshot()
        self.assertEqual(len(data), SNAP_SIZE)
        self.assertEqual(data[77], 1)
        self.assertEqual(struct.unpack_from("<I", data, 76)[0] >> 8 & 255, 1)

    def test_warmup_and_independent_conversion(self):
        row = decode_snapshot(self.snapshot())
        self.assertEqual(row["trip_phases"], ["U", "W"])
        self.assertTrue(row["median_warmup_at_fault"])
        self.assertTrue(row["first_accepted_frame"])
        self.assertFalse(row["physical_current_or_emi_proven"])

    def test_captured_fault_is_not_first_frame_or_conversion_error(self):
        path = Path(__file__).resolve().parents[1] / (
            "safety_backups/foc-first-fault-20261009/snapshot-1791551422021638100.bin")
        if not path.exists():
            self.skipTest("Physical capture unavailable")
        row = decode_snapshot(path.read_bytes())
        raw = row["raw_fields"]
        self.assertEqual(raw["accepted_u"], 1869)
        self.assertEqual(raw["accepted_v"], 1288)
        self.assertEqual(row["trip_phases"], ["U"])
        self.assertTrue(row["median_matches"])
        self.assertFalse(row["median_warmup_at_fault"])
        self.assertFalse(row["first_accepted_frame"])
        self.assertEqual(raw["valid_count"], 607)
        self.assertEqual(raw["reject_count"], 21)
        self.assertEqual(raw["analog_count"], 0)
        self.assertAlmostEqual(row["calculated_current_A"]["U"], -2.0482295482295485)

    def test_step_gate_and_median_cannot_reject_observed_bias(self):
        # Snapshot's three accepted samples all disagree with the zero by
        # hundreds of counts, while their mutual steps are within 60 counts.
        # This is offline replay, not a claim to reconstruct every prior frame.
        u, v = [1853, 1869, 1891], [1302, 1288, 1279]
        for series in (u, v):
            self.assertTrue(all(abs(b - a) < 60 for a, b in zip(series, series[1:])))
        gain = 3300 / (4095 * 120)
        self.assertGreater(abs((1564 - sorted(u)[1]) * gain), 2.0)
        self.assertGreater(min(x - 1564 for x in u), 100)
        self.assertGreater(min(1563 - x for x in v), 100)

    def test_invalid_and_inconsistent_snapshot(self):
        self.assertFalse(decode_snapshot(self.snapshot(valid=0))["valid"])
        with self.assertRaises(RuntimeError):
            decode_snapshot(self.snapshot(iu_mA=9999))
        with self.assertRaises(RuntimeError):
            decode_snapshot(b"\0" * 79)

    def test_no_test_firmware_confirmation(self):
        with self.assertRaises(ValueError):
            mailbox(1)
        self.assertIn("mww 0x2001ffd0 0x1", mailbox(3))  # target known A
        self.assertIn("mww 0x2001ffcc 0x2", mailbox(3))  # requester test B

    def test_bounded_no_image_write_and_lock_before_return(self):
        commands = trial_commands(Path("D:/new project/safety_backups/test.bin"))
        wire = "; ".join(commands)
        self.assertIn("$task_b_start >= 4000", wire)
        self.assertIn("< 20000", wire)
        self.assertIn("$task_vtor == 0x08040000", wire)
        self.assertIn("set task_probe_code [catch {", wire)
        self.assertLess(commands.index("mmw 0x4002104C 0x4 0"),
                        commands.index("mww 0x40012C20 0"))
        self.assertNotIn("flash write_image", wire)
        self.assertNotIn("FW CONFIRM", wire)
        self.assertEqual(commands.count("reset run"), 2)
        self.assertEqual(commands.count("mww 0x2001ffc8 0x2"), 1)
        stop = commands.index("mww 0x40012C20 0")
        capture = next(i for i, c in enumerate(commands) if c.startswith("dump_image"))
        restore = commands.index("mww 0x2001ffc8 0x3")
        self.assertLess(stop, capture)
        self.assertLess(capture, restore)

    def test_tcl_boot_delay_excluded_and_error_cleanup(self):
        # No target config, adapter or device init: every hardware primitive is
        # replaced by a Tcl stub before evaluating the generated command list.
        # Exercise a 6 s mock boot delay and a probe read exception independently.
        ocd = Path(r"D:\software\xpack-openocd-0.12.0-7\bin\openocd.exe")
        if not ocd.exists():
            self.skipTest("OpenOCD Tcl runtime not available")
        for inject in (0, 1):
            with self.subTest(inject=inject):
                stub = '''
set mock_time 0; set mock_reset 0; set mock_restored 0
proc ms {} {global mock_time; incr mock_time 10; return $mock_time}
rename init mock_original_init; proc init {} {}
proc halt {args} {}
proc reset {args} {global mock_reset; incr mock_reset}
proc mww {addr value} {global mock_restored; if {$addr == 0x2001ffc8 && $value == 3} {set mock_restored 1}}
proc mmw {args} {}
proc verify_image {args} {}
proc dump_image {args} {}
proc mdw {args} {}
proc mdb {args} {}
proc sleep {args} {}
proc mrw {addr} {
  global mock_time mock_reset mock_inject
  if {$addr == 0xE000ED08} {
    if {$mock_reset == 0} {return 0x08008000}
    if {$mock_time < 6000} {return 0}
    return 0x08040000
  }
  if {$addr == 0x200026ac} {
    if {$mock_inject} {error "mock read failure"}
    return 256
  }
  return 0
}
'''
                commands = trial_commands(Path("D:/new project/tmp/offline.bin"))
                commands[-1:-1] = ['echo "MOCK_RESTORED=$mock_restored"']
                wire = stub + f"\nset mock_inject {inject}\n" + "; ".join(commands)
                proc = subprocess.run([str(ocd), "-c", wire], capture_output=True,
                                      text=True, timeout=5)
                output = proc.stdout + proc.stderr
                self.assertEqual(proc.returncode, 0, output)
                self.assertIn("B_ENTRY_BOOT_MS=", output)
                self.assertIn("MOCK_RESTORED=1", output)
                self.assertIn("FIRST_FAULT_VALID=" + str(1 - inject), output)
                if inject:
                    self.assertIn("PROBE_LOOP_ERROR=mock read failure", output)


if __name__ == "__main__":
    unittest.main()
