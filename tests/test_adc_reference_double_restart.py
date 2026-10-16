"""Offline admission tests; no device access."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import adc_reference_double_restart as restart
import adc_reference_double_sample as sample
import adc_reference_double_sensor_sample as sensor

DIR = ROOT / "safety_backups/adc-reference-double-live-20261011"
FILES = (DIR / "deployment-1791719157907882500.json",
         DIR / "capture-1791719550389717900.json",
         DIR / "readback-1791719585497316100.json")


class DoubleRestartTests(unittest.TestCase):
    def evidence(self):
        return [json.loads(p.read_text(encoding="utf-8")) for p in FILES]

    def test_prior_full_batch_and_saved_binaries(self):
        self.assertEqual(restart.prior_identity(*self.evidence()), ("B", "402", "01E70AA4", "ON"))
        restart.audit_saved_files(FILES[1], FILES[2])

    def test_bad_evidence_rejected(self):
        for index, key, value in ((1,"sample_commands",2), (1,"reset",True),
                (1,"sha256","bad"), (2,"bytes",24576), (2,"halt",True),
                (2,"mismatched_entries",1), (2,"slot","A"), (2,"crc32","00000000")):
            evidence = self.evidence(); evidence[index][key] = value
            with self.subTest(key=key), self.assertRaises((RuntimeError,ValueError)):
                restart.prior_identity(*evidence)
        evidence = self.evidence(); evidence[1]["triples"][-1][0] = 1
        with self.assertRaises(ValueError): restart.prior_identity(*evidence)
        evidence = self.evidence(); evidence[2]["after_status"]["fw"]["GEN"] = "401"
        with self.assertRaises(RuntimeError): restart.prior_identity(*evidence)

    def test_wrong_image_and_corrupt_saved_ram(self):
        image = restart.pinned_image("B")[1]
        restart.verify_active_code(image, image)
        with self.assertRaises(RuntimeError): restart.verify_active_code(image[:-1], image)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"readback.json"
            path.write_bytes(FILES[2].read_bytes())
            path.with_suffix(".active-code.bin").write_bytes(image)
            raw = bytearray(FILES[2].with_suffix(".raw.bin").read_bytes()); raw[-1] ^= 1
            path.with_suffix(".raw.bin").write_bytes(raw)
            with self.assertRaisesRegex(RuntimeError,"RAM length/hash"):
                restart.audit_saved_files(FILES[1], path)

    def test_wl_sampler_and_conflicting_wiring(self):
        argv = ["sample", "--both-ground-confirmed", "--only-disconnected-control", "WL"]
        with patch.object(sys,"argv",argv), patch.object(sample.parallel,"main") as run:
            sample.main()
        options = run.call_args.kwargs
        self.assertEqual(options["capacity"],8192)
        self.assertEqual(options["quiet_wait_seconds"],1.)
        self.assertEqual(options["sample_command"],"ADC PAR SAMPLE ON")
        self.assertEqual(options["supply_checker"].keywords,{"power":"ON"})
        self.assertIn("ONLY WL disconnected",options["raw_mapping"]["CONTROL_WIRING_USER_CONFIRMED"])
        with patch.object(sys,"argv",argv+["--all-six-connected"]), patch.object(sample.parallel,"main") as run:
            with self.assertRaises(SystemExit): sample.main()
            run.assert_not_called()

    def test_wrapper_supplies_exact_b_validators(self):
        argv=["restart","--capture",str(FILES[1]),"--readback",str(FILES[2])]
        with patch.object(sys,"argv",argv), patch.object(restart.shared,"main") as run:
            restart.main()
        self.assertIs(run.call_args.kwargs["prior_checker"],restart.prior_identity)
        self.assertIs(run.call_args.kwargs["fresh_checker"],restart.require_fresh_double)
        self.assertIs(run.call_args.kwargs["status_checker"],restart.require_status)

    def test_ground_replacement_records_change_without_changing_capture_gates(self):
        argv=["sample","--both-ground-confirmed","--all-six-connected","--common-ground-replaced"]
        with patch.object(sys,"argv",argv), patch.object(sample.parallel,"main") as run:
            sample.main()
        options=run.call_args.kwargs
        self.assertEqual(options["capacity"],8192)
        self.assertEqual(options["sample_command"],"ADC PAR SAMPLE ON")
        self.assertEqual(options["supply_checker"].keywords,{"power":"ON"})
        self.assertIn("only existing inter-board signal GND replaced",options["raw_mapping"]["CONTROL_WIRING_USER_CONFIRMED"])
        with patch.object(sys,"argv",["sample","--both-ground-confirmed","--only-disconnected-control","WL","--common-ground-replaced"]), patch.object(sample.parallel,"main") as run:
            with self.assertRaises(SystemExit): sample.main()
            run.assert_not_called()

    def test_sensor_wiring_is_not_recorded_as_grounded(self):
        argv=["sensor","--iu-iv-connected","--all-six-connected","--common-ground-replaced",
              "--diagnostic-ground-resistors-removed"]
        with patch.object(sys,"argv",argv), patch.object(sensor.parallel,"main") as run:
            sensor.main()
        options=run.call_args.kwargs
        self.assertEqual(options["capacity"],8192)
        self.assertEqual(options["sample_command"],"ADC PAR SAMPLE ON")
        self.assertEqual(options["supply_checker"].keywords,{"power":"ON"})
        self.assertIn("not grounded",options["raw_mapping"]["U"])
        self.assertEqual(options["csv_headers"][2],"PA0_IU_SENSOR_RAW")
        for flag in argv[1:]:
            with patch.object(sys,"argv",[a for a in argv if a != flag]), patch.object(sensor.parallel,"main") as run:
                with self.assertRaises(SystemExit): sensor.main()
                run.assert_not_called()


if __name__ == "__main__": unittest.main()
