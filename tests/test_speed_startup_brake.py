"""Exact C kernel, recorded-window replay and contact reachability; no devices."""
import ctypes
import json
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
GCC=r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'
TRACE=ROOT/'tmp/loaded-fsm-motion-1792300223073650000-overspeed-analysis.json'


class SpeedStartupBrakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out=ROOT/'tests/speed_startup_brake_build'
        out.mkdir(exist_ok=True)
        cls.libs=[]
        for opt in ('Os','O2'):
            path=out/(opt+'.dll')
            subprocess.run([GCC,'-std=c11','-'+opt,'-Wall','-Wextra','-Werror',
                '-pedantic','-shared','-I',str(ROOT/'firmware_common'),
                str(ROOT/'tests/speed_startup_brake_host.c'),'-o',str(path)],check=True)
            lib=ctypes.CDLL(str(path))
            lib.speed_test_step.argtypes=[ctypes.POINTER(ctypes.c_float)]+[ctypes.c_float]*3+[
                ctypes.c_uint,ctypes.POINTER(ctypes.c_uint32)]
            lib.speed_test_step.restype=ctypes.c_float
            lib.speed_test_apply.argtypes=[ctypes.c_float]*5+[ctypes.POINTER(ctypes.c_uint32)]
            lib.speed_test_apply.restype=ctypes.c_float
            cls.libs.append(lib)

    def test_same_direction_integral_growth_bounded_and_symmetric(self):
        for lib in self.libs:
            for sign in (-1,1):
                flags=ctypes.c_uint32()
                value=lib.speed_test_apply(0,sign*.0004,sign*20,0,.001,ctypes.byref(flags))
                self.assertAlmostEqual(value,sign*.0002,places=7)
                self.assertEqual(flags.value,1)

    def test_existing_braking_integral_and_unwind_are_preserved(self):
        for lib in self.libs:
            flags=ctypes.c_uint32()
            value=lib.speed_test_apply(.2,.1996,20,21,.001,ctypes.byref(flags))
            self.assertAlmostEqual(value,.1996,places=6)
            self.assertEqual(flags.value,0)
            value=lib.speed_test_apply(-.1,-.101,20,40,.001,ctypes.byref(flags))
            self.assertAlmostEqual(value,-.101,places=6)
            self.assertEqual(flags.value,0)

    def test_brake_clears_only_integral_that_pushes_current_rotation(self):
        for lib in self.libs:
            for sign in (-1,1):
                flags=ctypes.c_uint32()
                value=lib.speed_test_apply(sign*.237,sign*.232,sign*20,sign*26,
                    .001,ctypes.byref(flags))
                self.assertEqual(value,0)
                self.assertEqual(flags.value,2)

    def test_stall_can_still_reach_existing_contact_threshold(self):
        for lib in self.libs:
            for sign in (-1,1):
                integral=ctypes.c_float()
                flags=ctypes.c_uint32()
                first=None
                for tick in range(2000):
                    ref=sign*min(20,(tick+1)*.2)
                    output=lib.speed_test_step(ctypes.byref(integral),ref,0,.001,1,
                        ctypes.byref(flags))
                    self.assertLessEqual(abs(output),.400001)
                    if sign*output>=.3 and first is None:
                        first=tick+1
                self.assertIsNotNone(first)
                self.assertLess(first,1600)

    def test_true_fault_window_old_policy_reproduced_new_policy_brakes(self):
        rows=json.loads(TRACE.read_text('utf-8'))['rows']
        for lib in self.libs:
            old=ctypes.c_float(rows[0]['speed_integral_inferred_A'])
            new=ctypes.c_float(old.value)  # Deliberately retain worst old history.
            flags=ctypes.c_uint32()
            for row in rows[1:]:
                dt=row['dt_us']*1e-6
                previous=lib.speed_test_step(ctypes.byref(old),row['ref_rpm'],
                    row['filtered_rpm'],dt,0,ctypes.byref(flags))
                self.assertAlmostEqual(previous,row['iq_ref_A'],places=5)
                current=lib.speed_test_step(ctypes.byref(new),row['ref_rpm'],
                    row['filtered_rpm'],dt,1,ctypes.byref(flags))
                if row['filtered_rpm']>=row['ref_rpm']+5:
                    self.assertLess(current,0)
            self.assertGreater(old.value,0)
            self.assertLess(new.value,0)

    def test_output_and_integral_limits_still_apply(self):
        for lib in self.libs:
            for sign in (-1,1):
                integral=ctypes.c_float(sign*.35)
                flags=ctypes.c_uint32()
                output=lib.speed_test_step(ctypes.byref(integral),sign*120,0,.001,1,
                    ctypes.byref(flags))
                self.assertLessEqual(abs(output),.400001)
                self.assertLessEqual(abs(integral.value),.350001)


if __name__=='__main__':
    unittest.main()
