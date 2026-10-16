"""Strict reference identity, real supply checks, no-retry host and actual console."""
import copy
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
import zlib
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import adc_reference_acceptance as deploy
import adc_reference_sample as sample
import adc_reference_report as report
import adc_reference_readback as readback
import zero_async_clock_acceptance as baseline
from tests.test_adc12_only import status as old_status
import adc_reference_restart as restart

WIRING = ["--same-divider-confirmed", "--pa0-measured-volts", "1.6", "--pa1-measured-volts", "1.6"]


def status(power="OFF", bus=0, crc=0):
    return (old_status(crc).replace("MODE=ADC12_ONLY", "MODE=ADC12_REFERENCE") +
            f" SUPPLY_POLICY=EXPLICIT_OFF_ON POWER={power} ADMIT_MV={bus}")


class ReferenceToolsTests(unittest.TestCase):
    def test_console_actual_command_routes_and_bounded_format(self):
        directory = ROOT / "tests/adc12_build"; directory.mkdir(exist_ok=True)
        exe = directory / "reference_console.exe"
        subprocess.run([r"D:\Qt\Tools\mingw1310_64\bin\gcc.exe", "-std=c11", "-O2", "-Wall",
                        "-Wextra", "-Werror", "-pedantic", "-UNDEBUG", "-I", str(ROOT / "tests/adc_dma_mock"),
                        str(ROOT / "tests/adc_reference_console_host.c"), "-o", str(exe)], check=True)
        for n in range(8):
            subprocess.run([str(exe), str(n)], check=True, capture_output=True)

    def test_pinned_images_and_only_inactive_b_admission(self):
        a = deploy.pinned_image("A")[1]; b = deploy.fallback.pinned_image("B")[1]
        self.assertEqual(deploy.image_info(deploy.pinned_image("B")[1])[0], "B")
        data = bytearray(b"\xff" * 0x80000)
        data[0x8000:0x8000 + len(a)] = a; data[0x40000:0x40000 + len(b)] = b
        meta = (0,0,1,0,0,393,len(a),zlib.crc32(a),len(b),zlib.crc32(b))
        with patch.object(baseline, "latest_meta", return_value=meta):
            self.assertEqual(deploy.diagnostic_baseline(data)["current"], "A")
            data[0x8010] ^= 1
            with self.assertRaises(RuntimeError): deploy.diagnostic_baseline(data)
        with patch.object(baseline, "latest_meta", return_value=meta[:2]+(2,)+meta[3:]):
            with self.assertRaises(RuntimeError): deploy.diagnostic_baseline(data)

    def test_strict_identity_supply_and_integrity(self):
        triples = [(1000,2048,0)] * 4096
        crc = zlib.crc32(struct.pack("<HHH",1000,2048,0) * 4096)
        self.assertEqual(report.verify_capture(status(crc=crc), triples, power="OFF"), f"{crc:08X}")
        report.require_status(status("ON",12000), terminal=True, power="ON")
        for line in (old_status(), status("NONE",0), status("OFF",1001), status("ON",9999),
                     status("ON",14001), status().replace("LOCK=1","LOCK=0"),
                     status().replace("SUPPLY_POLICY=EXPLICIT_OFF_ON","SUPPLY_POLICY=ANY"),
                     status().replace("IRQ=1,1,0","IRQ=1,0,0"), status().replace("SMP_CHECK=3","SMP_CHECK=0")):
            with self.assertRaises(ValueError): report.require_status(line,terminal=True)
        with self.assertRaises(ValueError): report.verify_capture(status(crc=crc),triples[:-1])
        with self.assertRaises(ValueError): report.verify_capture(status(crc=crc),[(1001,2048,0)] + triples[1:])
        with self.assertRaises(ValueError): report.require_status(status(),power="ON")

    def test_actual_supply_estimate_never_fabricated(self):
        line = "9 OK ANALOG VOLT VALID=1 PROTECT=0 VDDA_BOOT_MV=3280 AGE_MS=10 VBUS_EST_MV="
        for bus in (0,1000): report.require_supply(line+str(bus),"OFF")
        for bus in (10000,14000): report.require_supply(line+str(bus),"ON")
        for power,bus in (("OFF",1001),("OFF",12000),("ON",0),("ON",9999),("ON",14001)):
            with self.assertRaises(ValueError): report.require_supply(line+str(bus),power)
        for bad in ((line+"0").replace("VALID=1","VALID=0"),
                    (line+"0").replace("3280","2999"),(line+"0").replace("AGE_MS=10","AGE_MS=501"),
                    (line+"0").replace("PROTECT=0","PROTECT=1")):
            with self.assertRaises(ValueError): report.require_supply(bad,"OFF")

    def test_uart_explicit_only_and_no_resend(self):
        port = Mock(); uart = sample.ReferenceUart(port)
        uart.read_line = lambda _: f"{uart.request} OK ADC3PAR"
        uart.raw_query("ADC PAR SAMPLE OFF")
        with self.assertRaises(RuntimeError): uart.raw_query("ADC PAR SAMPLE ON")
        self.assertEqual(port.write.call_count,1)
        for bad in ("ADC PAR SAMPLE", "START", "ZERO SAMPLE", "ADC PAR SAMPLE ON extra"):
            with self.assertRaises(ValueError): sample.ReferenceUart(Mock()).raw_query(bad)
        port = Mock(); uart = sample.ReferenceUart(port); uart.read_line = lambda _: None
        with self.assertRaises(TimeoutError): uart.raw_query("ADC PAR SAMPLE ON",timeout=.001)
        with self.assertRaises(RuntimeError): uart.raw_query("ADC PAR SAMPLE ON")
        self.assertEqual(port.write.call_count,1)

    def test_wrapper_correct_requests_and_physical_conditions_before_probe(self):
        for power in ("off","on"):
            with patch.object(sys,"argv",["sample","--power-"+power,*WIRING]), patch.object(sample.parallel,"main") as run:
                sample.main()
                self.assertEqual(run.call_args.kwargs["sample_command"],"ADC PAR SAMPLE "+power.upper())
                self.assertTrue(run.call_args.kwargs["quiet_acquisition"])
                self.assertIs(run.call_args.kwargs["uart_factory"],sample.ReferenceUart)
        with patch.object(readback.readback,"main") as run:
            readback.main(); self.assertEqual(run.call_args.kwargs["expected_slot"],"B")
        for power,wrong in (("off","--supply-12v-0p5a-no-alarm"),("on","--drive-12v-off")):
            argv=["sample","--power-"+power,*WIRING,"--deployment-evidence","unused.json",
                  "--allow-sample","--motor-leads-disconnected",wrong]
            with patch.object(sys,"argv",argv), patch.object(sample.parallel.subprocess,"run") as cli, \
                 patch.object(Path,"read_text") as read:
                with self.assertRaises(SystemExit): sample.main()
                cli.assert_not_called(); read.assert_not_called()

    def test_missing_known_reference_or_bad_reset_evidence_prevents_io(self):
        with patch.object(sys,"argv",["sample","--power-off"]), patch.object(sample.parallel,"main") as run:
            with self.assertRaises(SystemExit): sample.main()
            run.assert_not_called()
        with self.assertRaises(RuntimeError): restart.prior_identity({}, {}, {})

    def test_deployment_identity_cannot_accept_legacy(self):
        raw={"MODE":"ADC12_REFERENCE","CAPTURE_MASK":"3","CH":"2","REAL_W":"0",
             "PAD_W":"ZERO_UNSAMPLED","SMP_CYCLES":"247.5","SMP_CHECK":"0",
             "SUPPLY_POLICY":"EXPLICIT_OFF_ON","POWER":"NONE","ADMIT_MV":"0"}
        evidence={"pass":True,"inspect_only":False,"profile":deploy.PROFILE,"target_slot":"B",
                  "image_sha256":deploy.PINNED["B"],"motion_commands":False,"sampling_commands":False,
                  "force_confirm":False,"direct_metadata_write":False,"physical_drive_off_user_confirmed":True,
                  "final_flash":{"all_protected_regions_unchanged":True},
                  "three_phase_service":{"zero":{"ADC_OWNER":"1"},"raw":raw},
                  "final_fw":{"CURRENT":"B","CONFIRMED":"B","PENDING":"-","ATTEMPTS":"0","ACTIVE":"0","GEN":"394"}}
        self.assertEqual(sample.deployment_identity(evidence),("B","394"))
        for key in raw:
            bad=copy.deepcopy(evidence); bad["three_phase_service"]["raw"][key]="wrong"
            with self.assertRaises(RuntimeError): sample.deployment_identity(bad)


if __name__ == "__main__": unittest.main()
