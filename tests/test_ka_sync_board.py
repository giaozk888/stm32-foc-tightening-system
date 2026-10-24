from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_torque_chain import ROOT
sys.path.insert(0,str(ROOT/'tools'))
import ka_sync_board as board


class KaSyncBoardTests(unittest.TestCase):
    @staticmethod
    def row():
        return dict(start_attempts=0,preflight_pass=True,commands=[],motor_stack_preflight=dict(VALID='1',FREE_B='500'),
            all_app_private_unchanged=True,final_cpu_halted=True,final_outputs_off=True,
            outputs=dict(VTOR=0x08008000,SD=0,BDTR=0,CCER=0),
            snapshot=dict(first_fault=dict(valid=0),cur_confirm=dict(fault=0),
                timing=dict(wall_max_us=32,deadline_miss=0,actual_late_count=0,actual_margin_min_us=14)),
            sync_saved=dict(meta=dict(count=0),publisher_max_cycles=80,publisher_max_us=80/170),
            sync_current_saved=dict(version=200,source_seq=100),
            postflight={'MOTOR TEST STATUS':'OK STATE=1 USED=0 FAULT=0 FLAGS=0 SD=0 MOE=0 CCER=0'})

    def test_only_ready_no_start_fault_timing_stack_or_torn_publication_rejected(self):
        board.accept(self.row())
        for key,value in (('start_attempts',1),('preflight_pass',False),('final_outputs_off',False)):
            r=self.row();r[key]=value
            with self.assertRaises(RuntimeError):board.accept(r)
        for section,key,value in (('motor_stack_preflight','FREE_B','100'),('sync_current_saved','version',201)):
            r=self.row();r[section][key]=value
            with self.assertRaises(RuntimeError):board.accept(r)
        r=self.row();r['snapshot']['timing']['deadline_miss']=1
        with self.assertRaises(RuntimeError):board.accept(r)
        r=self.row();r['sync_saved']['meta']['count']=64
        with self.assertRaises(RuntimeError):board.accept(r)
        r=self.row();r['commands']=[dict(command='START')]
        with self.assertRaises(RuntimeError):board.accept(r)

    def test_motion_explicitly_forbidden_and_preflight_source_never_sends_start(self):
        with self.assertRaises(RuntimeError):board.no_motion(None,{})
        import inspect
        source=inspect.getsource(board.execute_preflight)
        self.assertNotIn("command('START')",source);self.assertNotIn("send('START')",source)
        self.assertIn('wait_timing',source);self.assertIn('motor_stack',source)

    def test_files_only_default_and_confirmation_before_setup(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/ka_sync_board.py')],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)
        with patch.object(board,'setup') as setup:
            for args in (['--stage-off'],['--preflight-powered','missing'],['--restore-b-drive-off','missing']):
                with self.assertRaises(SystemExit):board.main(args)
            setup.assert_not_called()


if __name__=='__main__':unittest.main()
