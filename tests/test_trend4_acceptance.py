"""Offline pins, inactive-slot and no-commit staging contracts."""
from pathlib import Path
import struct
import sys
import unittest
import zlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import trend4_control_acceptance as m
import trend4_control_commit as trial
import trend4_after_trial_inspect as rollback

class Trend4StageTests(unittest.TestCase):
    def test_fault_capture_before_health_reset_and_partial_evidence(self):
        calls=[]
        class Fake:
            def query(self,text):
                calls.append(text)
                if text=='FAULT SNAPSHOT': return 'VALID=1 REASON=1 UA=1560 VA=1560 UP=2400 VP=1560'
                if text=='FAULT FILTER': return 'VALID=1 MC=3'
                if text=='FAULT SHADOW': return 'VALID=1 MODE=OBSERVE SRC=1 RM=5 FM=0'
                if text=='FAULT TREND': return 'VALID=1 CHANGED=7'
                if text=='OC SHADOW STATUS': return 'MODE=OBSERVE PEND=5 CONF=0'
                if text=='OC FILTER STATUS': return 'MODE=OBSERVE PAIRS=10 CHANGED=7 CU=5 CV=3'
                raise AssertionError(text)
        record={}
        self.assertTrue(trial.capture_trial_fault(Fake(),record))
        self.assertEqual(calls,['FAULT SNAPSHOT','FAULT FILTER'])
        calls.clear(); self.assertTrue(trial.capture_trial_fault(Fake(),record,shadow=True))
        self.assertEqual(record['trial_fault_captures'][-1]['shadow']['SRC'],'1')
        class Interrupted(Fake):
            def query(self,text):
                if text=='FAULT FILTER': raise TimeoutError('rollback interrupted reply')
                return super().query(text)
        with self.assertRaises(TimeoutError): trial.capture_trial_fault(Interrupted(),record)
        self.assertEqual(record['trial_fault_captures'][-1]['snapshot']['UP'],'2400')
        class Clean:
            def query(self,text):
                self_text=text
                if self_text!='FAULT SNAPSHOT': raise AssertionError(text)
                return 'VALID=0 REASON=0'
        self.assertFalse(trial.capture_trial_fault(Clean(),{}))

    def test_failed_trial_invalidates_metadata_not_physical_image(self):
        a=(ROOT/'foc2_app_a/build/ZeroFailureTrace20261012/foc2.bin').read_bytes()
        b=(ROOT/'foc2_app_b/build/IsolatedSpike20261012/foc2.bin').read_bytes()
        raw=bytearray(b'\xff'*0x80000)
        raw[0x8000:0x8000+len(a)]=a; raw[0x40000:0x40000+len(b)]=b
        def put_meta(data,generation,bsize,bcrc,current=1,pending=0):
            meta=struct.pack('<11I',0x424f4f54,3,current,pending,0,generation,
                             len(a),zlib.crc32(a),bsize,bcrc,0)
            data[0x7e800:0x7e830]=meta+struct.pack('<I',zlib.crc32(meta))
        put_meta(raw,429,len(b),zlib.crc32(b))
        after=bytearray(raw); image=m.image()
        after[0x40000:0x40000+len(image)]=image
        put_meta(after,433,0,0)
        self.assertTrue(rollback.validate_rollback(raw,after,image)['failed_B_metadata_invalidated'])
        for offset in (0x100,0x8010,0x40001,0x78000,0x7f800):
            altered=bytearray(after); altered[offset]^=1
            with self.assertRaises(RuntimeError): rollback.validate_rollback(raw,altered,image)
        for values in ((432,0,0,1,0),(433,len(image),zlib.crc32(image),1,0),
                       (433,0,0,2,0),(433,0,0,1,2)):
            altered=bytearray(after); put_meta(altered,*values)
            with self.assertRaises(RuntimeError): rollback.validate_rollback(raw,altered,image)

    def test_exact_hard_off_image(self):
        self.assertEqual(m.image_info(m.image())[0],'B')

    def test_locked_baseline_and_protection(self):
        a=(ROOT/'foc2_app_a/build/ZeroFailureTrace20261012/foc2.bin').read_bytes()
        b=(ROOT/'foc2_app_b/build/IsolatedSpike20261012/foc2.bin').read_bytes()
        raw=bytearray(b'\xff'*0x80000)
        raw[0x8000:0x8000+len(a)]=a; raw[0x40000:0x40000+len(b)]=b
        meta=struct.pack('<11I',0x424f4f54,3,1,0,0,429,len(a),zlib.crc32(a),len(b),zlib.crc32(b),0)
        raw[0x7e800:0x7e830]=meta+struct.pack('<I',zlib.crc32(meta))
        self.assertEqual(m.baseline(raw)['current'],'A')
        target=m.image(); after=bytearray(raw)
        after[0x40000:0x40000+len(target)]=target
        self.assertTrue(m.compare_flash(raw,after,target,'B',staged=True)['all_protected_regions_unchanged'])
        for offset in (0x100,0x8010,0x78000,0x7e810,0x7f800):
            altered=bytearray(after); altered[offset]^=1
            with self.assertRaises(RuntimeError): m.compare_flash(raw,altered,target,'B',staged=True)
        raw[0x8000]^=1
        with self.assertRaises(RuntimeError): m.baseline(raw)

    def test_no_motion_reset_commit_or_sampling(self):
        uart=m.StageConsole(None)
        for text in ('START','CLEAR','BENCH RUN','BENCH STOP','ZERO SAMPLE','FW RESET'):
            with self.assertRaises(ValueError): uart.query(text)
        for text in ('FW END','FW RESET','START','CLEAR'):
            with self.assertRaises(ValueError): uart.command(text)

    def test_trial_filter_retains_raw_evidence(self):
        line=('MEDIAN=0 SPIKE3=0 TREND4=1 DELAY_PAIRS=1 FILTER_REV=3 '
              'COMPUTE_ONLY=1 MOTOR_QUALIFIED=0 FILTER_STATE=3 RAW_STATE=4 '
              'RAW_REASON=2 RAW_LAST=1560,1800 RAW_RANGE=1450:1800,1500:1560 '
              'OUT=10 CHANGED=20 PAIRS=24003 RAW_WINDOW=4003')
        trial.require_filter(line)
        for old,new in (('TREND4=1','TREND4=0'),('DELAY_PAIRS=1','DELAY_PAIRS=2'),
                        ('FILTER_STATE=3','FILTER_STATE=4'),('MOTOR_QUALIFIED=0','MOTOR_QUALIFIED=1'),
                        ('OUT=10','OUT=4004'),('CHANGED=20','CHANGED=24004')):
            with self.assertRaises(RuntimeError): trial.require_filter(line.replace(old,new))
        with self.assertRaises(RuntimeError): trial.require_filter(line.replace('RAW_REASON=2 ',''))

    def test_trial_never_resends_commit_or_accepts_motion(self):
        uart=trial.Console(None,commit=True)
        uart.ends=1
        with self.assertRaises(ValueError): uart.command('FW END')
        for text in ('START','CLEAR','BENCH RUN','FW BEGIN 1 ABCDEF12','FW RESET'):
            with self.assertRaises(ValueError): uart.command(text)
        for text in ('START','CLEAR','BENCH RUN','ZERO SAMPLE','FW RESET'):
            with self.assertRaises(ValueError): uart.query(text)

    def test_active_stage_uses_allowed_zero_query_not_blocked_analog_query(self):
        data=m.image(); slot,crc=m.image_info(data)
        calls=[]
        class Fake:
            def query(self,text):
                calls.append(text)
                if text=='ZERO STATUS':
                    return ('PROFILE=LOCKED_DIAGNOSTIC LOCK=1 SD=0 MOE=0 CCER=0 '
                            'CEN=0 FOC=0 MOTOR_READY=0 IF=0 ACTIVE=0')
                if text=='FW STATUS':
                    return (f'CURRENT=A CONFIRMED=A TARGET={slot} PENDING=- ATTEMPTS=0 '
                            f'ACTIVE=1 RX={len(data)} SIZE={len(data)} EXPECT=0x{crc:08X}')
                raise AssertionError('Query is blocked during FW staging: '+text)
        trial.precommit_queries(Fake(),data)
        self.assertEqual(calls,['ZERO STATUS','FW STATUS'])

if __name__=='__main__': unittest.main()
