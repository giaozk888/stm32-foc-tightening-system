from pathlib import Path
import subprocess
import unittest
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
class TraceTests(unittest.TestCase):
    def test_actual_core(self):
        out=ROOT/'tests/foc_current_zero_build/failure_trace.exe'
        out.parent.mkdir(exist_ok=True)
        subprocess.run([r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe','-std=c11','-O2',
            '-Wall','-Wextra','-Werror','-DFOC_CURRENT_SPIKE_ONLY=1','-I',str(ROOT/'firmware_common'),
            str(ROOT/'tests/foc_zero_failure_trace_host.c'),str(ROOT/'firmware_common/foc_current_zero.c'),
            str(ROOT/'firmware_common/foc_zero_median.c'),'-o',str(out)],check=True)
        subprocess.run([str(out)],check=True,timeout=10)
    def test_locked_binding(self):
        for slot in 'ab':
            cm=(ROOT/f'foc2_app_{slot}/CMakeLists.txt').read_text()
            self.assertIn('option(FOC_ZERO_FAILURE_TRACE',cm)
            self.assertIn('NOT FOC_CURRENT_SPIKE_ONLY OR ADC_DMA_RAW_DIAGNOSTIC OR SWITCH_FEEDBACK_DIAGNOSTIC',cm)
        src=(ROOT/'firmware_common/zero_retest_boot.inc').read_text()
        self.assertLess(src.index('!ZeroRetest_Locked() || !pair_ready || adc_fault'),src.index('FocTrace_Push('))
        self.assertIn('if (!zero_trace.done) return;',src)
        console=(ROOT/'firmware_common/zero_failure_trace_console.inc').read_text()
        self.assertIn('zero_retest_running || !zero_trace.done',console)
        self.assertIn('!n || *arg',console)
    def test_host_decoder_and_pinned_image(self):
        import zero_failure_trace_acceptance as h
        import isolated_spike_acceptance as base
        p=h.parse_point('INDEX=32 SEQ=22000 A=1560,1561 B=2300,1502 C=1562,1560 FILTER=1560,1502 MASK=1')
        self.assertEqual(p['b'],(2300,1502))
        with self.assertRaises(RuntimeError):
            h.parse_point('INDEX=32 SEQ=22000 A=1560,1561 B=2300,1502 C=1562,1560 FILTER=2300,1502 MASK=0')
        with patch.dict(base.__dict__):
            h.configure()
            self.assertIn(b'TRACE=1 DONE=',base.image())
            self.assertEqual(base.TARGET_SLOT,'A')
            self.assertEqual(base.BASELINE_GENERATION,'426')
        uart=h.TraceConsole(None)
        for text in ('START','CLEAR','SWITCH START BRIDGE','ZERO TRACE READ -1','ZERO TRACE READ 1 BAD'):
            with self.assertRaises(ValueError): uart.query(text)
if __name__=='__main__': unittest.main()
