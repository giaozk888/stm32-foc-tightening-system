"""Host-only argument/mapping checks; never acquire/reset a board in tests."""
from pathlib import Path
import contextlib
import io
import sys
import unittest
from unittest.mock import patch
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import adc12_ground_sample as ground


class GroundSamplerTests(unittest.TestCase):
    def test_missing_wiring_confirmation_stops_before_sampler(self):
        with patch.object(sys, "argv", ["ground", "--allow-sample"]), \
                patch.object(ground.parallel, "main") as sampler, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                ground.main()
            self.assertEqual(error.exception.code, 2)
            sampler.assert_not_called()

    def test_confirmed_mapping_keeps_existing_identity_and_one_shot_guards(self):
        arguments = ["ground", "--pa0-ground-pa1-divider-confirmed", "--inspect",
                     "--deployment-evidence", "evidence.json"]
        with patch.object(sys, "argv", arguments), patch.object(ground.parallel, "main") as sampler:
            ground.main()
            self.assertEqual(sys.argv, ["ground", "--inspect", "--deployment-evidence", "evidence.json"])
            call = sampler.call_args.kwargs
            self.assertIs(call["fresh_checker"], ground.require_fresh_adc12)
            self.assertIs(call["deployment_checker"], ground.deployment_identity)
            self.assertIs(call["capture_verifier"], ground.verify_capture)
            self.assertEqual(call["output_dir"], ROOT / "safety_backups/adc12-ground-live-20261010")
            self.assertIn("IVU disconnected", call["raw_mapping"]["U"])
            self.assertIn("divider", call["raw_mapping"]["V"])
            self.assertIn("UNSAMPLED", call["raw_mapping"]["W"])

    def test_firmware_profile_is_not_replaced(self):
        from adc12_only_acceptance import pinned_image
        _, image = pinned_image("A")
        self.assertEqual(len(image), 148644)
        self.assertIn(b"MODE=ADC12_ONLY CAPTURE_MASK=3 CH=2 REAL_W=0 PAD_W=ZERO_UNSAMPLED", image)

    def test_quiet_flag_preserves_wiring_gate_and_has_separate_evidence(self):
        with patch.object(sys, "argv", ["ground", "--pa0-ground-pa1-divider-confirmed",
                                       "--quiet-acquisition", "--inspect"]), \
                patch.object(ground.parallel, "main") as sampler:
            ground.main()
            self.assertEqual(sys.argv, ["ground", "--inspect"])
            self.assertTrue(sampler.call_args.kwargs["quiet_acquisition"])
            self.assertEqual(sampler.call_args.kwargs["output_dir"],
                             ROOT / "safety_backups/adc12-ground-quiet-live-20261010")

    def test_quiet_wait_precedes_exactly_one_status_query(self):
        events = []
        uart = Mock()
        uart.raw_query.side_effect = lambda *a, **k: events.append(("query", a, k)) or "4"
        with patch.object(ground.parallel.time, "sleep", side_effect=lambda n: events.append(("wait", n))):
            line = ground.parallel.await_terminal(uart, "2", lambda x: {"STATE": x},
                                                  quiet_acquisition=True)
        self.assertEqual(line, "4")
        self.assertEqual(events, [("wait", .5), ("query", ("ADC PAR STATUS",), {"timeout": .5})])

    def test_quiet_incomplete_or_query_failure_never_retries(self):
        for response in ("2", TimeoutError("No ACK")):
            uart = Mock()
            if isinstance(response, Exception): uart.raw_query.side_effect = response
            else: uart.raw_query.return_value = response
            with patch.object(ground.parallel.time, "sleep"), self.assertRaises((RuntimeError, TimeoutError)):
                ground.parallel.await_terminal(uart, "2", lambda x: {"STATE": x}, quiet_acquisition=True)
            uart.raw_query.assert_called_once_with("ADC PAR STATUS", timeout=.5)

    def test_terminal_does_not_sleep_or_query(self):
        uart = Mock()
        with patch.object(ground.parallel.time, "sleep") as sleep:
            self.assertEqual(ground.parallel.await_terminal(uart, "4", lambda x: {"STATE": x},
                                                            quiet_acquisition=True), "4")
            sleep.assert_not_called()
        uart.raw_query.assert_not_called()

    def test_original_polling_path_keeps_bounded_status_queries(self):
        uart = Mock()
        uart.raw_query.side_effect = ["2", "4"]
        with patch.object(ground.parallel.time, "monotonic", return_value=0), \
                patch.object(ground.parallel.time, "sleep") as sleep:
            self.assertEqual(ground.parallel.await_terminal(uart, "2", lambda x: {"STATE": x}), "4")
            self.assertEqual(sleep.call_count, 2)
            sleep.assert_called_with(.05)
        self.assertEqual(uart.raw_query.call_count, 2)


if __name__ == "__main__":
    unittest.main()
