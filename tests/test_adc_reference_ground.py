"""Offline tests only: truthful ground mapping and one-reset hard-off gates."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import adc_reference_ground_sample as sample
import adc_reference_ground_restart as restart

WIRING = ["--both-ground-confirmed", "--pa0-measured-volts", "0", "--pa1-measured-volts", "0"]
PUBLIC = ROOT / "safety_backups/adc-reference-input-live-20261010"


class GroundReferenceTests(unittest.TestCase):
    def setUp(self):
        self.deployment = json.loads((PUBLIC / "deployment-1791639370434693100.json").read_text(encoding="utf-8"))
        self.capture = json.loads((PUBLIC / "capture-1791683778583519500.json").read_text(encoding="utf-8"))
        self.readback = json.loads((PUBLIC / "readback-1791683812879364400.json").read_text(encoding="utf-8"))

    def test_truthful_dual_ground_mapping_keeps_supply_and_no_retry_policy(self):
        for state in ("on", "off"):
            with patch.object(sys, "argv", ["sample", "--power-" + state, *WIRING]), \
                    patch.object(sample.parallel, "main") as run:
                sample.main()
            call = run.call_args.kwargs
            self.assertEqual(call["sample_command"], "ADC PAR SAMPLE " + state.upper())
            self.assertIs(call["fresh_checker"], sample.require_fresh_reference)
            self.assertIs(call["uart_factory"], sample.ReferenceUart)
            self.assertIs(call["supply_checker"].func, sample.require_supply)
            self.assertEqual(call["supply_checker"].keywords, {"power": state.upper()})
            self.assertTrue(call["quiet_acquisition"])
            for key in ("U", "V"):
                self.assertIn("MCU GND", call["raw_mapping"][key])
                self.assertIn("disconnected", call["raw_mapping"][key])
                self.assertNotIn("divider", call["raw_mapping"][key])
            self.assertIn("UNSAMPLED", call["raw_mapping"]["W"])

    def test_bad_measured_ground_or_missing_confirmation_prevents_io(self):
        for value in ("nan", "inf", "-inf", "0.051", "-0.051", "1.6", "3.3"):
            argv = ["sample", "--power-on", "--both-ground-confirmed",
                    "--pa0-measured-volts", value, "--pa1-measured-volts", "0"]
            with patch.object(sys, "argv", argv), patch.object(sample.parallel, "main") as run, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    sample.main()
                run.assert_not_called()
        with patch.object(sys, "argv", ["sample", "--power-on", "--pa0-measured-volts", "0", "--pa1-measured-volts", "0"]), \
                patch.object(sample.parallel, "main") as run, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                sample.main()
            run.assert_not_called()

    def test_supply_physical_flags_are_not_bypassed(self):
        for state, wrong in (("off", "--supply-12v-0p5a-no-alarm"), ("on", "--drive-12v-off")):
            argv = ["sample", "--power-" + state, *WIRING, "--deployment-evidence", "unused.json",
                    "--allow-sample", "--motor-leads-disconnected", wrong]
            with patch.object(sys, "argv", argv), patch.object(Path, "read_text") as read, \
                    patch.object(sample.parallel.subprocess, "run") as cli, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    sample.main()
                read.assert_not_called()
                cli.assert_not_called()

    def test_preserved_real_on_batch_can_authorize_this_reset_not_off_comparison(self):
        self.assertEqual(restart.prior_identity(self.deployment, self.capture, self.readback),
                         ("B", "396", "01EB0DA1", "ON"))
        import adc_reference_restart as original
        with self.assertRaises(RuntimeError):
            original.prior_identity(self.deployment, self.capture, self.readback)

    def test_corrupt_generation_crc_raw_or_write_history_rejects_prior(self):
        changes = [("capture", lambda c: c["after_fw"].update(GEN="397")),
                   ("capture", lambda c: c.update(sample_commands=2)),
                   ("capture", lambda c: c["triples"][0].__setitem__(0, 0)),
                   ("readback", lambda r: r.update(reset=True)),
                   ("readback", lambda r: r.update(target_ram_write=True)),
                   ("readback", lambda r: r.update(crc32="00000000"))]
        for target, change in changes:
            data = {"deployment": copy.deepcopy(self.deployment), "capture": copy.deepcopy(self.capture),
                    "readback": copy.deepcopy(self.readback)}
            change(data[target])
            with self.assertRaises((ValueError, RuntimeError)):
                restart.prior_identity(data["deployment"], data["capture"], data["readback"])

    def test_full_active_code_required_before_reset(self):
        _, image = restart.pinned_image("B")
        restart.verify_active_code(image, image)
        corrupt = bytearray(image)
        corrupt[100] ^= 1
        for code in (bytes(corrupt), image[:-1], restart.pinned_image("A")[1]):
            with self.assertRaises(RuntimeError):
                restart.verify_active_code(code, image)

    def test_current_generation_and_prior_crc_guards(self):
        from tests.test_adc_reference_tools import status
        restart.require_prior_status(status("ON", 11734, 0x01EB0DA1), "01EB0DA1", "ON")
        for crc, power in (("00000000", "ON"), ("01EB0DA1", "OFF")):
            with self.assertRaises((RuntimeError, ValueError)):
                restart.require_prior_status(status("ON", 11734, 0x01EB0DA1), crc, power)
        fw = "1 OK FW CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0 ACTIVE=0 GEN=396"
        restart.require_generation(fw, "B", "396")
        with self.assertRaises(RuntimeError):
            restart.require_generation(fw, "B", "397")

    def test_reset_requires_every_authorization_flag_before_files_or_probe(self):
        flags = ["--allow-one-reset", "--drive-12v-off", "--motor-leads-disconnected", "--both-ground-confirmed"]
        base = ["reset", "--deployment", "d.json", "--capture", "c.json", "--readback", "r.json"]
        for missing in flags:
            with patch.object(sys, "argv", [*base, *(f for f in flags if f != missing)]), \
                    patch.object(Path, "read_text") as read, patch.object(restart.subprocess, "run") as cli, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    restart.main()
                read.assert_not_called()
                cli.assert_not_called()

    def test_main_one_reset_or_uncertain_reset_failure_never_retries(self):
        _, image = restart.pinned_image("B")
        flags = ["--allow-one-reset", "--drive-12v-off", "--motor-leads-disconnected", "--both-ground-confirmed"]
        argv = ["reset", "--deployment", "d.json", "--capture", "c.json", "--readback", "r.json", *flags]
        for reset_fails in (False, True):
            calls = []
            def cli(command, **kwargs):
                calls.append(command)
                return Mock(returncode=1 if reset_fails and "-rst" in command else 0, stdout="", stderr="")
            before, after = Mock(), Mock()
            for uart in (before, after):
                uart.lines = []
                uart.sample_commands = 0
                uart.query.return_value = "1 OK VBUS_EST_MV=7570"
            port = Mock()
            serial_module = Mock()
            serial_module.Serial.return_value = port
            with patch.object(sys, "argv", argv), patch.dict(sys.modules, {"serial": serial_module}), \
                    patch.object(Path, "read_text", side_effect=[json.dumps(d) for d in (self.deployment, self.capture, self.readback)]), \
                    patch.object(Path, "read_bytes", return_value=image), patch.object(Path, "write_text") as write, \
                    patch.object(Path, "mkdir"), patch.object(restart.subprocess, "run", side_effect=cli), \
                    patch.object(restart, "ReferenceUart", side_effect=[before, after]), \
                    patch.object(restart, "require_registers", return_value={}), \
                    patch.object(restart, "require_generation", return_value={"GEN": "396"}), \
                    patch.object(restart, "require_owner_service", return_value={}), \
                    patch.object(restart, "require_prior_status", return_value={"CRC": "01EB0DA1"}), \
                    patch.object(restart, "require_fresh_reference", return_value={"raw": {"STATE": "0"}}) as fresh, \
                    patch.object(restart.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
                if reset_fails:
                    with self.assertRaises(RuntimeError):
                        restart.main()
                    fresh.assert_not_called()
                else:
                    restart.main()
                result = json.loads(write.call_args.args[0])
            self.assertEqual(sum("-rst" in c for c in calls), 1)
            self.assertTrue(all("-r32" in c or "-u" in c or "-rst" in c for c in calls))
            self.assertEqual(result["reset_commands"], 1)
            self.assertEqual(result["sample_commands"], 0)
            self.assertFalse(result["flash_write"])
            self.assertEqual(result["pass"], not reset_fails)
            self.assertEqual(port.dtr, False)
            self.assertEqual(port.rts, False)


if __name__ == "__main__":
    unittest.main()
