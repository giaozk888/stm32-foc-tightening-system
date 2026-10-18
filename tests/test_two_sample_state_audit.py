"""Offline evidence boundaries and unchanged state machine regressions."""
import json
import re
import sys
import unittest
import test_foc_fast_current_reject as fast
sys.path.insert(0,str(fast.ROOT/'tools'))
import two_sample_fault_audit as audit


class TwoSampleAuditTests(unittest.TestCase):
    def test_unchanged_core_invariants_and_real_early_recovery(self):
        for opt in ('-Os','-O2'):
            exe=fast.OUT/('two_sample_state_audit'+opt+'.exe')
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',fast.COMMON,*fast.FLAGS,
                fast.ROOT/'tests/foc_two_sample_state_audit_host.c','-o',exe)
            self.assertIn('PASS unchanged',fast.run(exe))

    def test_arm_layout_verified_not_host_pointer_guess(self):
        obj=fast.OUT/'two_sample_layout.o'
        fast.run(fast.ARM/'arm-none-eabi-gcc.exe','-std=c11','-Os','-mcpu=cortex-m4','-mthumb',
            '-mfpu=fpv4-sp-d16','-mfloat-abi=hard','-Wall','-Wextra','-Werror','-pedantic',
            '-I',fast.COMMON,*fast.FLAGS,'-c',fast.ROOT/'tests/foc_two_sample_layout.c','-o',obj)
        audit.verify_layout(obj)

    def test_missing_fault_frames_never_fabricated(self):
        receipt=json.loads((fast.ROOT/'safety_backups/protected-closed-loop-20261014/'
            'current-fault-trace-trial-1792238818857368100.json').read_text('utf-8'))
        end=dict(zip(audit.KEYS,[475373,3544,3347,162,61,3,3,1,34,1514,1545,1563,1561,1,3]))
        row=audit.summarize(receipt,end)
        self.assertFalse(row['fault_window_captured'])
        self.assertFalse(row['production_fix_justified'])
        self.assertFalse(row['real_fault_regression_available'])
        self.assertEqual(row['trace_last_seq'],28537)
        self.assertEqual(row['fault_seq'],499373)
        frames=row['partial_fault_evolution']
        self.assertEqual([f['unresolved_consecutive'] for f in frames],[1,2,3])
        self.assertIsNone(frames[0]['raw'])
        self.assertEqual(frames[-1]['d_old'],49)
        self.assertIsNone(frames[-1]['d_candidate'])
        self.assertIsNone(frames[-1]['candidate_before'])
        self.assertEqual(frames[-1]['candidate_after'],[1563,1561])

    def test_early_replay_is_exact_recorded_window_not_final_fault(self):
        receipt=json.loads((fast.ROOT/'safety_backups/protected-closed-loop-20261014/'
            'current-fault-trace-trial-1792238818857368100.json').read_text('utf-8'))
        source=(fast.ROOT/'tests/foc_two_sample_state_audit_host.c').read_text('utf-8')
        body=source.split('static const CurrentRawPair early[]={',1)[1].split('};',1)[0]
        pairs=[tuple(map(int,m)) for m in re.findall(r'\{(\d+),(\d+)\}',body)]
        frames=receipt['trace']['frames']
        self.assertEqual(pairs,[(r['raw_u'],r['raw_v']) for r in frames])
        self.assertEqual([r['discriminator_result'] for r in frames],
                         [0 if i==9 else 1 for i in range(16)])
        self.assertTrue(all(r['discriminator_executed']==1 for r in frames))
        self.assertEqual(receipt['trace']['header']['fault_seq'],0)


if __name__=='__main__':
    unittest.main()
