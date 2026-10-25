import ctypes as C
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import prepare_load_speed as p


class SchedulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=ROOT/'tmp/load_speed_policy_tests.dll'
        subprocess.run([str(p.reviewed.GCC),'-std=c11','-O2','-Wall','-Wextra','-Werror','-shared',
            '-I',str(p.COMMON),'-I',str(p.NATIVE),str(ROOT/'tests/load_speed_scheduler_host.c'),
            str(p.COMMON/'speed_scurve.c'),'-lm','-o',str(cls.path)],check=True,capture_output=True,text=True)

    def setUp(self):
        self.lib=C.CDLL(str(self.path));self.lib.schedule_step.argtypes=[C.POINTER(C.c_double),C.POINTER(C.c_double)]
        self.lib.schedule_reset();self.now=100000

    def step(self,phase=3,enabled=1,valid=1,level=4,trend_valid=1,trend=2,base=240,contact=20,mean=.05):
        self.now+=1000;u=(C.c_double*10)(self.now,phase,enabled,valid,level,trend_valid,trend,base,contact,mean)
        y=(C.c_double*8)();self.lib.schedule_step(u,y);return list(y)

    def slow(self):
        for _ in range(40):y=self.step()
        self.assertEqual(y[0],120)

    def test_only_rundown_and_disabled_identity(self):
        for phase in (0,1,2,4,5,6,7,8,9,10):
            for _ in range(60):y=self.step(phase=phase)
            self.assertEqual(y[0],240);self.assertEqual(y[1],0)
        for _ in range(60):y=self.step(enabled=0)
        self.assertEqual(y[0],240);self.assertEqual(y[3],0)

    def test_high_requires_real_continuous_evidence_and_releases_with_hysteresis(self):
        for _ in range(25):y=self.step()
        self.assertEqual(y[0],240)
        for _ in range(20):self.step(valid=0)
        y=self.step();self.assertEqual(y[4],24000)  # Missing epochs did not earn dwell credit.
        for _ in range(10):y=self.step()
        self.assertEqual(y[0],120)
        for _ in range(250):y=self.step(level=1,trend=1,mean=0)
        self.assertEqual(y[0],120)  # minimum300ms slow dwell still holds.
        for _ in range(70):y=self.step(level=1,trend=1,mean=0)
        self.assertEqual(y[0],240)

    def test_short_invalid_holds_long_invalid_returns_through_original_scurve(self):
        self.slow()
        for _ in range(100):y=self.step(valid=0)
        self.assertEqual(y[0],120)
        previous=y
        for _ in range(110):
            y=self.step(valid=0)
            self.assertLessEqual(abs(y[7]-previous[7]),1.001)
            previous=y
        self.assertEqual(y[0],240);self.assertEqual(y[2],5)

    def test_sign_bounds_and_no_target_near_contact(self):
        for base in (240,-240,80,-80,20):
            self.setUp()
            for _ in range(70):y=self.step(base=base)
            self.assertLessEqual(abs(y[0]),abs(base))
            self.assertEqual(y[0]<0,base<0)
            if abs(base)>=120:self.assertGreaterEqual(abs(y[0]),120)

    def test_retarget_keeps_original_acceleration_and_jerk_limits(self):
        previous=None
        for k in range(4000):
            y=self.step(level=4 if k<1200 else 1,trend=2 if k<1200 else 1,mean=.05 if k<1200 else 0)
            self.assertLessEqual(abs(y[7]),200.01)
            if previous is not None:self.assertLessEqual(abs(y[7]-previous[7]),1.001)
            previous=y
        self.assertAlmostEqual(y[6],240,places=3)


if __name__=='__main__':unittest.main()
