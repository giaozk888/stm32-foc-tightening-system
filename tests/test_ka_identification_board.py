import copy
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_torque_chain import ROOT
sys.path.insert(0,str(ROOT/'tools'))
import ka_identification_board as board


class KaBoardTests(unittest.TestCase):
    @staticmethod
    def row():
        f=dict(seq=1,start_us=100,end_us=100100,flags=0,speed_start_rpm=20.,speed_end_rpm=40.,
            mean_iq_a=.15,mean_friction_a=.105,mean_speed_ref_rpm=35.,mean_speed_meas_rpm=30.)
        return dict(ka_capture=dict(samples=2401,windows=[f]),tokenized_decoded=[dict(decoded=x) for x in (
            'KAI T seq=1 start_us=100 end_us=100100 flags=0',
            'KAI S seq=1 speed_start=20 speed_end=40 ref=35 meas=30',
            'KAI I seq=1 iq_mean=0.15 fric_mean=0.105')])

    def test_files_only_default_and_gates_before_any_setup(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/ka_identification_board.py')],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)
        with patch.object(board,'setup') as setup:
            for args in (['--stage-off'],['--execute-powered','missing.json'],['--restore-b-drive-off','missing.json']):
                with self.assertRaises(SystemExit):board.main(args)
            setup.assert_not_called()

    def test_exact_zero_ka_motion_owner_not_gain_setter_or_sweep(self):
        row=dict(gain_percent=0,bemf_enabled=False,friction_enabled=True)
        with patch.object(board.gain,'ORIGINAL_MOTION') as run,patch.object(board.gain,'motion') as gain:
            board.motion(object(),row);run.assert_called_once();gain.assert_not_called()
        for k,v in (('gain_percent',25),('bemf_enabled',True),('friction_enabled',False)):
            bad=dict(row);bad[k]=v
            with patch.object(board.gain,'ORIGINAL_MOTION') as run:
                with self.assertRaises(ValueError):board.motion(object(),bad)
                run.assert_not_called()

    def test_log_join_same_sequence_values_and_no_missing(self):
        r=self.row();self.assertEqual(board.check_logs(r),1)
        for change in ('mixed','value','missing'):
            bad=copy.deepcopy(r)
            if change=='mixed':bad['tokenized_decoded'][1]['decoded']=bad['tokenized_decoded'][1]['decoded'].replace('seq=1','seq=2')
            elif change=='value':bad['ka_capture']['windows'][0]['mean_iq_a']=.2
            else:bad['tokenized_decoded'].pop()
            with self.assertRaises(RuntimeError):board.check_logs(bad)

    def test_original_protection_and_coverage_never_bypassed_for_fit(self):
        with patch.object(board.gain.prior,'metrics',side_effect=RuntimeError('protection')),patch.object(board,'check_logs') as logs:
            with self.assertRaisesRegex(RuntimeError,'protection'):board.classify(self.row())
            logs.assert_not_called()
        with patch.object(board.gain.prior,'metrics',return_value={}):
            with self.assertRaisesRegex(RuntimeError,'Incomplete Ka'):board.classify(self.row())


if __name__=='__main__':unittest.main()
