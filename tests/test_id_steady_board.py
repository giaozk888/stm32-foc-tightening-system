import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import id_steady_board as board


class IdSteadyBoardTests(unittest.TestCase):
    def test_files_only_default_new_image_actual_b1043_restore(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/id_steady_board.py')],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('3 mechanical points; no devices',p.stdout)
        board.image()
        r=json.loads(board.ROOT_RESTORE.read_text())
        self.assertTrue(r['pass_'] and r['b_application_not_run'])
        self.assertEqual(r['image_sha256'],board.previous.SHA)
        self.assertEqual(r['metadata'][5],1043)

    def test_fresh_gates_precede_setup_three_runs_and_no_threshold_changes(self):
        low=board.low
        with patch.multiple(low,setup=low.setup,POINTS=low.POINTS,TRIP_RPM=low.TRIP_RPM,
            TRAVEL_DEG=low.TRAVEL_DEG,CLOSURE_SECONDS=low.CLOSURE_SECONDS,LIMITS_QUERY=low.LIMITS_QUERY,
            LIMITS_EXTRA=low.LIMITS_EXTRA),patch.object(board,'ORIGINAL_SETUP') as setup:
            for args in (['--prepare-off'],['--execute-three','missing'],['--restore-b-drive-off','missing']):
                with self.assertRaises(SystemExit):board.main(args)
            setup.assert_not_called()
            with patch.object(low,'main',return_value=0):board.main([])
            self.assertEqual(low.POINTS,(600,600,600))
            self.assertEqual((low.TRIP_RPM,low.TRAVEL_DEG,low.CLOSURE_SECONDS),(1000,30000,11.))

    def test_exact_stats_configuration_unused_before_existing_dob_and_run_owner(self):
        run='MOTOR TEST MECH RUN POS 600'
        def new():b=object.__new__(board.IdStatsBoard);b.record={};return b
        cfg='1 OK IDSTATS '+' '.join(k+'='+v for k,v in board.CONFIG.items())
        initial='2 OK IDSTATS V=1 STATE=0 N=0 GOOD_US=0 BAD_US=0 FEEDBACK=0'
        with patch.object(board.previous.DobBoard,'command',side_effect=[cfg,initial,'3 OK MECH QUEUED RPM=600']) as send:
            b=new();self.assertIn('QUEUED',b.command(run))
            self.assertEqual([c.args[0] for c in send.call_args_list],
                ['MOTOR TEST MECH IDSTATS CFG','MOTOR TEST MECH IDSTATS',run])
        for replies in ([cfg.replace('THRESH_UA=50000','THRESH_UA=100000'),initial],
                        [cfg,initial.replace('N=0','N=100')]):
            with patch.object(board.previous.DobBoard,'command',side_effect=replies) as send:
                with self.assertRaises(RuntimeError):new().command(run)
                self.assertFalse(any(c.args[0]==run for c in send.call_args_list))
        with patch.object(board.previous.DobBoard,'command') as send:
            with self.assertRaises(ValueError):new().command('MOTOR TEST MECH RUN NEG 600')
            send.assert_not_called()

    def test_poor_statistics_retained_without_retry_or_control_change(self):
        row=dict(receipt_path='receipt',ram_capture='ram')
        captured=dict(fixed_window_complete=False,steady_throughout=False,current_data_coverage=.2,
                      dob_capture=dict(meta={}))
        with patch.object(board,'ORIGINAL_RUN') as run,patch.object(board.report,'decode',return_value=captured),\
             patch.object(board.outer,'decode_trace',return_value={}),\
             patch.object(board.readiness,'decode_readiness',return_value={}):
            board.run_point(row)
            run.assert_called_once()
            self.assertFalse(row['id_steady_quality']['window_complete'])
            self.assertFalse(row['id_steady_quality']['threshold_changed'] or row['id_steady_quality']['feedback_enabled'])
        with patch.object(board,'ORIGINAL_RUN',side_effect=RuntimeError('protection')),\
             patch.object(board.report,'decode') as decode,patch.object(board.outer,'decode_trace',return_value={}),\
             patch.object(board.readiness,'decode_readiness',return_value={}):
            with self.assertRaisesRegex(RuntimeError,'protection'):board.run_point(row)
            decode.assert_not_called()


if __name__=='__main__':unittest.main()
