"""Pure host gates; no serial, probe or hardware operation."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from zero_retest_sample import (fields, require_supply, require_locked_sample,
                               require_completed, OneShotUart, ZERO_MAX_SPAN_COUNTS,
                               require_confirmed_current)

GOOD = ("OK PROFILE=LOCKED_DIAGNOSTIC LOCK=1 SD=0 MOE=0 CCER=0 CEN=0 "
        "FOC=0 MOTOR_READY=0 IF=0 ADC_READY=1 ACTIVE=0 STATE=3 REASON=0 "
        "SPAN=100 NOM=1558 U0=1558 V0=1559 N=4000 SET=20000 RET=0 ADC=24000 RNG=1550:1560,1550:1565")


class SampleGates(unittest.TestCase):
    def test_either_confirmed_idle_slot_but_never_pending_trial(self):
        for slot in "AB":
            good = f"OK CURRENT={slot} CONFIRMED={slot} PENDING=- ATTEMPTS=0 ACTIVE=0"
            self.assertEqual(require_confirmed_current(good)["CURRENT"], slot)
            for old, new in (("PENDING=-", "PENDING=A"), ("ATTEMPTS=0", "ATTEMPTS=1"),
                             ("ACTIVE=0", "ACTIVE=1"),
                             (f"CONFIRMED={slot}", "CONFIRMED=-")):
                with self.assertRaises(RuntimeError):
                    require_confirmed_current(good.replace(old, new))
        with self.assertRaises(RuntimeError):
            require_confirmed_current("OK CURRENT=-")

    def test_digit_fields_and_ready_evidence(self):
        self.assertEqual(fields(GOOD)["U0"], "1558")
        require_completed(GOOD)
        for old, new in (("N=4000", "N=3999"), ("U0=1558", "U0=0"),
                         ("RNG=1550:1560,1550:1565", "RNG=1510:1611,1550:1565"),
                         ("ADC=24000", "ADC=23000")):
            with self.assertRaises(RuntimeError): require_completed(GOOD.replace(old, new))

    def test_live_span_and_exact_100_boundary(self):
        self.assertEqual(ZERO_MAX_SPAN_COUNTS, 100)
        header = (Path(__file__).resolve().parents[1] / "firmware_common/foc_current_zero.h").read_text(encoding="utf-8")
        self.assertIn(f"FOC_ZERO_MAX_SPAN = {ZERO_MAX_SPAN_COUNTS}U", header)
        require_completed(GOOD.replace("RNG=1550:1560,1550:1565", "RNG=1510:1610,1510:1610"))
        for old in (GOOD.replace("SPAN=100", "SPAN=20"), GOOD.replace("SPAN=100 ", "")):
            with self.assertRaises(RuntimeError): require_locked_sample(old)

    def test_outputs_never_enabled_even_while_sampling(self):
        active = GOOD.replace("CEN=0", "CEN=1").replace("ACTIVE=0", "ACTIVE=1").replace("STATE=3", "STATE=1")
        require_locked_sample(active)
        for key in ("SD", "MOE", "CCER", "FOC", "MOTOR_READY", "IF"):
            with self.assertRaises(RuntimeError): require_locked_sample(active.replace(key + "=0", key + "=1"))

    def test_failed_offsets_and_supply(self):
        failed = GOOD.replace("STATE=3", "STATE=4").replace("U0=1558", "U0=0").replace("V0=1559", "V0=0")
        require_completed(failed)
        with self.assertRaises(RuntimeError): require_completed(failed.replace("U0=0", "U0=1558"))
        supply = "VALID=1 PROTECT=0 VBUS_EST_MV=11592 VDDA_BOOT_MV=3285 AGE_MS=75"
        require_supply(supply)
        for old, new in (("11592", "7480"), ("75", "501"), ("VALID=1", "VALID=0")):
            with self.assertRaises(RuntimeError): require_supply(supply.replace(old, new))

    def test_no_second_sample_or_motion_query(self):
        class Port:
            def write(self, value): raise AssertionError("Must not send")
        uart = OneShotUart(Port())
        uart.sample_commands = 1
        with self.assertRaises(RuntimeError): uart.sample_once()
        for command in ("START", "CLEAR", "ZERO SAMPLE", "FW END", "BOOT B"):
            with self.assertRaises(ValueError): uart.query(command)


if __name__ == "__main__":
    unittest.main()
