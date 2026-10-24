import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import readiness_snapshot_batch as batch
low=batch.low


class ReadinessBatchTests(unittest.TestCase):
    def test_offline_exact_new_identity_and_actual_old_restore(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/readiness_snapshot_batch.py')],
            cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('9 mechanical points; no devices',p.stdout)
        batch.image()
        r=json.loads(batch.ROOT_RESTORE.read_text())
        self.assertTrue(r['pass_']);self.assertTrue(r['b_application_not_run'])
        self.assertEqual(r['image_sha256'],batch.previous.SHA)
        self.assertNotEqual(r['image_sha256'],batch.SHA)

    def test_fresh_physical_gates_before_setup_and_fixed_nine_point_plan(self):
        with patch.multiple(low,setup=low.setup,POINTS=low.POINTS,TRIP_RPM=low.TRIP_RPM,
            TRAVEL_DEG=low.TRAVEL_DEG,CLOSURE_SECONDS=low.CLOSURE_SECONDS,
            LIMITS_QUERY=low.LIMITS_QUERY,LIMITS_EXTRA=low.LIMITS_EXTRA),\
             patch.object(batch,'ORIGINAL_SETUP') as setup:
            for args in (['--prepare-off'],['--execute-nine','missing'],['--restore-b-drive-off','missing']):
                with self.assertRaises(SystemExit):batch.main(args)
            setup.assert_not_called()
            with patch.object(low,'main',return_value=0):batch.main([])
            self.assertEqual(low.POINTS,(600,)*3+(700,)*3+(800,)*3)
            self.assertEqual(low.TRIP_RPM,1000);self.assertEqual(low.TRAVEL_DEG,30000)

    def test_rejection_query_no_retry_and_transport_failure_immediate_cleanup(self):
        def board():
            b=object.__new__(batch.ReadinessBoard);b.record={};return b
        command='MOTOR TEST MECH RUN POS 600'
        with patch.object(batch.ORIGINAL_BOARD,'command',side_effect=[
            '1 OK MECH READY FIX=1 VALID=0',RuntimeError('2 ERR MECH NOT_READY'),
            '3 OK MECH READY FIX=1 VALID=1 FAIL=0x00020000 AGE=101']) as send:
            b=board()
            with self.assertRaisesRegex(RuntimeError,'NOT_READY'):b.command(command,.6)
            self.assertIn('AGE=101',b.record['ready_rejection_reply'])
            self.assertEqual(sum(c.args[0]==command for c in send.call_args_list),1)
        with patch.object(batch.ORIGINAL_BOARD,'command',side_effect=[
            '1 OK MECH READY FIX=1 VALID=0',TimeoutError('missing ACK')]) as send:
            b=board()
            with self.assertRaises(TimeoutError):b.command(command,.6)
            self.assertEqual(send.call_count,2)
            self.assertNotIn('ready_rejection_reply',b.record)
        with patch.object(batch.ORIGINAL_BOARD,'command',return_value='1 OK UNKNOWN') as send:
            with self.assertRaisesRegex(RuntimeError,'no motion'):board().command(command,.6)
            self.assertEqual(send.call_count,1)


if __name__=='__main__':unittest.main()
