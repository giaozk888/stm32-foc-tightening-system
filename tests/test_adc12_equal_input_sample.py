"""Host-only equal-input wiring/measurement gates. No board access."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import adc12_equal_input_sample as equal


class EqualInputTests(unittest.TestCase):
    def test_requires_wiring_and_both_measurements_before_board_access(self):
        for args in ([], ["--same-divider-confirmed"],
                     ["--pa0-measured-volts", "1.6", "--pa1-measured-volts", "1.6"]):
            with patch.object(sys, "argv", ["equal", *args]), \
                    patch.object(equal.parallel, "main") as sampler, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    equal.main()
                sampler.assert_not_called()

    def test_rejects_nonfinite_and_wrong_voltage(self):
        for voltage in ("nan", "inf", "0", "3.3", "-1"):
            with patch.object(sys, "argv", ["equal", "--same-divider-confirmed",
                             "--pa0-measured-volts", voltage, "--pa1-measured-volts", "1.6"]), \
                    patch.object(equal.parallel, "main") as sampler, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    equal.main()
                sampler.assert_not_called()

    def test_delegation_preserves_fixed_identity_and_no_retry_guards(self):
        argv = ["equal", "--same-divider-confirmed", "--pa0-measured-volts", "1.6",
                "--pa1-measured-volts", "1.6", "--inspect", "--deployment-evidence", "old.json"]
        with patch.object(sys, "argv", argv), patch.object(equal.parallel, "main") as sampler:
            equal.main()
            self.assertEqual(sys.argv, ["equal", "--inspect", "--deployment-evidence", "old.json"])
            kw = sampler.call_args.kwargs
            self.assertIs(kw["deployment_checker"], equal.deployment_identity)
            self.assertIs(kw["fresh_checker"], equal.require_fresh_adc12)
            self.assertIs(kw["capture_verifier"], equal.verify_capture)
            self.assertIs(kw["image_hashes"], equal.PINNED)
            self.assertTrue(kw["quiet_acquisition"])
            self.assertEqual(kw["output_dir"], ROOT / "safety_backups/adc12-equal-input-live-20261010")
            self.assertIn("same divider", kw["raw_mapping"]["U"])
            self.assertIn("1.6 V", kw["raw_mapping"]["V"])
            self.assertIn("UNSAMPLED", kw["raw_mapping"]["W"])


if __name__ == "__main__":
    unittest.main()
