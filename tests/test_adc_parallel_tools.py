"""Offline gate tests, never invokes UART/SWD or sampling."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import adc_parallel_acceptance as deploy
import adc_parallel_sample as sample
import adc_parallel_clock as clock
import zero_async_clock_acceptance as baseline
class ToolsTests(unittest.TestCase):
    def test_pinned_artifacts_and_locked_fallback_gate(self):
        for slot in "AB": self.assertEqual(deploy.image_info(deploy.pinned_image(slot)[1])[0],slot)
        a=(ROOT/"foc2_app_a/build/AdcDmaRaw20261009/foc2.bin").read_bytes()
        b=(ROOT/"foc2_app_b/build/AdcThreePhase20261010/foc2.bin").read_bytes()
        data=bytearray(b"\xff"*0x80000); data[0x8000:0x8000+len(a)]=a; data[0x40000:0x40000+len(b)]=b
        meta=(0,0,2,0,0,378,len(a),zlib.crc32(a),len(b),zlib.crc32(b))
        with patch.object(baseline,"latest_meta",return_value=meta):
            self.assertEqual(deploy.diagnostic_baseline(data)["current"],"B")
        for changed in (meta[:3]+(1,)+meta[4:],meta[:2]+(0,)+meta[3:]):
            with patch.object(baseline,"latest_meta",return_value=changed):
                with self.assertRaises(RuntimeError): deploy.diagnostic_baseline(data)
        data[0x8010]^=1
        with patch.object(baseline,"latest_meta",return_value=meta):
            with self.assertRaises(RuntimeError): deploy.diagnostic_baseline(data)
    def test_no_repeated_sample_or_legacy_command(self):
        class Port:
            def __init__(self): self.writes=[]
            def write(self,data): self.writes.append(data)
        p=Port(); uart=deploy.ParallelUart(p)
        with self.assertRaises(TimeoutError): uart.raw_query("ADC PAR SAMPLE",timeout=0)
        with self.assertRaises(RuntimeError): uart.raw_query("ADC PAR SAMPLE",timeout=0)
        self.assertEqual(len(p.writes),1)
        for cmd in ("START","ZERO SAMPLE","ADC 3PH SAMPLE","ADC DMA SAMPLE"):
            with self.assertRaises(ValueError): uart.raw_query(cmd,timeout=0)
    def test_independent_clock_and_pa8_proof(self):
        regs=dict(zip(clock.CLOCK_ADDRESSES,(0x80000,0x80000,0xA0000000,0,4249,3<<16,0)))
        def output(d): return "\n".join(f"0x{k:08X} : {v:08X}" for k,v in d.items())
        clock.require_async_registers(output(regs))
        for address,value in ((0x50000708,0x40000),(0x50000708,0xA0000),(0x40021088,0x60000000),
                              (0x48000000,0),(0x4800000C,1<<16),(0x40012C2C,4248)):
            with self.assertRaises(RuntimeError): clock.require_async_registers(output(dict(regs,**{})|{address:value}))
        del regs[0x50000708]
        with self.assertRaises(RuntimeError): clock.require_async_registers(output(regs))
    def test_evidence_and_capture_tool_scoped(self):
        good={"pass":True,"inspect_only":False,"target_slot":"A","image_sha256":deploy.PINNED["A"],
              "final_flash":{"all_protected_regions_unchanged":True},"motion_commands":False,"sampling_commands":False,
              "final_fw":{"CURRENT":"A","CONFIRMED":"A","PENDING":"-","ATTEMPTS":"0","ACTIVE":"0","GEN":"381"}}
        self.assertEqual(sample.deployment_identity(good),("A","381"))
        for key,value in (("pass",False),("image_sha256",deploy.SEQUENTIAL_PINNED["A"]),("sampling_commands",True)):
            with self.assertRaises(RuntimeError): sample.deployment_identity(dict(good,**{key:value}))
        changed=copy.deepcopy(good); changed["final_fw"]["PENDING"]="A"
        with self.assertRaises(RuntimeError): sample.deployment_identity(changed)
        source=Path(sample.__file__).read_text(encoding="utf-8")
        for forbidden in ('"START"','"FW END"','"-rst"','"CLEAR"','"ZERO SAMPLE"'):
            self.assertNotIn(forbidden,source)
    def test_parallel_profile_remains_off_by_default_and_not_foc(self):
        for slot in "ab":
            cmake=(ROOT/f"foc2_app_{slot}/CMakeLists.txt").read_text(encoding="utf-8")
            self.assertIn('option(ADC_DMA_PARALLEL_DIAGNOSTIC "Independent ADC1/2/5 common-event PA0/PA1/PA8 raw DMA" OFF)',cmake)
            self.assertIn('ADC_DMA_PARALLEL_DIAGNOSTIC AND NOT ADC_DMA_THREE_PHASE_DIAGNOSTIC',cmake)
        console=(ROOT/"firmware_common/adc_parallel_console.inc").read_text(encoding="utf-8")
        for forbidden in ("PowerStage_Enable(","FOC_CurrentLoopStep(","iw_zero_raw ="):
            self.assertNotIn(forbidden,console)
        owner=(ROOT/"firmware_common/zero_adc_owner.inc").read_text(encoding="utf-8")
        self.assertIn('bus_mv < 10000U || bus_mv > 14000U',owner)
        self.assertIn('AdcDmaDiag_ParallelReady()',owner)
        self.assertIn('ZeroRetest_SubmitAcquisition(request_id, ZERO_ADC_ACQUIRE_DMA)',console)
        self.assertNotIn('ADC_AnalogLiveSample(',console)
if __name__=="__main__": unittest.main()
