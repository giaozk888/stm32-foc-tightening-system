"""No hardware: six fixed L shots, quality vs safety, exact firmware pins."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import motor_ident_l_repeat_batch as b


class LBatchTests(unittest.TestCase):
    def test_default_files_pins_no_devices(self):
        self.assertEqual(len(b.image()),215156)
        p=subprocess.run([sys.executable,str(ROOT/'tools/motor_ident_l_repeat_batch.py')],
            capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('no devices',p.stdout)

    def exercise(self,outcomes):
        seen=[]
        def point(row,name,source,before,data,first):
            seen.append((row['axis'],row['repeat'],first))
            row.update(point_outcome=outcomes[len(seen)-1],final_capture='unused',final_sha256='same',
                final_cpu_halted=True,final_outputs_off=True)
        parent=dict(powered_no_alarm=True,locked_fixture=True)
        with patch.object(b.base,'staged',return_value=(Path('unused'),b'x')),\
             patch.object(b.base.old.prior,'checkpoint'),patch.object(Path,'read_bytes',return_value=b'x'),\
             patch.object(b.base.old.zero,'digest',return_value='same'),patch.object(b.time,'sleep'),\
             patch.dict(b.run.__dict__,{}),patch.dict(b.axis.__dict__,{}):
            b.execute_batch(parent,'offline',Path('unused'),b'x',point_runner=point)
        return seen,parent

    def test_all_six_quality_failures_complete_and_no_fake_inductance(self):
        seen,parent=self.exercise(['QUALITY_FAILED']*6)
        self.assertEqual([(a,r) for a,r,_ in seen],list(b.PLAN))
        self.assertEqual([x[2] for x in seen],[True]+[False]*5)
        self.assertTrue(parent['pass_']);self.assertFalse(parent['remaining_not_run'])
        self.assertIsNone(parent['comparison']['ld']);self.assertIsNone(parent['comparison']['lq'])
        self.assertFalse(parent['comparison']['automatic_pi_write'])

    def test_protection_stops_without_retry_or_next_reset(self):
        seen,parent=self.exercise(['QUALITY_FAILED','PROTECTION_STOP'])
        self.assertEqual(len(seen),2);self.assertEqual(len(parent['remaining_not_run']),4)
        self.assertFalse(parent['pass_'])

    def test_historical_safe_timing_exit_can_continue_but_safety_cannot(self):
        r=json.loads((ROOT/'tmp/motor-ident-ld-run-1792559233960715200.json').read_text())
        r.update(axis='LD',repeat=1,image_sha256=b.SHA,elf_sha256=b.ELF_SHA)
        # Explicit quality failure; original clean terminal safety proof retained.
        self.assertEqual(b.classify(r),'QUALITY_FAILED')
        for mutate in (lambda x:x['live_guard'].update(cl_flags=1),
                       lambda x:x['snapshot']['timing'].update(deadline_miss=1),
                       lambda x:x['snapshot']['timing'].update(actual_late_count=1),
                       lambda x:x['safe'].update(SD='1'),
                       lambda x:x.update(excitation_attempts=0)):
            bad=copy.deepcopy(r);mutate(bad)
            self.assertNotIn(b.classify(bad),('QUALITY_FAILED','CONDITIONAL_FIT'))


if __name__=='__main__':unittest.main()
