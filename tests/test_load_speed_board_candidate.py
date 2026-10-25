import ctypes as C
from pathlib import Path
import re
import struct
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'tests'))
import prepare_load_speed as p


class BoardPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=ROOT/'tmp/load_speed_board_tests.dll'
        subprocess.run([str(p.reviewed.GCC),'-std=c11','-Os','-Wall','-Wextra','-Werror','-shared',
            '-DFOC_DOB_TREND_WINDOW75=1','-DFOC_DOB_TREND_CONTINUOUS=1','-I',str(p.COMMON),'-I',str(p.NATIVE),
            str(ROOT/'tests/load_speed_board_host.c'),str(p.COMMON/'dob_load_speed_candidate.c'),
            str(p.COMMON/'dob_trend_shadow.c'),str(p.COMMON/'dob_trend_continuous.c'),
            str(ROOT/'tests/load_speed_scheduler_host.c'),str(p.COMMON/'speed_scurve.c'),
            '-lm','-o',str(cls.path)],capture_output=True,text=True,check=True)

    def setUp(self):
        self.dll=C.CDLL(str(self.path));self.dll.board_reset();self.dll.schedule_reset()
        self.dll.board_step.argtypes=[C.POINTER(C.c_double),C.POINTER(C.c_double)]
        self.dll.schedule_step.argtypes=[C.POINTER(C.c_double),C.POINTER(C.c_double)]
        self.dll.board_tail.argtypes=[C.c_void_p]
        self.now=100000

    def step(self,valid=1,level=4,trend=2,mean=.05,phase=3,age=1000,base=240):
        self.now+=1000
        u=[self.now,phase,1,valid,level,1,trend,base,20,mean]
        a=(C.c_double*8)();b=(C.c_double*9)()
        self.dll.schedule_step((C.c_double*10)(*u),a)
        self.dll.board_step((C.c_double*13)(*u,age,240,0),b)
        return list(a),list(b)

    def tail(self):
        out=C.create_string_buffer(200);self.dll.board_tail(out);return out.raw

    def test_port_policy_matches_frozen_simulation_policy(self):
        for phase,valid,level,trend,mean,n in [(2,1,4,2,.05,70),(3,1,1,1,0,100),
                (3,1,4,2,.05,500),(3,0,4,2,.05,100),(3,1,4,2,.05,200),
                (3,0,4,2,.05,300),(3,1,4,2,.05,500),(3,1,1,1,0,600),(4,1,4,2,.05,50)]:
            for _ in range(n):
                a,b=self.step(phase=phase,valid=valid,level=level,trend=trend,mean=mean)
                self.assertEqual(a[:6],b[:6])

    def test_no_duplicate_epoch_and_stale_classifier_cannot_trigger_slow(self):
        for _ in range(60):a,b=self.step(age=3000)
        self.assertEqual(b[0],240);self.assertEqual(b[1],0)
        before=b
        u=(C.c_double*13)(self.now,3,1,1,4,1,2,240,20,.05,0,240,0);y=(C.c_double*9)()
        self.dll.board_step(u,y)
        self.assertEqual(list(y),before)

    def test_trace_first_and_latest2_survive_classifier_clear(self):
        for _ in range(5):
            for _ in range(50):self.step()
            for _ in range(400):self.step(level=1,trend=1,mean=0)
        raw=self.tail();magic,count=struct.unpack_from('<2I',raw)
        self.assertEqual(magic,0xD1500001);self.assertEqual(count,10)
        first=struct.unpack_from('<11I5f',raw,8)
        self.assertEqual(first[1],2);self.assertEqual(first[3:5],(0,1))
        self.assertEqual(first[11:13],(240,120))
        self.dll.board_quality_clear();self.assertEqual(self.tail(),raw)

    def test_firmware_policy_text_identical_to_simulation_body(self):
        body=lambda path:Path(path).read_text().split('typedef struct {',1)[1].rsplit('#endif',1)[0]
        self.assertEqual(body(p.COMMON/'load_speed_policy.h'),body(p.NATIVE/'load_speed_scheduler.h'))


if __name__=='__main__':unittest.main()
