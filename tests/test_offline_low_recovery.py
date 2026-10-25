import ctypes as C
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'simulation/dob_simulink/low_recovery_work'
sys.path.insert(0,str(ROOT/'tools'))
class Host:
    def __init__(self,name):
        self.dll=C.CDLL(str(WORK/(name+'.dll')))
        self.dll.dob_host_observe.argtypes=[C.POINTER(C.c_double),C.POINTER(C.c_double)]
        self.dll.dob_host_reset.argtypes=[C.POINTER(C.c_double)]
        self.dll.dob_host_save.argtypes=[C.c_void_p];self.dll.dob_host_restore.argtypes=[C.c_void_p]
        self.dll.dob_host_state_size.restype=C.c_uint
        self.reset()
    def reset(self):self.dll.dob_host_reset((C.c_double*3)(1,.25,.025));self.k=0
    def step(self,w=25.13274123,id=.005,valid=1,sat=0,flags=0,run=1,fault=0):
        self.k+=1;t=100000+self.k*1000
        u=(C.c_double*14)(t+20,t,1000,w,id,.16,self.k*20,t-20,t,valid,sat,flags,run,fault)
        y=(C.c_double*33)();self.dll.dob_host_observe(u,y);return list(y)
    def warm(self,negative=False):
        for _ in range(1000):y=self.step(w=-25.13274123 if negative else 25.13274123)
        return y
class LowRecoveryTests(unittest.TestCase):
    def setUp(self):self.base=Host('baseline');self.fast=Host('retain')
    def test_no_low_case_original_outputs_bitwise_equal(self):
        for _ in range(1300):
            a,b=self.base.step(),self.fast.step()
            for k in [*range(7),*range(14,24),*range(25,33)]:self.assertEqual(a[k],b[k],k)
    def test_short_low_uses_real_confirmation_not_missing_time_credit(self):
        self.base.warm();before=self.fast.warm();elapsed=before[3]
        for _ in range(60):
            self.base.step(w=.5);y=self.fast.step(w=.5);self.assertEqual(y[1],0)
        outputs=[]
        for _ in range(40):outputs.append((self.base.step(),self.fast.step()))
        first=next(i for i,(a,b) in enumerate(outputs) if b[1])
        self.assertGreaterEqual(first,20);self.assertLess(first,30)
        self.assertFalse(outputs[first][0][1]);self.assertEqual(outputs[first][1][9],1)
        self.assertLessEqual(outputs[first][1][3]-elapsed,.0021)
        self.assertTrue(all(abs(b[4])<=.025001 for a,b in outputs))
    def test_long_gap_drops_cache_and_does_not_restart_original_cold_path(self):
        self.base.warm();self.fast.warm()
        for _ in range(150):self.base.step(w=.5);self.fast.step(w=.5)
        for _ in range(400):
            a,b=self.base.step(),self.fast.step();self.assertEqual(a[1],b[1]);self.assertEqual(a[3],b[3])
        self.assertEqual(b[9],0);self.assertEqual(b[10],1)
    def test_noisy_or_saturated_return_falls_back_without_second_warmup(self):
        self.base.warm();self.fast.warm()
        for _ in range(60):self.base.step(w=.5);self.fast.step(w=.5)
        for i in range(400):
            a,b=self.base.step(sat=i<170),self.fast.step(sat=i<170)
            self.assertEqual(a[1],b[1]);self.assertEqual(a[3],b[3])
        self.assertEqual(b[9],0);self.assertEqual(b[10],1)
    def test_spike_source_loss_reverse_and_fault_cannot_use_fast_cache(self):
        for failure in ('spike','source','reverse','nan','fault'):
            self.fast.reset();self.fast.warm()
            for _ in range(10):self.fast.step(w=.5)
            kwargs={'w':.5}
            if failure=='spike':kwargs['id']=.7
            if failure=='source':kwargs['valid']=0
            if failure=='reverse':kwargs['w']=-.5
            if failure=='nan':kwargs['id']=float('nan')
            if failure=='fault':kwargs['fault']=1
            y=self.fast.step(**kwargs);self.assertFalse(y[1]);self.assertEqual(y[9],0)
            self.assertEqual(y[10],1)
            if failure=='spike':self.assertLess(y[14],.01)
            if failure=='fault':self.assertEqual(y[20],16)
    def test_snapshot_roundtrip_in_pending_low_path(self):
        self.fast.warm()
        for _ in range(30):self.fast.step(w=.5)
        size=self.fast.dll.dob_host_state_size();snapshot=C.create_string_buffer(size)
        self.fast.dll.dob_host_save(snapshot);k=self.fast.k
        first=[self.fast.step() for _ in range(35)]
        self.fast.dll.dob_host_restore(snapshot);self.fast.k=k
        second=[self.fast.step() for _ in range(35)]
        self.assertEqual(first,second)
    def test_200ms_candidate_keeps_unsafe_saturation_fallback(self):
        h=Host('retain200');h.warm()
        for _ in range(60):h.step(w=.5)
        for k in range(400):y=h.step(sat=k<220)
        self.assertEqual(y[9],0);self.assertEqual(y[10],1);self.assertTrue(y[1])
if __name__=='__main__':unittest.main()
