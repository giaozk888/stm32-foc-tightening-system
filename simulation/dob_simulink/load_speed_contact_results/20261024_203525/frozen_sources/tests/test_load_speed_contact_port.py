import ctypes as C
import json
import struct
import subprocess
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import prepare_load_speed_contact as p
from dob_load_speed_contact_decode import decode


class ContactPortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=ROOT/'tmp/load_speed_contact_port.dll'
        subprocess.run([str(p.old.reviewed.GCC),'-std=c11','-Os','-Wall','-Wextra','-Werror','-shared',
            '-DFOC_DOB_TREND_WINDOW75=1','-DFOC_DOB_TREND_CONTINUOUS=1','-DFOC_DOB_LOAD_SPEED_CONTACT_HOLD=1',
            '-I',str(p.old.COMMON),str(ROOT/'tests/load_speed_board_host.c'),
            *[str(p.old.COMMON/f) for f in ('dob_load_speed_candidate.c','dob_trend_shadow.c','dob_trend_continuous.c')],
            '-lm','-o',str(cls.path)],capture_output=True,text=True,check=True)

    def setUp(self):
        self.dll=C.CDLL(str(self.path));self.dll.board_reset();self.now=100000
        self.dll.board_step.argtypes=[C.POINTER(C.c_double),C.POINTER(C.c_double)]
        self.dll.board_tail.argtypes=[C.c_void_p]

    def step(self,phase=3,valid=1,level=4,trend=2,mean=.05,age=1000):
        self.now+=1000;y=(C.c_double*9)()
        self.dll.board_step((C.c_double*13)(self.now,phase,1,valid,level,1,trend,240,20,mean,age,209,-200),y)
        return list(y)

    def tail(self):
        buf=C.create_string_buffer(200);self.dll.board_tail(buf);return buf.raw

    def test_mcu_selector_contact_cancel_and_real_release_dwell(self):
        for _ in range(50):y=self.step()
        self.assertEqual(y[:2],[120,1])
        for _ in range(400):y=self.step(phase=4,valid=0)
        self.assertEqual(y[:3],[120,1,8])
        for _ in range(150):y=self.step(phase=3,level=1,trend=1,mean=0)
        self.assertEqual(y[0],120)
        for _ in range(52):y=self.step(phase=3,level=1,trend=1,mean=0)
        self.assertEqual(y[0],240)

    def test_compact_events_and_quality_clear_keep_first_and_latest_three(self):
        for _ in range(3):
            for _ in range(50):self.step()
            for _ in range(40):self.step(phase=4,valid=0)
            for _ in range(400):self.step(level=1,trend=1,mean=0)
        raw=self.tail();magic,count=struct.unpack_from('<2I',raw)
        self.assertEqual((magic,count),(0xD1500002,12))
        first=struct.unpack_from('<6I5fI',raw,8)
        self.assertEqual(first[1],2);self.assertEqual(first[6:8],(240,120))
        self.dll.board_quality_clear();self.assertEqual(self.tail(),raw)
        ram=bytearray(4096);ram[1024+300:1024+400]=raw[:100];ram[1024+700:1024+800]=raw[100:]
        ram[128:132]=struct.pack('<I',0x20000400)
        # State is a synthetic decoding fixture; actual MCU state ABI verified by compile assertion.
        ram[:68]=struct.pack('<12I2f3I',0,0,0,1,0,6,0,0,1470,600,0,self.now,240,240,3,0,0)
        out=decode(ram,{'dob_load_speed':(0x20000000,68),'dob_trend_continuous_arena':(0x20000080,4),
            'mechanical_capture':(0x20000400,800)})
        self.assertEqual([e['event_ordinal'] for e in out['events']],[1,10,11,12])
        self.assertEqual([e['reason_name'] for e in out['events']][-3:],['CONTACT_HOLD','CONTACT_REACQUIRE','BASE'])


class ContactFullHostTests(unittest.TestCase):
    def setUp(self):
        self.dll=C.CDLL(str(p.WORK/'contact_host.dll'))
        self.dll.dob_host_reset.argtypes=[C.POINTER(C.c_double)]
        self.dll.dob_host_step.argtypes=[C.c_double,C.POINTER(C.c_double),C.POINTER(C.c_double)]
        self.dll.dob_host_state_size.restype=C.c_uint
        self.dll.dob_host_save.argtypes=[C.c_void_p];self.dll.dob_host_restore.argtypes=[C.c_void_p]
        self.dll.dob_host_reset((C.c_double*3)(1,.25,.025))

    def step(self,k,rpm=240,stop=0,fault=0):
        t=k*.001;y=(C.c_double*66)()
        u=(C.c_double*16)(240 if t>=.2 else 0,rpm*.10471975511966,.20,0,0,.005,1,0,0,1,1,t*1440,1,0,stop,fault)
        self.dll.dob_host_step(t,u,y);return list(y)

    def test_actual_fsm_cancel_keeps_slow_target_and_snapshot(self):
        for k in range(2500):self.step(k)
        rows=[self.step(k,10) for k in range(2500,2600)]
        self.assertTrue(any(y[46]==4 for y in rows))
        self.assertTrue(all(y[34]==120 for y in rows if y[46]==4))
        buf=C.create_string_buffer(self.dll.dob_host_state_size());self.dll.dob_host_save(buf)
        first=[self.step(k,120) for k in range(2600,2650)]
        self.dll.dob_host_restore(buf);second=[self.step(k,120) for k in range(2600,2650)]
        self.assertEqual(first,second)
        self.assertEqual(first[0][46],3);self.assertEqual(first[0][34],120)
        self.assertEqual(first[-1],self.step(2649,10))
        y=self.step(2650,stop=1);self.assertEqual(y[7],0);self.assertEqual(y[35],0)

    def test_actual_fsm_protection_and_confirmed_contact_override_hold(self):
        for event in ('fault','confirmed'):
            self.setUp()
            for k in range(2500):self.step(k)
            for k in range(2500,2600):y=self.step(k,10)
            self.assertEqual(y[46],4);self.assertEqual(y[34],120)
            if event=='fault':
                y=self.step(2600,10,fault=1)
                self.assertEqual(y[46],10);self.assertEqual(y[7],0);self.assertEqual(y[35],0)
            else:
                for k in range(2600,2900):y=self.step(k,0)
                self.assertTrue(y[49]);self.assertEqual(y[54],1) # Existing zero-current NEUTRAL, not power OFF.
                self.assertEqual(y[7],0);self.assertEqual(y[34],0);self.assertEqual(y[64],0)


if __name__=='__main__':unittest.main()
