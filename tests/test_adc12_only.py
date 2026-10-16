"""Actual C adapter scenarios and strict identity/integrity/admission tests."""
import copy
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
import zlib
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import adc12_only_report as report
import adc12_only_sample as sample
import adc12_only_acceptance as deploy
import adc12_only_readback as readback
import adc_pa1_only_readback as shared_readback
import adc_sampletime_acceptance as old_a
import zero_async_clock_acceptance as baseline
from tests.test_adc_pa1_only import status as single_status


def status(crc=0):
    return ("1 OK ADC3PAR MODE=ADC12_ONLY CAPTURE_MASK=3 CH=2 REAL_W=0 PAD_W=ZERO_UNSAMPLED "
            "W_READY=1 SYNC=COMMON_EVENT LOCK=1 SD=0 MOE=0 CCER=0 CEN=0 FOC=0 STATE=4 REASON=0 "
            "NU=4096 NV=4096 NW=0 IRQ=1,1,0 ERR=0,0,0 RESTORE=1 SMP_CYCLES=247.5 SMP_CHECK=3 "
            f"RANGE=1000:1000,2048:2048,0:0 CRC={crc:08X} CAP=4096")


class Adc12Tests(unittest.TestCase):
    def test_exact_inactive_a_and_b_fallback(self):
        a = old_a.pinned_image("A")[1]; b = deploy.pinned_image("B")[1]
        new_a = deploy.pinned_image("A")[1]
        self.assertEqual(deploy.image_info(new_a)[0], "A")
        data = bytearray(b"\xff" * 0x80000)
        data[0x8000:0x8000+len(a)] = a; data[0x40000:0x40000+len(b)] = b
        meta = (0,0,2,0,0,390,len(a),zlib.crc32(a),len(b),zlib.crc32(b))
        with patch.object(baseline, "latest_meta", return_value=meta):
            self.assertEqual(deploy.diagnostic_baseline(data)["current"], "B")
            data[0x40010] ^= 1
            with self.assertRaises(RuntimeError): deploy.diagnostic_baseline(data)
        with patch.object(baseline, "latest_meta", return_value=meta[:2]+(1,)+meta[3:]):
            with self.assertRaises(RuntimeError): deploy.diagnostic_baseline(data)

    def test_actual_adapter(self):
        directory = ROOT / "tests/adc12_build"; directory.mkdir(exist_ok=True)
        exe = directory / "adapter.exe"
        subprocess.run([r"D:\Qt\Tools\mingw1310_64\bin\gcc.exe", "-std=c11", "-O2", "-Wall",
                        "-Wextra", "-Werror", "-pedantic", "-UNDEBUG", "-I", str(ROOT / "tests/adc_dma_mock"),
                        "-I", str(ROOT / "firmware_common"), str(ROOT / "tests/adc12_adapter_host.c"),
                        str(ROOT / "firmware_common/adc_raw_report.c"), "-o", str(exe)], check=True)
        for case in list(range(21)) + list(range(101,111)) + list(range(211,219)):
            with self.subTest(case=case):
                subprocess.run([str(exe), str(case)], check=True, capture_output=True)

    def test_identity_padding_crc_range(self):
        triples = [(1000,2048,0)] * 4096
        crc = zlib.crc32(struct.pack("<HHH",1000,2048,0) * 4096)
        self.assertEqual(report.verify_capture(status(crc),triples), f"{crc:08X}")
        self.assertFalse(report.analyze(triples)["real_w_sampled"])
        self.assertEqual(report.analyze(triples)["V_odd_zero_based"]["exact_2048"],2048)
        for bad in (single_status(), status().replace("CAPTURE_MASK=3","CAPTURE_MASK=7"),
                    status().replace("IRQ=1,1,0","IRQ=1,1,1"), status().replace("SMP_CHECK=3","SMP_CHECK=7"),
                    status().replace("SD=0","SD=1"), status().replace("NW=0","NW=4096")):
            with self.assertRaises(ValueError): report.require_status(bad,terminal=True)
        for bad in (triples[:-1], [(1000,2048,1)] + triples[1:], [(1001,2048,0)] + triples[1:],
                    [(4096,2048,0)] + triples[1:], [(1000,True,0)] + triples[1:]):
            with self.assertRaises(ValueError): report.verify_capture(status(crc),bad)
        with self.assertRaises(ValueError): report.verify_capture(status(crc).replace("1000:1000","999:1000"),triples)

    def test_deployment_and_wrappers(self):
        raw={"MODE":"ADC12_ONLY","CAPTURE_MASK":"3","CH":"2","REAL_W":"0",
             "PAD_W":"ZERO_UNSAMPLED","SMP_CYCLES":"247.5","SMP_CHECK":"0"}
        evidence={"pass":True,"inspect_only":False,"profile":deploy.PROFILE,"target_slot":"A",
                  "image_sha256":deploy.PINNED["A"],"motion_commands":False,"sampling_commands":False,
                  "force_confirm":False,"direct_metadata_write":False,"physical_drive_off_user_confirmed":True,
                  "final_flash":{"all_protected_regions_unchanged":True},
                  "three_phase_service":{"zero":{"ADC_OWNER":"1"},"raw":raw},
                  "final_fw":{"CURRENT":"A","CONFIRMED":"A","PENDING":"-","ATTEMPTS":"0","ACTIVE":"0","GEN":"393"}}
        self.assertEqual(sample.deployment_identity(evidence),("A","393"))
        for key in raw:
            bad=copy.deepcopy(evidence); bad["three_phase_service"]["raw"][key]="wrong"
            with self.assertRaises(RuntimeError): sample.deployment_identity(bad)
        with patch.object(sample.parallel,"main") as run:
            sample.main(); self.assertIs(run.call_args.kwargs["capture_verifier"],report.verify_capture)
        with patch.object(readback.readback,"main") as run:
            readback.main(); self.assertEqual(run.call_args.kwargs["expected_slot"],"A")
            self.assertEqual(run.call_args.kwargs["capture_mask"],3)
            self.assertIs(run.call_args.kwargs["capture_verifier"],report.verify_capture)

    def test_invalid_capture_rejected_before_probe(self):
        # Default PA1 readback and ADC12 wrapper must both fail closed before CLI.
        with patch.object(sys,"argv",["readback","--capture","unused.json"]), \
             patch.object(Path,"read_text",return_value='{}'), \
             patch.object(shared_readback.subprocess,"run") as cli:
            with self.assertRaises(RuntimeError): shared_readback.main()
            with self.assertRaises(RuntimeError): readback.main()
            cli.assert_not_called()

if __name__ == "__main__": unittest.main()
