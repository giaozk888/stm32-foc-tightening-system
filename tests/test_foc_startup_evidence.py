"""Offline only. No serial, reset, flash, bridge or motor access."""
import subprocess
import unittest
import test_latest_original_fsm as latest

FLAGS=latest.FLAGS+['-DFOC_LATEST_ZERO_COUNT_ONLY=1','-DFOC_STARTUP_TRACE=1']

class StartupEvidenceTests(unittest.TestCase):
    def test_linked_candidate_and_old_images_preserved(self):
        for slot in 'ab':
            root=latest.ROOT/f'foc2_app_{slot}/build'
            image=(root/'LatestOriginalStartupEvidence/foc2.bin').read_bytes()
            self.assertIn(b'STARTUP CONFIG ENABLED=1 ROWS=32 FIRST_CAUSE=1',image)
            self.assertIn(b'MAX=OFF SEG_MAX=OFF',image)
            self.assertIn(b'LEASE_US=400000',image)
            for old in ('LatestFeedbackOriginalFsm','LatestFeedbackOriginalFsmCountOnly'):
                self.assertNotIn(b'STARTUP CONFIG ENABLED=1', (root/old/'foc2.bin').read_bytes())

    def test_ring_and_fault_freeze(self):
        latest.OUT.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=latest.OUT/('startup_ring'+opt+'.exe')
            latest.run(latest.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',latest.COMMON,latest.ROOT/'tests/foc_startup_trace_host.c','-o',exe)
            self.assertIn('PASS',latest.run(exe))

    def test_actual_binding_fault_preemption(self):
        for opt in ('-Os','-O2'):
            exe=latest.OUT/('startup_binding'+opt+'.exe')
            latest.run(latest.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',latest.COMMON,*FLAGS,latest.ROOT/'tests/latest_startup_evidence_host.c',
                latest.COMMON/'foc_current_zero.c',latest.COMMON/'foc_zero_median.c',
                latest.COMMON/'foc_zero_robust.c','-o',exe)
            self.assertIn('PASS',latest.run(exe))

    def test_partial_profile_rejected(self):
        flags=[x for x in FLAGS if x!='-DFOC_LATEST_ORIGINAL_FSM=1']
        result=subprocess.run([str(latest.GCC),'-std=c11','-fsyntax-only','-I',str(latest.COMMON),
            *flags,str(latest.ROOT/'tests/latest_startup_evidence_host.c')],capture_output=True)
        self.assertNotEqual(result.returncode,0)

if __name__=='__main__':
    unittest.main()
