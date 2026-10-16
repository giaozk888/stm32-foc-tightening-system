import hashlib
from pathlib import Path
import struct
import sys
import unittest
import zlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import overcurrent_layers_selftest_acceptance as acceptance

class ProtectionSelftestAcceptanceTests(unittest.TestCase):
    def test_exact_locked_image_pins_and_reset_mask(self):
        data=acceptance.image()
        self.assertEqual(hashlib.sha256(data).hexdigest(),acceptance.SHA)
    def test_baseline_rejects_changed_generation_slot_and_images(self):
        data=bytearray(b'\xff'*0x80000)
        a=(ROOT/'foc2_app_a/build/ZeroFailureTrace20261012/foc2.bin').read_bytes()
        b=(ROOT/'foc2_app_b/build/Trend4Compute20261013/foc2.bin').read_bytes()
        data[0x8000:0x8000+len(a)]=a
        data[0x40000:0x40000+len(b)]=b
        def meta(slot,gen):
            words=(0x424f4f54,3,slot,0,0,gen,len(a),zlib.crc32(a),0,0,0)
            raw=struct.pack('<11I',*words)
            data[0x7e800:0x7e830]=raw+struct.pack('<I',zlib.crc32(raw))
        meta(1,433); self.assertEqual(acceptance.baseline(bytes(data))['current'],'A')
        for slot,gen in ((2,433),(1,432),(1,434)):
            meta(slot,gen)
            with self.assertRaises(RuntimeError): acceptance.baseline(bytes(data))
        meta(1,433); data[0x40010]^=1
        with self.assertRaises(RuntimeError): acceptance.baseline(bytes(data))
    def test_missing_failed_or_unlocked_results_are_rejected(self):
        good='OK INPUT=SYNTHETIC DONE=1 CASES=6 CHECKS=36 FAIL=0x00000000 SOFT_MA=4000 HARD_SIM_MA=5000 ACTUAL_LIMIT_MA=4000 LOCK=1 MOTOR_QUALIFIED=0'
        self.assertEqual(acceptance.require_selftest(good)['CHECKS'],'36')
        for old,new in (('LOCK=1','LOCK=0'),('FAIL=0x00000000','FAIL=0x00000001'),
                        ('DONE=1','DONE=0'),('ACTUAL_LIMIT_MA=4000','ACTUAL_LIMIT_MA=5000'),
                        ('INPUT=SYNTHETIC','INPUT=ADC'),('CHECKS=36','CHECKS=35')):
            with self.assertRaises(RuntimeError): acceptance.require_selftest(good.replace(old,new))
    def test_no_commit_before_readback_and_no_unscoped_queries(self):
        c=acceptance.Console(None)
        with self.assertRaises(ValueError): c.command('FW END')
        for cmd in ('START','ZERO SAMPLE','BOOT B','FW CONFIRM','CLEAR'):
            with self.assertRaises(ValueError): c.query(cmd)
            with self.assertRaises(ValueError): c.command(cmd)
        c.commit_ready=True; c.ends=1
        with self.assertRaises(ValueError): c.command('FW END')
if __name__=='__main__': unittest.main()
