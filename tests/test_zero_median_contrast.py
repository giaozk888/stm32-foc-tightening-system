import sys
import unittest
import subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import zero_median_contrast as m
from zero_retest_sample import require_locked_sample
from test_zero_async_clock_sample import FRESH

class MedianContracts(unittest.TestCase):
    def test_actual_median_core(self):
        root=Path(__file__).resolve().parents[1]
        target=root/'tests/foc_current_zero_build/median_host.exe'
        target.parent.mkdir(exist_ok=True)
        subprocess.run([r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe', '-std=c11',
                        '-Wall', '-Wextra', '-Werror', '-pedantic', '-UNDEBUG',
                        '-I', str(root/'firmware_common'),
                        str(root/'tests/foc_zero_median_host.c'),
                        str(root/'firmware_common/foc_zero_median.c'),
                        str(root/'firmware_common/foc_current_zero.c'),
                        '-o',str(target)],check=True)
        subprocess.run([str(target)],check=True,capture_output=True,text=True)
    def test_raw_tool_rejects_median(self):
        line = FRESH + " MEDIAN=1 ADC_OWNER=1"
        with self.assertRaises(RuntimeError): require_locked_sample(line)
        m.fresh_sample(line)
    def test_output_guard_still_enforced(self):
        line = FRESH + " MEDIAN=1 ADC_OWNER=1"
        for old, new in (("SD=0", "SD=1"), ("MOE=0", "MOE=1"), ("SPAN=100", "SPAN=200")):
            with self.assertRaises(RuntimeError): m.fresh_sample(line.replace(old,new))
        with self.assertRaises(RuntimeError): m.median_guard(FRESH)
    def test_baseline_exact_images_and_no_trial(self):
        _, a=m.image("A")
        _, b=m.target_image()
        import struct, zlib
        data=bytearray(b'\xff'*0x80000)
        data[0x8000:0x8000+len(a)]=a
        data[0x40000:0x40000+len(b)]=b
        raw=struct.pack('<11I',0x424f4f54,3,1,0,0,405,len(a),zlib.crc32(a),149172,0x1c0bfdc0,0)
        data[0x7e800:0x7e830]=raw+struct.pack('<I',zlib.crc32(raw))
        self.assertEqual(m.baseline(data)['current'],'A')
        data[0x8000]^=1
        with self.assertRaises(RuntimeError): m.baseline(data)
    def test_filter_report_requires_raw_evidence(self):
        line='OK MEDIAN=1 MOTOR_READY=0 PAIRS=24000 CHANGED=1 OUT=1 RAW_STATE=4 RAW_REASON=2 RAW_N=90 RAW_U0=0 RAW_V0=0 RAW_LAST=1668,1671 RAW_RANGE=1561:1668,1561:1671 FILTER_STATE=3 FILTER_REASON=0'
        self.assertEqual(m.filter_status(line)['RAW_STATE'],'4')
        with self.assertRaises(RuntimeError): m.filter_status(line.replace('RAW_U0=0','RAW_U0=1561'))
    def test_module_has_no_motor_publication(self):
        root=Path(__file__).resolve().parents[1]
        src=(root/'firmware_common/foc_zero_median.c').read_text()
        for forbidden in ('malloc(', 'iu_zero_raw =', 'PowerStage_Enable', 'FOC_CurrentLoopStep'):
            self.assertNotIn(forbidden,src)
        self.assertIn('FocZero_Push(&m->raw, u, v)',src)

if __name__=='__main__': unittest.main()
