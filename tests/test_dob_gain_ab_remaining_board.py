import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import dob_gain_ab_remaining_board as r
b=r.b


class RemainingTests(unittest.TestCase):
    def test_exact_real_prefix_and_no_start_proof_files_only(self):
        rows,pins,x,safe=r.verified_original()
        self.assertEqual(len(rows),9);self.assertEqual(len(pins),9)
        self.assertEqual(x['start_attempts'],0)
        self.assertEqual([x['dob_gain_requested'] for x in rows],[.25,.5]*4+[.25])
    def test_completed_prefix_never_rerun_only_eleven_new(self):
        prefix=[dict(receipt_path='prefix'+str(i),dob_gain_requested=g) for i,g in enumerate(b.SCHEDULE[:9])]
        parent=dict(baseline_restore_receipt='baseline',manual_resume_authorized=True);seen=[]
        def run(row,*args):
            seen.append((row['trial_index'],row['dob_gain_requested']))
            row.update(pass_=True,actual_gain_ram=row['dob_gain_requested'],final_cpu_halted=True)
        with patch.object(b,'image',return_value=b'A'),patch.object(b.raw,'run_one',side_effect=run),patch.object(b.base.old.prior,'checkpoint'):
            b.execute_twenty(Path('newstage'),parent,verified_prefix=prefix)
        self.assertEqual(seen,list(zip(range(10,21),b.SCHEDULE[9:])))
        self.assertEqual(len(parent['runs']),20)
        self.assertEqual(parent['comparison']['groups']['0.25']['runs'],10)
        self.assertEqual(parent['comparison']['groups']['0.5']['runs'],10)
    def test_missing_fresh_gates_prevents_every_operation(self):
        for args in [['--prepare-off'],['--execute-eleven','missing']]:
            with patch.object(r,'prepare_off') as off,patch.object(r,'execute_remaining') as execute:
                with self.assertRaises(SystemExit):r.main(args)
                off.assert_not_called();execute.assert_not_called()
    def test_any_original_start_attempt_forbids_resume(self):
        parent=json.loads(r.ORIGINAL.read_text());bad=json.loads(r.INTERRUPTED.read_text());bad['start_attempts']=1
        with patch.object(Path,'read_text',side_effect=[json.dumps(parent),json.dumps(bad)]):
            with self.assertRaisesRegex(ValueError,'no-START'):r.verified_original()
    def test_manual_authorization_required_and_new_protection_stops(self):
        prefix=[dict(receipt_path='prefix'+str(i),dob_gain_requested=g) for i,g in enumerate(b.SCHEDULE[:9])]
        with self.assertRaisesRegex(ValueError,'manually authorized'):
            b.execute_twenty(Path('stage'),{},verified_prefix=prefix)
        with patch.object(b,'image',return_value=b'A'),patch.object(b.raw,'run_one',side_effect=RuntimeError('protection')) as run,patch.object(b.base.old.prior,'checkpoint'):
            with self.assertRaisesRegex(RuntimeError,'protection'):
                b.execute_twenty(Path('stage'),dict(baseline_restore_receipt='baseline',manual_resume_authorized=True),verified_prefix=prefix)
            self.assertEqual(run.call_count,1)


if __name__=='__main__':unittest.main()
