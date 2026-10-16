from pathlib import Path
import struct
import sys
import unittest
import zlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import trend4_fault_capture_acceptance as m

class RealFocCaptureTests(unittest.TestCase):
    def fixture(self):
        a=(ROOT/'foc2_app_a/build/ZeroFailureTrace20261012/foc2.bin').read_bytes()
        b=(ROOT/'foc2_app_b/build/OvercurrentLayersSelftest20261013/foc2.bin').read_bytes()
        raw=bytearray(b'\xff'*0x80000)
        raw[0x8000:0x8000+len(a)]=a; raw[0x40000:0x40000+len(b)]=b
        def meta(data,gen=436,current=2,alen=len(a),acrc=zlib.crc32(a)):
            packed=struct.pack('<11I',0x424f4f54,3,current,0,0,gen,alen,acrc,len(b),zlib.crc32(b),0)
            data[0x7e800:0x7e830]=packed+struct.pack('<I',zlib.crc32(packed))
        meta(raw)
        return raw,meta
    def test_image_includes_capture_and_hard_off_markers(self):
        self.assertEqual(m.core.image_info(m.image())[0],'A')
    def test_exact_B436_no_inactive_guess(self):
        raw,meta=self.fixture()
        self.assertEqual(m.baseline(raw)['current'],'B')
        for slot,gen in ((1,436),(2,435),(2,437)):
            altered=bytearray(raw); meta(altered,gen,current=slot)
            with self.assertRaises(RuntimeError): m.baseline(altered)
        for offset in (0x8000,0x40000):
            altered=bytearray(raw); altered[offset]^=1
            with self.assertRaises(RuntimeError): m.baseline(altered)
    def test_stage_preserves_B_and_every_non_A_byte(self):
        raw,_=self.fixture(); after=bytearray(raw); image=m.image()
        after[0x8000:0x8000+len(image)]=image
        self.assertTrue(m.compare_flash(raw,after,image,'A',staged=True)['all_protected_regions_unchanged'])
        for offset in (0x100,0x40010,0x78000,0x7e810,0x7f800):
            altered=bytearray(after); altered[offset]^=1
            with self.assertRaises(RuntimeError): m.compare_flash(raw,altered,image,'A',staged=True)
    def test_failed_A_rollback_keeps_pinned_B(self):
        raw,meta=self.fixture(); after=bytearray(raw); image=m.image()
        after[0x8000:0x8000+len(image)]=image; meta(after,440,alen=0,acrc=0)
        self.assertTrue(m.validate_rollback(raw,after)['failed_A_metadata_invalidated'])
        for offset in (0x100,0x8010,0x40010,0x78000,0x7f800):
            altered=bytearray(after); altered[offset]^=1
            with self.assertRaises(RuntimeError): m.validate_rollback(raw,altered)
        for gen in (439,441):
            altered=bytearray(after); meta(altered,gen,alen=0,acrc=0)
            with self.assertRaises(RuntimeError): m.validate_rollback(raw,altered)
    def test_only_one_commit_no_motion_or_clear(self):
        uart=m.core.Console(None,commit=True); uart.ends=1
        with self.assertRaises(ValueError): uart.command('FW END')
        for text in ('START','CLEAR','BENCH RUN','ZERO SAMPLE','FW RESET','FW BEGIN 1 ABCDEF12'):
            with self.assertRaises(ValueError): uart.command(text)
            with self.assertRaises(ValueError): uart.query(text)
    def test_capture_precedes_confirmation_and_partial_evidence_survives(self):
        source=(ROOT/'tools/trend4_fault_capture_acceptance.py').read_text('utf-8')
        body=source[source.index("if fw.get('CURRENT')=='A':"):]
        self.assertLess(body.index('capture_fault()'),body.index("confirmed(fw,'A')"))
        self.assertIn('shadow=True',source)
        self.assertNotIn('FW ABORT',source)
if __name__=='__main__': unittest.main()
