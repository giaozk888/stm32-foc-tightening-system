"""Offline actual adapter, single-channel identity and complete raw integrity gates."""
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
import adc_pa1_only_report as report
import adc_pa1_only_sample as sample
import adc_pa1_only_acceptance as deploy
import adc_owner_acceptance as owner
import zero_async_clock_acceptance as baseline
from tests.test_adc_parallel import status as triple_status

def status(crc=0):
    return ("1 OK ADC3PAR MODE=PA1_ONLY CAPTURE_MASK=2 CH=1 REAL_W=0 PAD_UW=ZERO_UNSAMPLED "
            "W_READY=1 SYNC=SINGLE LOCK=1 SD=0 MOE=0 CCER=0 CEN=0 FOC=0 STATE=4 REASON=0 "
            "NU=0 NV=4096 NW=0 IRQ=0,1,0 ERR=0,0,0 RESTORE=1 SMP_CYCLES=247.5 SMP_CHECK=2 "
            f"RANGE=0:0,2048:2048,0:0 CRC={crc:08X} CAP=4096")

class Pa1Tests(unittest.TestCase):
    def test_exact_inactive_b_and_a_fallback(self):
        a = deploy.pinned_image("A")[1]
        b = owner.pinned_image("B")[1]
        new_b = deploy.pinned_image("B")[1]
        self.assertEqual(deploy.image_info(new_b)[0], "B")
        data = bytearray(b"\xff" * 0x80000)
        data[0x8000:0x8000+len(a)] = a
        data[0x40000:0x40000+len(b)] = b
        meta = (0,0,1,0,0,387,len(a),zlib.crc32(a),len(b),zlib.crc32(b))
        with patch.object(baseline,"latest_meta",return_value=meta):
            self.assertEqual(deploy.diagnostic_baseline(data)["current"],"A")
            data[0x40010] ^= 1
            with self.assertRaises(RuntimeError): deploy.diagnostic_baseline(data)
        with patch.object(baseline,"latest_meta",return_value=meta[:2]+(2,)+meta[3:]):
            with self.assertRaises(RuntimeError): deploy.diagnostic_baseline(data)

    def test_actual_adapter(self):
        directory = ROOT / "tests/adc_pa1_build"; directory.mkdir(exist_ok=True)
        exe = directory / "adapter.exe"
        subprocess.run([r"D:\Qt\Tools\mingw1310_64\bin\gcc.exe", "-std=c11", "-O2", "-Wall",
                        "-Wextra", "-Werror", "-pedantic", "-UNDEBUG", "-I", str(ROOT / "tests/adc_dma_mock"),
                        "-I", str(ROOT / "firmware_common"), str(ROOT / "tests/adc_pa1_adapter_host.c"),
                        str(ROOT / "firmware_common/adc_raw_report.c"), "-o", str(exe)], check=True)
        for case in list(range(11)) + list(range(101,107)) + list(range(207,214)):
            with self.subTest(case=case):
                subprocess.run([str(exe), str(case)], check=True, capture_output=True)

    def test_identity_padding_crc_and_range(self):
        triples = [(0,2048,0)] * 4096
        crc = zlib.crc32(struct.pack("<HHH",0,2048,0) * 4096)
        self.assertEqual(report.verify_capture(status(crc),triples), f"{crc:08X}")
        self.assertFalse(report.analyze(triples)["real_w_sampled"])
        self.assertEqual(report.analyze(triples)["odd_zero_based"]["exact_2048"],2048)
        for bad in (triple_status(), status().replace("CAPTURE_MASK=2","CAPTURE_MASK=7"),
                    status().replace("IRQ=0,1,0","IRQ=1,1,1"), status().replace("SMP_CHECK=2","SMP_CHECK=7"),
                    status().replace("SD=0","SD=1"), status().replace("NW=0","NW=4096")):
            with self.assertRaises(ValueError): report.require_status(bad,terminal=True)
        for bad in (triples[:-1], [(1,2048,0)] + triples[1:], [(0,2049,0)] + triples[1:]):
            with self.assertRaises(ValueError): report.verify_capture(status(crc), bad)
        with self.assertRaises(ValueError): report.verify_capture(status(crc).replace("2048:2048","2000:2048"),triples)

    def test_deployment_and_wrapper(self):
        raw={"MODE":"PA1_ONLY","CAPTURE_MASK":"2","CH":"1","REAL_W":"0",
             "PAD_UW":"ZERO_UNSAMPLED","SMP_CYCLES":"247.5","SMP_CHECK":"0"}
        evidence={"pass":True,"inspect_only":False,"profile":deploy.PROFILE,"target_slot":"B",
                  "image_sha256":deploy.PINNED["B"],"motion_commands":False,"sampling_commands":False,
                  "force_confirm":False,"direct_metadata_write":False,"physical_drive_off_user_confirmed":True,
                  "final_flash":{"all_protected_regions_unchanged":True},
                  "three_phase_service":{"zero":{"ADC_OWNER":"1"},"raw":raw},
                  "final_fw":{"CURRENT":"B","CONFIRMED":"B","PENDING":"-","ATTEMPTS":"0","ACTIVE":"0","GEN":"390"}}
        self.assertEqual(sample.deployment_identity(evidence),("B","390"))
        for key in raw:
            bad=copy.deepcopy(evidence); bad["three_phase_service"]["raw"][key]="wrong"
            with self.assertRaises(RuntimeError): sample.deployment_identity(bad)
        with patch.object(sample.parallel,"main") as run:
            sample.main(); self.assertIs(run.call_args.kwargs["capture_verifier"],report.verify_capture)
            self.assertIs(run.call_args.kwargs["capture_analyzer"],report.analyze)

if __name__ == "__main__": unittest.main()
