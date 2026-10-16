from pathlib import Path
import struct
import sys
import unittest
import zlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import current_observe_acceptance as m

class ObserveAcceptanceTests(unittest.TestCase):
    def fixture(self):
        a=m.OLD_A.read_bytes();b=m.OLD_B.read_bytes();raw=bytearray(b'\xff'*0x80000)
        raw[0x8000:0x8000+len(a)]=a;raw[0x40000:0x40000+len(b)]=b
        def meta(data,gen=440,current=2,alen=0,acrc=0):
            packed=struct.pack('<11I',0x424f4f54,3,current,0,0,gen,alen,acrc,len(b),zlib.crc32(b),0)
            data[0x7e800:0x7e830]=packed+struct.pack('<I',zlib.crc32(packed))
        meta(raw);return raw,meta
    def test_exact_image_and_invalidated_A_baseline(self):
        self.assertEqual(m.core.image_info(m.image())[0],'A')
        raw,meta=self.fixture();self.assertEqual(m.baseline(raw)['generation'],440)
        for offset in (0x8010,0x40010):
            other=bytearray(raw);other[offset]^=1
            with self.assertRaises(RuntimeError):m.baseline(other)
        for gen,current,alen in ((439,2,0),(441,2,0),(440,1,0),(440,2,205472)):
            other=bytearray(raw);meta(other,gen,current,alen)
            with self.assertRaises(RuntimeError):m.baseline(other)
    def test_stage_and_rollback_protected_regions(self):
        raw,meta=self.fixture();after=bytearray(raw);image=m.image()
        after[0x8000:0x8000+len(image)]=image
        self.assertTrue(m.trial.compare_flash(raw,after,image,'A',staged=True)['all_protected_regions_unchanged'])
        meta(after,444);self.assertTrue(m.validate_rollback(raw,after)['failed_A_metadata_invalidated'])
        for offset in (0x100,0x8010,0x40010,0x78000,0x7f800):
            other=bytearray(after);other[offset]^=1
            with self.assertRaises(RuntimeError):m.validate_rollback(raw,other)
    def test_mode_and_counts_never_qualify_motor(self):
        p=dict(RAW='OBSERVE_POWER_OFF',FILTERED='OBSERVE_POWER_OFF',LIMIT_MA='4000',
               INVALID='STOP',LOCK_LOSS='STOP',MOTOR_QUALIFIED='0')
        r=dict(MODE='OBSERVE',LIMIT_MA='4000',N='10',HIT='0,0,3')
        f=dict(MODE='OBSERVE_POWER_OFF',LIMIT_MA='4000',N='10',HIT='0,0,1',
               DELAY_PAIRS='1',MOTOR_QUALIFIED='0')
        self.assertTrue(m.require_observation(p,r,f))
        for row,key,value in ((p,'RAW','STOP'),(f,'MOTOR_QUALIFIED','1'),
                              (f,'DELAY_PAIRS','0'),(r,'HIT','0,0,11')):
            old=row[key];row[key]=value
            with self.assertRaises(RuntimeError):m.require_observation(p,r,f)
            row[key]=old
    def test_no_motion_retry_or_configuration_commands(self):
        # configure only changes tool-side pins and two READ-ONLY query names.
        old=m.core.READ;m.core.READ=old|m.EXTRA_READ
        try:
            uart=m.ObserveConsole(None,commit=True);uart.ends=1
            for cmd in ('FW END','START','CLEAR','BENCH RUN','FW RESET','OC RAW SET 0'):
                with self.assertRaises(ValueError):uart.command(cmd)
            for cmd in ('START','CLEAR','BENCH RUN','FW RESET','OC RAW SET 0'):
                with self.assertRaises(ValueError):uart.query(cmd)
        finally:m.core.READ=old

if __name__=='__main__':unittest.main()
