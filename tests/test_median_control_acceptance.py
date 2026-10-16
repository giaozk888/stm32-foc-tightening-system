"""Pure host validation; no hardware opened by these tests."""
from pathlib import Path
import struct
import sys
import unittest
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import median_control_acceptance as m
from zero_median_contrast import image as fallback_image

class AcceptanceTests(unittest.TestCase):
    def test_exact_artifact(self):
        self.assertEqual(m.image_info(m.image())[0],'A')
    def test_exact_fallback_and_generation(self):
        a,b=fallback_image('A')[1],fallback_image('B')[1]
        data=bytearray(b'\xff'*0x80000)
        data[0x8000:0x8000+len(a)]=a
        data[0x40000:0x40000+len(b)]=b
        def meta(current=2,pending=0,generation=408):
            raw=struct.pack('<11I',0x424f4f54,3,current,pending,0,generation,
                            len(a),zlib.crc32(a),len(b),zlib.crc32(b),0)
            data[0x7f000:0x7f030]=raw+struct.pack('<I',zlib.crc32(raw))
        meta(); self.assertEqual(m.baseline(data)['current'],'B')
        for settings in ((1,0,408),(2,1,408),(2,0,409)):
            meta(*settings)
            with self.assertRaises(RuntimeError): m.baseline(data)
        meta(); data[0x40010]^=1
        with self.assertRaises(RuntimeError): m.baseline(data)
    def test_no_motion_clear_or_bench_restart(self):
        class NoPort:
            def write(self,data): raise AssertionError('Rejected command reached wire')
        for commit in (False,True):
            console=m.Console(NoPort(),commit)
            for command in ('START','CLEAR','BOOT A','FW CONFIRM','BENCH RUN','ZERO SAMPLE'):
                with self.assertRaises(ValueError): console.command(command)
                with self.assertRaises(ValueError): console.query(command)
        with self.assertRaises(ValueError): m.Console(NoPort()).command('FW END')
        console=m.Console(NoPort(),True); console.ends=1
        with self.assertRaises(ValueError): console.command('FW END')
    def test_filtered_ready_explicitly_not_motor_admission(self):
        line=('MEDIAN=1 COMPUTE_ONLY=1 MOTOR_QUALIFIED=0 RAW_STATE=4 RAW_REASON=2 '
              'RAW_LAST=1700,1700 RAW_RANGE=1500:1700,1500:1700 OUT=1 CHANGED=10 PAIRS=24000 FILTER_STATE=3')
        m.require_filter(line)
        for old,new in (('COMPUTE_ONLY=1','COMPUTE_ONLY=0'),('MOTOR_QUALIFIED=0','MOTOR_QUALIFIED=1'),
                        ('FILTER_STATE=3','FILTER_STATE=4'),('OUT=1','OUT=24001')):
            with self.assertRaises(RuntimeError): m.require_filter(line.replace(old,new))
    def test_filtered_zero_retains_same_window_and_nominal_gates(self):
        line='STATE=3 REASON=0 NOM=1560 U0=1560 V0=1561 N=4000 SET=20000 RET=0 RNG=1530:1600,1531:1601'
        m.require_zero(line)
        for old,new in (('N=4000','N=3999'),('SET=20000','SET=19999'),
                        ('U0=1560','U0=1700'),('RNG=1530:1600','RNG=1530:1631')):
            with self.assertRaises(RuntimeError): m.require_zero(line.replace(old,new))

if __name__=='__main__': unittest.main()
