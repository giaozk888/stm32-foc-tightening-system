"""Offline identity/completion gates; no serial or SWD calls."""
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import adc_owner_restart as restart

STATUS = (
    "1 OK ADC3PAR CH=3 REAL_W=1 W_ADC=5 W_PIN=PA8 W_DELAY=NONE "
    "SYNC=COMMON_EVENT W_READY=1 LOCK=1 SD=0 MOE=0 CCER=0 CEN=0 FOC=0 "
    "STATE=4 REASON=0 NU=4096 NV=4096 NW=4096 IRQ=1,1,1 MS=205 "
    "ERR=0,0,0 RESTORE=1 RANGE=1:2,1:2,1:2 CRC=1C64C2B7 CAP=4096"
)
FW = "1 OK FW CURRENT=B TARGET=A ACTIVE=0 CONFIRMED=B PENDING=- ATTEMPTS=0 GEN=384"


class RestartGates(unittest.TestCase):
    def test_only_intact_completed_capture(self):
        self.assertEqual(restart.require_completed(STATUS)["STATE"], "4")
        for old, new in (("STATE=4", "STATE=0"), ("REASON=0", "REASON=1"),
                         ("CEN=0", "CEN=1"), ("ERR=0,0,0", "ERR=0,1,0"),
                         ("NU=4096", "NU=4095"), ("RESTORE=1", "RESTORE=0"),
                         ("SD=0", "SD=1"), ("FOC=0", "FOC=1"),
                         ("IRQ=1,1,1", "IRQ=1,2,1"), ("W_ADC=5", "W_ADC=2")):
            with self.subTest(new=new), self.assertRaises(ValueError):
                restart.require_completed(STATUS.replace(old, new))

    def test_confirmed_generation(self):
        self.assertEqual(restart.require_generation(FW, "B", "384")["GEN"], "384")
        for old, new in (("GEN=384", "GEN=385"), ("PENDING=-", "PENDING=A"),
                         ("CONFIRMED=B", "CONFIRMED=A"), ("ACTIVE=0", "ACTIVE=1")):
            with self.subTest(new=new), self.assertRaises(RuntimeError):
                restart.require_generation(FW.replace(old, new), "B", "384")

    def test_code_and_pinned_hash_both_required(self):
        image = b"locked-test-image"
        digest = hashlib.sha256(image).hexdigest()
        with patch.dict(restart.PINNED, {"B": digest}):
            restart.verify_active_code(image, image, "B")
            with self.assertRaises(RuntimeError):
                restart.verify_active_code(image + b"x", image, "B")
        with patch.dict(restart.PINNED, {"B": "0" * 64}):
            with self.assertRaises(RuntimeError):
                restart.verify_active_code(image, image, "B")

    def test_missing_authority_exits_before_hardware(self):
        with patch.object(sys, "argv", ["restart", "--deployment-evidence", "nonexistent.json"]), \
                self.assertRaises(SystemExit) as raised:
            restart.main()
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
