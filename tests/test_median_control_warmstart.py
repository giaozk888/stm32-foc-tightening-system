"""No hardware: repaired binary entry and exact restored B baseline."""
from pathlib import Path
import struct
import sys
import unittest
import zlib

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import median_control_warmstart_acceptance as w
import median_control_acceptance as old
from zero_median_contrast import image as original


class WarmStartTests(unittest.TestCase):
    def test_repaired_binary_masks_irq_first(self):
        data=w.image()
        self.assertEqual(len(data),202536)
        self.assertNotEqual(w.SHA,old.SHA)

    def test_exact_restored_baseline_only(self):
        a,b=old.image(),original('B')[1]
        data=bytearray(b'\xff'*0x80000)
        data[0x8000:0x8000+len(a)]=a
        data[0x40000:0x40000+len(b)]=b
        def meta(current=2,pending=0,generation=414):
            raw=struct.pack('<11I',0x424F4F54,3,current,pending,0,generation,
                            len(a),zlib.crc32(a),len(b),zlib.crc32(b),0)
            data[0x7F000:0x7F030]=raw+struct.pack('<I',zlib.crc32(raw))
        meta(); self.assertEqual(w.baseline(data)['generation'],414)
        for args in ((1,0,414),(2,1,414),(2,0,408),(2,0,415)):
            meta(*args)
            with self.assertRaises(RuntimeError): w.baseline(data)
        meta(); data[0x40010]^=1
        with self.assertRaises(RuntimeError): w.baseline(data)


if __name__=='__main__': unittest.main()
