"""Offline tests only: no serial port is opened."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from current_zero_calibration import (
    CalibrationBoard, calibration_evidence, require_ready, require_safe,
    require_source, require_stationary,
)


class CalibrationGuardTest(unittest.TestCase):
    def setUp(self):
        self.source = [
            "1 OK FW CURRENT=A CONFIRMED=A PENDING=- ACTIVE=0 ATTEMPTS=0",
            "2 OK SAFE LATCHED=1 SD=0 MOE=0 FOC=0",
            "3 OK STATUS MODE=IDLE BUSY=0 START_REQ=0 IqRef=0mA "
            "FLT=1 REASON=1 CTRL=0.0rpm DET=0.0rpm",
            "4 OK SELFTEST ZERO=0",
            "5 OK BENCH ACTIVE=0 LOCK=1 SD=0 MOE=0 CCER=0 CEN=0",
        ]
        self.ready = [
            "1 OK FW CURRENT=B CONFIRMED=B PENDING=- ACTIVE=0 ATTEMPTS=0",
            "2 OK SELFTEST READY=1 MASK=0x000 ZERO=1 ADC=1 FOC=1 ENC=1",
            "3 OK STATUS MODE=IDLE BUSY=0 START_REQ=0 IqRef=0mA "
            "FLT=0 REASON=0 CTRL=0.0rpm DET=0.0rpm",
        ]
        self.evidence = [
            "TWO ADC RUN ZERO CAL DONE", "STATIC ZERO : U=1558 V=1563",
            "RUN ZERO    : U=1563 V=1567", "VALID=4000 REJECTED=18",
        ]

    def test_recorded_source_accepted(self):
        require_source(*self.source)

    def test_source_mismatch_refused(self):
        for index, old, new in ((0, "PENDING=-", "PENDING=B"),
                                (0, "ACTIVE=0", "ACTIVE=1"),
                                (1, "SD=0", "SD=1"),
                                (2, "REASON=1", "REASON=2"),
                                (2, "START_REQ=0", "START_REQ=99"),
                                (4, "ACTIVE=0", "ACTIVE=1")):
            source = self.source.copy()
            source[index] = source[index].replace(old, new)
            with self.subTest(new=new), self.assertRaises(RuntimeError):
                require_source(*source)

    def test_real_ready_accepted_but_fault_or_fake_zero_refused(self):
        require_ready(*self.ready)
        for index, old, new in ((1, "ZERO=1", "ZERO=0"),
                                (1, "READY=1", "READY=0"),
                                (2, "FLT=0", "FLT=1")):
            ready = self.ready.copy()
            ready[index] = ready[index].replace(old, new)
            with self.subTest(new=new), self.assertRaises(RuntimeError):
                require_ready(*ready)

    def test_moving_missing_or_nonfinite_speed_refused(self):
        for value in ("2.0rpm", "nanrpm", "infrpm", ""):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                require_stationary("1 OK CTRL=" + value + " DET=0.0rpm")

    def test_safe_requires_all_outputs_off(self):
        require_safe(self.source[1])
        with self.assertRaises(RuntimeError):
            require_safe(self.source[1].replace("MOE=0", "MOE=1"))

    def test_calibration_counts_and_range(self):
        self.assertEqual(calibration_evidence(self.evidence),
                         (1558, 1563, 1563, 1567, 4000, 18))
        for old, new in (("VALID=4000", "VALID=3999"),
                         ("U=1563", "U=0")):
            lines = [line.replace(old, new) for line in self.evidence]
            with self.subTest(new=new), self.assertRaises(RuntimeError):
                calibration_evidence(lines)
        with self.assertRaises(RuntimeError):
            calibration_evidence(self.evidence + ["ISOLATED DIGITAL BASELINE ONLY"])

    def test_motion_and_upgrade_commands_never_reach_uart(self):
        board = CalibrationBoard.__new__(CalibrationBoard)
        for command in ("START", "STOP", "SET RUNDOWN_RPM 80", "FW END",
                        "FW CONFIRM", "BOOT A", "BENCH RUN"):
            with self.subTest(command=command), self.assertRaises(ValueError):
                board.send(command)


if __name__ == "__main__":
    unittest.main()
