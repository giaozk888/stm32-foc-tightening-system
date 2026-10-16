"""Offline admission and command contracts for pinned diagnostic deployment."""
import sys
import unittest
from pathlib import Path
import struct
import zlib
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import isolated_spike_acceptance as m

class DeploymentTests(unittest.TestCase):
    def test_image_locked_and_pinned(self):
        data = m.image()
        self.assertIn(b'MEDIAN=0 SPIKE3=1 DELAY_PAIRS=1',data)
        self.assertNotIn(b'OPEN_LOAD_ONLY',data)

    def test_exact_baseline_and_protected_slots(self):
        a = (ROOT/'foc2_app_a/build/SwitchFeedbackTimerFix20261012/foc2.bin').read_bytes()
        b = (ROOT/'foc2_app_b/build/SwitchFeedback20261012/foc2.bin').read_bytes()
        raw = bytearray(b'\xff'*0x80000)
        raw[0x8000:0x8000+len(a)] = a
        raw[0x40000:0x40000+len(b)] = b
        meta = struct.pack('<11I',0x424f4f54,3,1,0,0,423,len(a),zlib.crc32(a),len(b),zlib.crc32(b),0)
        raw[0x7e800:0x7e830] = meta+struct.pack('<I',zlib.crc32(meta))
        self.assertEqual(m.baseline(raw)['current'],'A')
        raw[0x8000] ^= 1
        with self.assertRaises(RuntimeError): m.baseline(raw)

    def test_spike_service_requires_off_and_fresh(self):
        line = ('PROFILE=LOCKED_DIAGNOSTIC LOCK=1 SD=0 MOE=0 CCER=0 CEN=0 '
                'FOC=0 MOTOR_READY=0 IF=0 ACTIVE=0 MEDIAN=0 SPIKE3=1 DELAY_PAIRS=1 '
                'ADC_OWNER=1 SPAN=100 ADC_READY=1 STATE=0 REASON=0 N=0 SET=0 ADC=0')
        m.require_spike(line,fresh=True)
        for old,new in (('SD=0','SD=1'),('MEDIAN=0','MEDIAN=1'),('SPIKE3=1','SPIKE3=0'),
                        ('DELAY_PAIRS=1','DELAY_PAIRS=0'),('N=0','N=4000')):
            with self.assertRaises(RuntimeError): m.require_spike(line.replace(old,new),fresh=True)

    def test_numeric_field_names_not_lost(self):
        self.assertEqual(m.fields('MEDIAN=0 SPIKE3=1 U0=1562 V0=1560'),
                         dict(MEDIAN='0',SPIKE3='1',U0='1562',V0='1560'))

    def test_no_motion_switch_fault_clear_or_repeat(self):
        uart = m.SpikeConsole(None)
        for text in ('START','MOTOR START','CLEAR','SWITCH START BRIDGE','SWITCH START PWM','FW RESET'):
            with self.assertRaises(ValueError): uart.query(text)
        uart.starts.add('ZERO SAMPLE')
        with self.assertRaises(ValueError): uart.query('ZERO SAMPLE')

if __name__ == '__main__': unittest.main()
