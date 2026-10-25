import ctypes as C
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import prepare_load_gain as p


class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=ROOT/'tmp/load_gain_tests.dll'
        subprocess.run([str(p.old.reviewed.GCC),'-std=c11','-O2','-Wall','-Wextra','-Werror','-shared',
            '-I',str(p.NATIVE),str(ROOT/'tests/load_gain_host.c'),'-lm','-o',str(cls.path)],check=True)

    def setUp(self):
        self.dll=C.CDLL(str(self.path));self.dll.gain_reset()
        self.dll.gain_step.argtypes=[C.POINTER(C.c_double),C.POINTER(C.c_double)];self.now=100000

    def step(self,phase=3,running=1,fault=0,enabled=1,adaptive=1,valid=1,level=4,trend=2,mean=.08,cap=.25,dt=1000):
        self.now+=dt;y=(C.c_double*10)()
        self.dll.gain_step((C.c_double*12)(self.now,phase,running,fault,enabled,adaptive,valid,level,1,trend,mean,cap),y)
        return list(y)

    def test_gain_ramps_after_real_high_confirmation_and_never_exceeds_cap(self):
        for _ in range(30):y=self.step()
        self.assertEqual(y[0],0)
        previous=0
        for _ in range(400):
            y=self.step();self.assertLessEqual(y[0]-previous,.001001);previous=y[0]
        self.assertEqual(y[0],.25)

    def test_light_release_has_dwell_then_fades(self):
        for _ in range(450):self.step()
        for _ in range(199):y=self.step(level=1,trend=1,mean=0)
        self.assertEqual(y[2],1)
        for _ in range(110):y=self.step(level=1,trend=1,mean=0)
        self.assertEqual(y[0],0);self.assertEqual(y[2],0)

    def test_bad_samples_earn_no_credit_and_do_not_refresh_last_good(self):
        for _ in range(450):self.step()
        good=self.step()[7]
        for _ in range(5):y=self.step(valid=0)
        self.assertEqual(y[0],.25);self.assertEqual(y[6],0);self.assertEqual(y[7],good)
        for _ in range(210):y=self.step(valid=0)
        self.assertEqual(y[0],0);self.assertEqual(y[2],0);self.assertEqual(y[7],good)
        y=self.step();self.assertEqual(y[6],0)

    def test_spike_or_negative_directional_load_cannot_raise_gain(self):
        self.step()
        for _ in range(400):y=self.step(level=1,trend=1,mean=0)
        self.assertEqual(y[0],0)
        for _ in range(400):y=self.step(level=4,mean=-.1)
        self.assertEqual(y[0],0)

    def test_lifecycle_fixed_off_duplicate_and_time_gap(self):
        self.assertEqual(self.step(adaptive=0,cap=2)[0],.25)
        for _ in range(400):self.step()
        before=self.step();self.assertEqual(self.step(dt=0),before)
        self.assertEqual(self.step(dt=90000,valid=0)[0],before[0])
        self.assertEqual(self.step(fault=1)[0],0)
        self.assertEqual(self.step(enabled=0)[0],0)
        self.assertEqual(self.step(phase=4)[0],0)
        self.assertEqual(self.step(phase=5)[0],0)


