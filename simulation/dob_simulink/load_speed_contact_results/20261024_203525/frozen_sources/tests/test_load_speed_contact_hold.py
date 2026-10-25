import ctypes as C
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import prepare_load_speed as p


class ContactHoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=ROOT/'tmp/contact_hold_tests.dll'
        subprocess.run([str(p.reviewed.GCC),'-std=c11','-Os','-Wall','-Wextra','-Werror','-shared',
            '-I',str(p.COMMON),str(ROOT/'tests/load_speed_contact_host.c'),
            str(p.COMMON/'speed_scurve.c'),'-lm','-o',str(cls.path)],check=True,capture_output=True,text=True)

    def setUp(self):
        self.dll=C.CDLL(str(self.path));self.dll.contact_reset()
        self.dll.contact_step.argtypes=[C.POINTER(C.c_double),C.POINTER(C.c_double)];self.now=100000

    def step(self,phase=3,valid=1,level=4,trend=2,mean=.05,enabled=1,base=240):
        self.now+=1000;y=(C.c_double*11)()
        self.dll.contact_step((C.c_double*10)(self.now,phase,enabled,valid,level,1,trend,base,20,mean),y)
        return list(y)

    def begin_slow(self):
        for _ in range(40):y=self.step()
        self.assertEqual(y[0],120)

    def test_cannot_create_new_slow_in_contact_confirm(self):
        for _ in range(400):y=self.step(phase=4)
        self.assertEqual(y[0],240);self.assertEqual(y[8],0)

    def test_contact_holds_existing_selection_without_false_dob_freshness(self):
        self.begin_slow();before=self.step();last_good=before[10]
        for _ in range(500):y=self.step(phase=4,valid=0,mean=float('nan'))
        self.assertEqual(y[0],120);self.assertEqual(y[2],8);self.assertEqual(y[8],1)
        self.assertEqual(y[10],last_good);self.assertEqual(y[5],0)

    def test_cancel_with_good_evidence_requires_real_release_dwell(self):
        self.begin_slow()
        for _ in range(250):self.step(phase=4,valid=0)
        for _ in range(199):y=self.step(level=1,trend=1,mean=0)
        self.assertEqual(y[0],120)
        for _ in range(4):y=self.step(level=1,trend=1,mean=0)
        self.assertEqual(y[0],240)

    def test_cancel_invalid_grace_is_bounded_and_does_not_earn_good_time(self):
        self.begin_slow()
        for _ in range(250):self.step(phase=4,valid=0)
        first=self.step(valid=0);last_good=first[10]
        for _ in range(198):y=self.step(valid=0)
        self.assertEqual(y[0],120);self.assertEqual(y[10],last_good)
        for _ in range(3):y=self.step(valid=0)
        self.assertEqual(y[0],240);self.assertEqual(y[2],5)

    def test_phase_hold_does_not_restart_scurve_or_reverse_sign(self):
        for sign in (1,-1):
            self.setUp()
            for _ in range(40):before=self.step(base=sign*240)
            for _ in range(150):
                y=self.step(phase=4,base=sign*240)
                self.assertEqual(y[0],sign*120)
                self.assertLessEqual(abs(y[7]-before[7]),1.001);before=y

    def test_neutral_torque_stop_fault_and_disable_override_hold(self):
        for phase,base,enabled in [(4,0,1),(0,0,1),(5,0,1),(6,0,1),(7,0,1),(10,0,1),(3,240,0)]:
            self.setUp();self.begin_slow();self.step(phase=4)
            y=self.step(phase=phase,base=base,enabled=enabled)
            self.assertEqual(y[0],base);self.assertEqual(y[1],0)
            self.assertEqual(y[8],0);self.assertEqual(y[9],0)


if __name__=='__main__':unittest.main()
