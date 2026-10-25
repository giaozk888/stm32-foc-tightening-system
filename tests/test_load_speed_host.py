import ctypes as C
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class HostTests(unittest.TestCase):
    def setUp(self):
        self.dll=C.CDLL(str(ROOT/'simulation/dob_simulink/load_speed_work/load_speed_host.dll'))
        self.dll.dob_host_step.argtypes=[C.c_double,C.POINTER(C.c_double),C.POINTER(C.c_double)]
        self.dll.dob_host_reset.argtypes=[C.POINTER(C.c_double)]
        self.dll.dob_host_state_size.restype=C.c_uint
        self.dll.dob_host_save.argtypes=[C.c_void_p];self.dll.dob_host_restore.argtypes=[C.c_void_p]
        self.reset()

    def reset(self):self.dll.dob_host_reset((C.c_double*3)(1,.25,.025))

    def step(self,k,truth=0,stop=0,fault=0,enabled=1):
        # Deliberately synthetic controller contract test, not a plant test.
        t=k*.001;u=(C.c_double*16)(240 if t>=.2 else 0,25.1327412287,.20,0,0,.005,1,0,0,1,
                                 enabled,t*1440,1,truth,stop,fault)
        y=(C.c_double*64)();self.dll.dob_host_step(t,u,y);return list(y)

    def test_fixture_truth_never_changes_the_controller(self):
        a=[self.step(k,truth=0) for k in range(2500)]
        self.reset();b=[self.step(k,truth=1) for k in range(2500)]
        self.assertEqual(a,b)
        self.assertTrue(any(y[35] for y in a))
        self.assertTrue(all(y[33]==y[34] for y in a if y[46]!=3))

    def test_full_controller_snapshot_and_duplicate_epoch_are_deterministic(self):
        for k in range(1600):self.step(k)
        saved=C.create_string_buffer(self.dll.dob_host_state_size());self.dll.dob_host_save(saved)
        first=[self.step(k) for k in range(1600,1700)]
        self.dll.dob_host_restore(saved)
        second=[self.step(k) for k in range(1600,1700)]
        self.assertEqual(first,second)
        self.assertEqual(second[-1],self.step(1699,enabled=0))

    def test_stop_and_fault_override_the_scheduler(self):
        for event in ('stop','fault'):
            self.reset()
            for k in range(2500):self.step(k)
            y=self.step(2500,**{event:1})
            self.assertEqual(y[7],0)
            self.assertEqual(y[35],0)
            self.assertEqual(y[46],0 if event=='stop' else 10)


if __name__=='__main__':unittest.main()