class FullHostTests(unittest.TestCase):
    def setUp(self):
        self.dll=C.CDLL(str(p.WORK/'load_gain_host.dll'))
        self.dll.dob_host_reset.argtypes=[C.POINTER(C.c_double)]
        self.dll.dob_host_step.argtypes=[C.c_double,C.POINTER(C.c_double),C.POINTER(C.c_double)]
        self.dll.dob_host_state_size.restype=C.c_uint
        self.dll.dob_host_save.argtypes=[C.c_void_p];self.dll.dob_host_restore.argtypes=[C.c_void_p]
        self.reset()

    def reset(self,adaptive=1,enabled=1):self.dll.dob_host_reset((C.c_double*4)(enabled,.25,.025,adaptive))

    def step(self,k,sat=0,stop=0,fault=0,iq=.20):
        t=k*.001;y=(C.c_double*80)()
        u=(C.c_double*16)(240 if t>=.2 else 0,25.1327412287,iq,0,0,.005,1,sat,0,1,0,t*1440,1,0,stop,fault)
        self.dll.dob_host_step(t,u,y);return list(y)

    def test_saturation_does_not_refresh_compensation_and_expires_on_original_clock(self):
        self.reset(adaptive=0)
        for k in range(2500):self.step(k)
        out=[self.step(k,sat=1) for k in range(2500,2540)]
        self.assertTrue(any(int(y[12])&128 for y in out))
        self.assertTrue(all(y[78]==0 for y in out[1:]))
        self.assertTrue(all(y[25]!=2 for y in out[1:])) # Original TRACK=2 cannot persist under SAT128.
        self.assertEqual(out[-1][9],0)
        self.assertTrue(all(y[11] for y in out[5:])) # Estimation itself still runs on limited input.

    def test_snapshot_duplicate_and_stop_fault_remain_deterministic(self):
        for k in range(2500):self.step(k)
        buf=C.create_string_buffer(self.dll.dob_host_state_size());self.dll.dob_host_save(buf)
        a=[self.step(k) for k in range(2500,2600)];self.dll.dob_host_restore(buf)
        self.assertEqual(a,[self.step(k) for k in range(2500,2600)])
        self.assertEqual(a[-1],self.step(2599,stop=1))
        y=self.step(2600,stop=1);self.assertEqual(y[7],0);self.assertEqual(y[68],0)
        self.reset()
        for k in range(2000):self.step(k)
        y=self.step(2000,fault=1);self.assertEqual(y[7],0);self.assertEqual(y[68],0)

    def test_off_is_zero_and_policy_never_changes_reference_or_working_iq_limit(self):
        self.reset(enabled=0)
        rows=[self.step(k) for k in range(3000)]
        self.assertTrue(all(y[9]==0 and y[68]==0 for y in rows))
        self.assertTrue(all(y[33]==y[34] and y[35]==0 for y in rows))
        self.assertTrue(all(y[55]==.5 for y in rows if y[54]==3))

    def test_fixed_mode_matches_frozen_controller_exactly_without_saturation(self):
        old=C.CDLL(str(ROOT/'simulation/dob_simulink/load_speed_contact_results/20261024_203525/contact_host.dll'))
        old.dob_host_reset.argtypes=[C.POINTER(C.c_double)]
        old.dob_host_step.argtypes=[C.c_double,C.POINTER(C.c_double),C.POINTER(C.c_double)]
        old.dob_host_reset((C.c_double*3)(1,.25,.025));self.reset(adaptive=0)
        rpm=position=0
        for k in range(3000):
            t=k*.001;position+=rpm*.006
            u=(C.c_double*16)(240 if t>=.2 else 0,rpm*.10471975511966,.16,0,0,.005,1,0,0,1,0,position,1,0,0,0)
            a=(C.c_double*66)();b=(C.c_double*80)();old.dob_host_step(t,u,a);self.dll.dob_host_step(t,u,b)
            self.assertFalse(int(a[12])&128)
            self.assertEqual(list(a),list(b)[:66]);rpm=a[0]

    def test_independent_fixture_truth_is_not_a_gain_input(self):
        def run(truth):
            self.reset();out=[]
            for k in range(2500):
                t=k*.001;y=(C.c_double*80)()
                u=(C.c_double*16)(240 if t>=.2 else 0,25.1327412287,.20,0,0,.005,1,0,0,1,0,t*1440,1,truth,0,0)
                self.dll.dob_host_step(t,u,y);out.append(list(y))
            return out
        self.assertEqual(run(0),run(1))


if __name__=='__main__':unittest.main()
