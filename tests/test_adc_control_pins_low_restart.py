"""Offline only: reset admission and fail-closed behavior; no board access."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import adc_control_pins_low_restart as restart
import adc_control_pins_low_sample as sample
import adc_control_wire_group_audit as group_audit

DIR = ROOT / "safety_backups/adc-control-pins-low-live-20261011"
FILES = (DIR / "deployment-1791709552602714400.json",
         DIR / "capture-1791709871367018700.json",
         DIR / "readback-1791709894484702200.json")


class RestartTests(unittest.TestCase):
    def evidence(self):
        return [json.loads(p.read_text(encoding="utf-8")) for p in FILES]

    def test_preserved_actual_a_batch(self):
        self.assertEqual(restart.prior_identity(*self.evidence()), ("A", "399", "431AB0B8", "ON"))

    def test_wrong_identity_mutation_lock_or_raw_rejected(self):
        for i, key, value in (
                (0, "profile", "OLD"), (1, "sha256", restart.PINNED["B"]),
                (1, "sample_commands", 2), (1, "reset", True), (1, "thresholds_changed", True),
                (1, "host_quiet_after_sample_ack", False), (2, "slot", "B"),
                (2, "image_sha256", restart.PINNED["B"]), (2, "mismatched_entries", 1),
                (2, "bytes", 12288), (2, "halt", True), (2, "sample_commands", 1),
                (2, "crc32", "00000000")):
            bad = self.evidence(); bad[i][key] = value
            with self.subTest(key=key, value=value), self.assertRaises((RuntimeError, ValueError)):
                restart.prior_identity(*bad)
        for member in ("before_fw", "after_fw"):
            bad = self.evidence(); bad[1][member]["GEN"] = "400"
            with self.assertRaises(RuntimeError): restart.prior_identity(*bad)
        for phase in ("before_status", "after_status"):
            bad = self.evidence(); bad[2][phase]["raw"]["PIN_LEVEL"] = "0"
            with self.assertRaises(ValueError): restart.prior_identity(*bad)
        bad = self.evidence(); bad[1]["triples"][2369][0] ^= 1
        with self.assertRaises((RuntimeError, ValueError)): restart.prior_identity(*bad)
        bad = self.evidence(); bad[1]["uart"] = []
        with self.assertRaises(RuntimeError): restart.prior_identity(*bad)

    def test_only_actual_exact_a_image(self):
        image = restart.pinned_image("A")[1]
        restart.verify_active_code(image, image)
        bad = bytearray(image); bad[20] ^= 1
        with self.assertRaises(RuntimeError): restart.verify_active_code(bytes(bad), image)
        b = restart.pinned_image("B")[1]
        with self.assertRaises(RuntimeError): restart.verify_active_code(b, b)

    def test_group_wiring_record_does_not_change_sample_or_supply_gates(self):
        argv = ["sample", "--power-on", "--both-ground-confirmed", "--pa0-measured-volts", "0",
                "--pa1-measured-volts", "0", "--upper-three-disconnected"]
        with patch.object(sys, "argv", argv), patch.object(sample.parallel, "main") as run:
            sample.main()
        call = run.call_args.kwargs
        self.assertEqual(call["sample_command"], "ADC PAR SAMPLE ON")
        self.assertIn("UPPER_DISCONNECTED", call["capture_label"])
        self.assertIn("UL/VL/WL connected", call["raw_mapping"]["CONTROL_WIRING_USER_CONFIRMED"])
        self.assertEqual(call["supply_checker"].keywords, {"power": "ON"})
        self.assertTrue(call["quiet_acquisition"])

    def test_lower_group_and_contradictory_wiring_flags(self):
        argv = ["sample", "--power-on", "--both-ground-confirmed", "--pa0-measured-volts", "0",
                "--pa1-measured-volts", "0", "--lower-three-disconnected"]
        with patch.object(sys, "argv", argv), patch.object(sample.parallel, "main") as run:
            sample.main()
        call = run.call_args.kwargs
        self.assertEqual(call["sample_command"], "ADC PAR SAMPLE ON")
        self.assertIn("LOWER_DISCONNECTED", call["capture_label"])
        self.assertIn("UH/VH/WH connected", call["raw_mapping"]["CONTROL_WIRING_USER_CONFIRMED"])
        self.assertEqual(call["supply_checker"].keywords, {"power": "ON"})
        with patch.object(sys, "argv", argv + ["--upper-three-disconnected"]), \
                patch.object(sample.parallel, "main") as run:
            with self.assertRaises(SystemExit): sample.main()
            run.assert_not_called()

    def test_latest_upper_batch_admissible_and_lower_reset_record(self):
        latest = (DIR / "capture-1791710869176412900.json",
                  DIR / "readback-1791710895811725900.json")
        evidence = [self.evidence()[0], *[json.loads(p.read_text(encoding="utf-8")) for p in latest]]
        self.assertEqual(restart.prior_identity(*evidence), ("A", "399", "CE182877", "ON"))
        base = ["restart"]
        for name, p in zip(("deployment", "capture", "readback"), (FILES[0], *latest)):
            base.extend(("--" + name, str(p)))
        flags = ["--allow-one-reset", "--drive-12v-off", "--motor-leads-disconnected",
                 "--both-ground-confirmed", "--lower-three-disconnected"]
        with patch.object(sys, "argv", base + flags + ["--upper-three-disconnected"]), \
                patch.object(restart.subprocess, "run") as run:
            with self.assertRaises(SystemExit): restart.main()
            run.assert_not_called()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, "argv", base + flags), patch.object(restart, "OUTPUT", Path(directory)), \
                patch.object(restart.subprocess, "run", side_effect=RuntimeError("Stop before first check")):
            with self.assertRaisesRegex(RuntimeError, "Stop before"):
                restart.main()
            saved = json.loads(next(Path(directory).glob("lower-disconnected-reset-*.json")).read_text(encoding="utf-8"))
            self.assertEqual(saved["reset_commands"], 0)
            self.assertEqual(saved["wiring_user_confirmed"],
                             {"UH_VH_WH": "connected", "UL_VL_WL": "disconnected", "common_ground": "unchanged"})

    def test_lower_chain_audit_rejects_wrong_group_and_stale_prior(self):
        paths = {
            "deployment": FILES[0], "baseline": FILES[1], "baseline-readback": FILES[2],
            "group": DIR / "capture-1791711310967778400.json",
            "group-readback": DIR / "readback-1791711338226637500.json",
            "reset": DIR / "lower-disconnected-reset-1791711235561530000.json",
            "prior-capture": DIR / "capture-1791710869176412900.json",
            "prior-readback": DIR / "readback-1791710895811725900.json"}
        with tempfile.TemporaryDirectory() as directory:
            paths["output"] = Path(directory) / "audit.json"
            argv = ["audit"]
            for name, path in paths.items(): argv.extend(("--" + name, str(path)))
            with patch.object(sys, "argv", argv + ["--disconnected-group", "lower"]):
                group_audit.main()
            result = json.loads(paths["output"].read_text(encoding="utf-8"))
            group = result["lower_three_disconnected"]
            self.assertEqual(group["paired_nonzero_count"], 2)
            self.assertEqual(group["common_strictly_above_20"], 0)
            self.assertEqual(len(group["nonzero_events"]), 3)
            with patch.object(sys, "argv", argv + ["--disconnected-group", "upper"]):
                with self.assertRaises(RuntimeError): group_audit.main()
            paths["prior-capture"] = FILES[1]; paths["prior-readback"] = FILES[2]
            argv = ["audit"]
            for name, path in paths.items(): argv.extend(("--" + name, str(path)))
            with patch.object(sys, "argv", argv + ["--disconnected-group", "lower"]):
                with self.assertRaises(RuntimeError): group_audit.main()

    def test_single_control_sampler_records_exact_other_five_and_rejects_conflicts(self):
        for control in ("UL", "VL", "WL"):
            argv = ["sample", "--power-on", "--both-ground-confirmed", "--pa0-measured-volts", "0",
                    "--pa1-measured-volts", "0", "--only-disconnected-control", control]
            with patch.object(sys, "argv", argv), patch.object(sample.parallel, "main") as run:
                sample.main()
            call = run.call_args.kwargs
            self.assertEqual(call["sample_command"], "ADC PAR SAMPLE ON")
            self.assertEqual(call["raw_mapping"]["CONTROL_WIRING_USER_CONFIRMED"], sample.single_control_description(control))
            self.assertIn("ONLY_" + control + "_DISCONNECTED", call["capture_label"])
            self.assertEqual(call["supply_checker"].keywords, {"power": "ON"})
            self.assertTrue(call["quiet_acquisition"])
            for conflict in ("--upper-three-disconnected", "--lower-three-disconnected", "--all-six-connected"):
                with patch.object(sys, "argv", argv + [conflict]), patch.object(sample.parallel, "main") as run:
                    with self.assertRaises(SystemExit): sample.main()
                    run.assert_not_called()
        with self.assertRaises(ValueError): sample.single_control_description("UH")

    def test_exact_lower_prior_and_single_reset_record_before_any_mutation(self):
        latest = (DIR / "capture-1791711310967778400.json",
                  DIR / "readback-1791711338226637500.json")
        evidence = [self.evidence()[0], *[json.loads(p.read_text(encoding="utf-8")) for p in latest]]
        self.assertEqual(restart.prior_identity(*evidence), ("A", "399", "93D2382B", "ON"))
        base = ["restart"]
        for name, p in zip(("deployment", "capture", "readback"), (FILES[0], *latest)):
            base.extend(("--" + name, str(p)))
        flags = ["--allow-one-reset", "--drive-12v-off", "--motor-leads-disconnected",
                 "--both-ground-confirmed", "--only-disconnected-control", "UL"]
        for conflict in ("--upper-three-disconnected", "--lower-three-disconnected", "--all-six-connected"):
            with patch.object(sys, "argv", base + flags + [conflict]), patch.object(restart.subprocess, "run") as run:
                with self.assertRaises(SystemExit): restart.main()
                run.assert_not_called()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, "argv", base + flags), patch.object(restart, "OUTPUT", Path(directory)), \
                patch.object(restart.subprocess, "run", side_effect=RuntimeError("Stop before first check")):
            with self.assertRaisesRegex(RuntimeError, "Stop before"):
                restart.main()
            saved = json.loads(next(Path(directory).glob("only-ul-disconnected-reset-*.json")).read_text(encoding="utf-8"))
            self.assertEqual(saved["reset_commands"], 0)
            self.assertEqual(saved["wiring_user_confirmed"]["per_control_wire"],
                             {"UH": "connected", "VH": "connected", "WH": "connected", "UL": "disconnected",
                              "VL": "connected", "WL": "connected"})

    def test_single_wire_audit_checks_all_six_not_just_selected_label(self):
        wiring = {"UH_VH_WH": "connected", "UL_VL_WL": "mixed", "common_ground": "unchanged",
                  "disconnected_control": "UL", "per_control_wire":
                  {"UH": "connected", "VH": "connected", "WH": "connected", "UL": "disconnected",
                   "VL": "connected", "WL": "connected"}}
        description = sample.single_control_description("UL")
        self.assertTrue(group_audit.single_wiring_matches(description, wiring, "UL"))
        for control in wiring["per_control_wire"]:
            bad = copy.deepcopy(wiring)
            bad["per_control_wire"][control] = "connected" if control == "UL" else "disconnected"
            self.assertFalse(group_audit.single_wiring_matches(description, bad, "UL"))
        self.assertFalse(group_audit.single_wiring_matches(sample.single_control_description("VL"), wiring, "UL"))
        bad = copy.deepcopy(wiring); bad["common_ground"] = "changed"
        self.assertFalse(group_audit.single_wiring_matches(description, bad, "UL"))

    def test_offline_saved_binary_audit_and_corruption_rejection(self):
        deployment = self.evidence()[0]
        good = group_audit.audit(deployment, FILES[1], FILES[2])
        self.assertEqual(good["common_strictly_above_20"], 1)
        self.assertEqual(good["nonzero_events"][0]["index"], 2369)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "readback.json"
            path.write_bytes(FILES[2].read_bytes())
            path.with_suffix(".active-code.bin").write_bytes(FILES[2].with_suffix(".active-code.bin").read_bytes())
            raw = bytearray(FILES[2].with_suffix(".raw.bin").read_bytes())
            raw[10] ^= 1
            path.with_suffix(".raw.bin").write_bytes(raw)
            with self.assertRaisesRegex(RuntimeError, "RAM binary identity"):
                group_audit.audit(deployment, FILES[1], path)

    def test_no_mutating_actions_before_admission_and_no_reset_retry(self):
        base = ["restart"]
        for name, p in zip(("deployment", "capture", "readback"), FILES):
            base.extend(("--" + name, str(p)))
        flags = ["--allow-one-reset", "--drive-12v-off", "--motor-leads-disconnected",
                 "--both-ground-confirmed", "--upper-three-disconnected"]
        for flag in flags:
            with patch.object(sys, "argv", base + [f for f in flags if f != flag]), \
                    patch.object(restart.subprocess, "run") as run:
                with self.assertRaises(SystemExit): restart.main()
                run.assert_not_called()

        class UART:
            sample_commands = 0
            lines = []
            def __init__(self, port): pass
            def query(self, command, *args):
                evidence = restart_tests[1]
                row = evidence["after_fw"] if command == "FW STATUS" else evidence["after_zero"]
                return "1 OK " + " ".join(f"{k}={v}" for k, v in row.items())
            def raw_query(self, command):
                row = restart_tests[1]["terminal"]
                return "1 OK ADC3PAR " + " ".join(f"{k}={v}" for k, v in row.items())

        restart_tests = self.evidence()
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            if "-u" in command:
                Path(command[-1]).write_bytes(restart.pinned_image("A")[1])
            if "-rst" in command:
                raise RuntimeError("Uncertain reset acknowledgement")
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, "argv", base + flags), \
                patch.object(restart, "OUTPUT", Path(directory)), \
                patch.object(restart.subprocess, "run", side_effect=run), \
                patch.object(restart, "require_registers", return_value={}), \
                patch.object(restart, "read_pin_registers", return_value={}), \
                patch.object(restart, "ReferenceUart", UART), \
                patch("serial.Serial"), patch.object(restart.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "Uncertain"):
                restart.main()
            evidence = json.loads(next(Path(directory).glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(evidence["reset_commands"], 1)
            self.assertEqual(evidence["sample_commands"], 0)
            self.assertFalse(evidence["pass"])
            sleep.assert_not_called()
        self.assertEqual(sum("-rst" in c for c in commands), 1)
        for command in commands:
            self.assertFalse(any(arg in command for arg in ("-w", "-w32", "-halt", "-e", "-d")))


if __name__ == "__main__": unittest.main()
