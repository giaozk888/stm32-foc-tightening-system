import ctypes as C
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import prepare_load_gain_opt as p


class OptPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=ROOT/'tmp/load_gain_opt_tests.dll'
        subprocess.run([str(p.prior.old.reviewed.GCC),'-std=c11','-O2','-Wall','-Wextra','-Werror','-shared',
            '-I',str(p.WORK),str(ROOT/'tests/load_gain_opt_host.c'),'-lm','-o',str(cls.path)],check=True)

    def setUp(self):
        self.dll=C.CDLL(str(self.path));self.dll.gain_reset();self.now=100000
        self.dll.gain_step.argtypes=[C.POINTER(C.c_double),C.POINTER(C.c_double)]

    def step(self,profile=4,valid=1,level=4,trend=2,mean=.08,phase=3,dt=1000,fault=0,enabled=1):
        self.now+=dt;y=(C.c_double*10)()
        self.dll.gain_step((C.c_double*13)(self.now,phase,1,fault,enabled,1,valid,level,1,trend,mean,.25,profile),y)
        return list(y)

    def test_floor_is_nonzero_only_with_qualified_data_and_bounded(self):
        for _ in range(100):y=self.step(valid=0,level=1,trend=1,mean=0)
        self.assertEqual(y[0],0)
        for _ in range(80):y=self.step(level=1,trend=1,mean=0)
        self.assertAlmostEqual(y[0],.1,places=6);self.assertEqual(y[2],0)
        for _ in range(200):y=self.step()
        self.assertEqual(y[0],.25)

    def test_fast_rise_shortens_only_gain_slew_not_evidence_dwell(self):
        for _ in range(30):y=self.step(profile=2)
        self.assertEqual(y[0],0)
        y=self.step(profile=2);self.assertAlmostEqual(y[0],.005,places=6)
        for _ in range(51):y=self.step(profile=2)
        self.assertEqual(y[0],.25)

    def test_light_release_returns_to_floor_then_bad_data_expires_to_zero(self):
        for _ in range(400):self.step()
        for _ in range(300):y=self.step(level=1,trend=1,mean=0)
        self.assertAlmostEqual(y[0],.1,places=6);last_good=y[7]
        for _ in range(5):y=self.step(valid=0)
        self.assertAlmostEqual(y[0],.1,places=6);self.assertEqual(y[6],0)
        for _ in range(200):y=self.step(valid=0)
        self.assertEqual(y[0],0);self.assertEqual(y[7],last_good)

    def test_stop_fault_other_phases_duplicate_and_time_gap(self):
        for _ in range(150):self.step()
        before=self.step();self.assertEqual(self.step(dt=0),before)
        self.assertEqual(self.step(valid=0,dt=90000)[0],before[0])
        self.assertEqual(self.step(fault=1)[0],0)
        self.assertEqual(self.step(enabled=0)[0],0)
        self.assertEqual(self.step(phase=4)[0],0)
        self.assertEqual(self.step(phase=5)[0],0)


class OptHostTests(unittest.TestCase):
    def setUp(self):
        self.new=C.CDLL(str(p.WORK/'load_gain_opt_host.dll'))
        self.old=C.CDLL(str(p.BASELINE/'load_gain_host.dll'))
        for dll in (self.new,self.old):
            dll.dob_host_reset.argtypes=[C.POINTER(C.c_double)]
            dll.dob_host_step.argtypes=[C.c_double,C.POINTER(C.c_double),C.POINTER(C.c_double)]
            dll.dob_host_state_size.restype=C.c_uint
            dll.dob_host_save.argtypes=[C.c_void_p];dll.dob_host_restore.argtypes=[C.c_void_p]

    def step(self,dll,k,sat=0,stop=0,truth=0):
        t=k*.001;y=(C.c_double*80)()
        u=(C.c_double*16)(240 if t>=.2 else 0,25.1327412287,.20,0,0,.005,1,sat,0,1,0,t*1440,1,truth,stop,0)
        dll.dob_host_step(t,u,y);return list(y)

    def test_original_profile_and_fixed_off_are_bitwise_preserved(self):
        for profile,enabled in ((0,1),(0,0),(1,1)):
            cfg=(C.c_double*4)(enabled,.25,.025,profile)
            self.new.dob_host_reset(cfg);self.old.dob_host_reset(cfg)
            for k in range(2700):
                sat=2500<=k<2530
                self.assertEqual(self.step(self.new,k,sat),self.step(self.old,k,sat))

    def test_all_new_profiles_preserve_saturation_expiry_caps_and_stop(self):
        for profile in (2,3,4):
            self.new.dob_host_reset((C.c_double*4)(1,.25,.025,profile))
            for k in range(2500):self.step(self.new,k)
            buf=C.create_string_buffer(self.new.dob_host_state_size());self.new.dob_host_save(buf)
            a=[self.step(self.new,k,1) for k in range(2500,2540)]
            self.new.dob_host_restore(buf);self.assertEqual(a,[self.step(self.new,k,1) for k in range(2500,2540)])
            self.assertTrue(all(0<=y[68]<=.25 and abs(y[9])<=.025001 and abs(y[7])<=.500001 for y in a))
            self.assertTrue(all(y[25]!=2 and y[78]==0 for y in a[1:]))
            self.assertEqual(a[-1][9],0)
            y=self.step(self.new,2540,stop=1);self.assertEqual(y[7],0);self.assertEqual(y[68],0)


if __name__=='__main__':unittest.main()
