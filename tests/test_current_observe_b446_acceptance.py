import struct
import sys
import unittest
import zlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import current_observe_b446_acceptance as host
from switch_trend_compare_deploy import image as fallback_image

class B446ObserveTests(unittest.TestCase):
    def fixture(self,slot=2,generation=446,pending=0):
        a=host.observe.image(); b=fallback_image()
        raw=bytearray(b'\xff'*0x80000)
        raw[0x8000:0x8000+len(a)]=a; raw[0x40000:0x40000+len(b)]=b
        packed=struct.pack('<11I',0x424f4f54,3,slot,pending,0,generation,
                           len(a),zlib.crc32(a),len(b),zlib.crc32(b),0)
        raw[0x7e800:0x7e830]=packed+struct.pack('<I',zlib.crc32(packed))
        return raw
    def test_exact_baseline(self):
        self.assertEqual(host.baseline(self.fixture())['generation'],446)
        for slot,gen,pending in ((1,446,0),(2,443,0),(2,447,0),(2,446,1)):
            with self.assertRaises(RuntimeError): host.baseline(self.fixture(slot,gen,pending))
    def test_both_image_pins(self):
        for offset in (0x8010,0x40010):
            raw=self.fixture(); raw[offset]^=1
            with self.assertRaises(RuntimeError): host.baseline(raw)
    def test_no_motion_or_repeated_commit(self):
        class Port:
            def write(self,value): raise AssertionError('Forbidden command reached UART')
        c=host.observe.ObserveConsole(Port(),commit=True)
        for cmd in ('START','CLEAR','BOOT A','BENCH RUN','SWITCH START BRIDGE','OC RAW SET 0'):
            with self.assertRaises(ValueError): c.query(cmd)
            with self.assertRaises(ValueError): c.command(cmd)
        c.ends=1
        with self.assertRaises(ValueError): c.command('FW END')

if __name__=='__main__': unittest.main()
