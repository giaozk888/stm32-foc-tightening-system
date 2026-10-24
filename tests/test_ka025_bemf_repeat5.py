import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import ka025_bemf_repeat5 as batch


class RepeatTests(unittest.TestCase):
    def test_confirmation_precedes_setup(self):
        with patch.object(batch.board,'setup') as setup:
            with self.assertRaises(SystemExit):batch.main(['--execute-five','missing'])
            setup.assert_not_called()

    def test_summary_does_not_invent_missing_settling_or_mix_modes(self):
        rows=[dict(metrics=dict(manual_ka=batch.board.KA,bemf_enabled=True,
             accel_mae_rpm=x,settling_time_ms=None)) for x in (1.,2.,3.,4.,5.)]
        result=batch.summarize(rows)
        self.assertTrue(result['completed'])
        self.assertEqual(result['metrics']['accel_mae_rpm']['mean'],3.)
        self.assertEqual(result['metrics']['settling_time_ms']['missing'],5)
        self.assertIsNone(result['metrics']['settling_time_ms']['mean'])
        rows[0]['metrics']['bemf_enabled']=False
        with self.assertRaises(ValueError):batch.summarize(rows)

    def test_protection_on_first_run_stops_without_next_start(self):
        parent=dict(operator_present_whole_batch=True,attempts=[],runs=[],receipt_path='parent')
        row=dict(receipt_path='run',hardware_attempted=True,final_cpu_halted=True)
        with patch.object(Path,'read_text',return_value=json.dumps(dict(bemf_enabled=True,manual_ka=batch.board.KA))),\
             patch.object(batch.board,'image',return_value=b'image'),\
             patch.object(batch.base,'staged'),patch.object(batch.prior,'checkpoint'),\
             patch.object(batch.prior,'new_run',return_value=row),\
             patch.object(batch.board,'execute',side_effect=RuntimeError('protection')) as start,\
             patch.object(batch.prior,'next_run') as next_run:
            with self.assertRaisesRegex(RuntimeError,'protection'):batch.execute(Path('plan'),parent)
            self.assertEqual(start.call_count,1)
            next_run.assert_not_called()
            self.assertEqual(parent['runs'],[])

    def test_exactly_five_safe_runs_reuse_one_protected_owner(self):
        parent=dict(operator_present_whole_batch=True,attempts=[],runs=[],receipt_path='parent')
        def new(*args):return dict(receipt_path='run'+str(args[-1]),final_outputs_off=True,final_cpu_halted=True)
        def first(row,*args):row['metrics']=dict(manual_ka=batch.board.KA,bemf_enabled=True)
        with patch.object(Path,'read_text',return_value=json.dumps(dict(bemf_enabled=True,manual_ka=batch.board.KA))),\
             patch.object(batch.board,'image',return_value=b'image'),\
             patch.object(batch.base,'staged'),patch.object(batch.prior,'checkpoint'),\
             patch.object(batch.prior,'new_run',side_effect=new),\
             patch.object(batch.board,'execute',side_effect=first) as start,\
             patch.object(batch.prior,'metrics',side_effect=lambda row:dict(manual_ka=batch.board.KA,bemf_enabled=True)),\
             patch.object(batch.prior,'next_run') as next_run:
            batch.execute(Path('plan'),parent)
            self.assertTrue(parent['pass_']);self.assertEqual(len(parent['runs']),5)
            self.assertEqual(start.call_count,1);self.assertEqual(next_run.call_count,4)


if __name__=='__main__':unittest.main()
