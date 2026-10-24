import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import outer_completion_board as board
low=board.low


class OuterBoardTests(unittest.TestCase):
    def test_offline_default_proves_actual_restore_and_new_image(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/outer_completion_board.py')],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('1 mechanical points; no devices',p.stdout)
        board.image()
        r=json.loads(board.ROOT_RESTORE.read_text())
        self.assertTrue(r['pass_']);self.assertTrue(r['b_application_not_run'])

    def test_gates_before_hardware_and_exact_readbacks(self):
        with patch.multiple(low,setup=low.setup,POINTS=low.POINTS,TRIP_RPM=low.TRIP_RPM,
            TRAVEL_DEG=low.TRAVEL_DEG,CLOSURE_SECONDS=low.CLOSURE_SECONDS,
            LIMITS_QUERY=low.LIMITS_QUERY,LIMITS_EXTRA=low.LIMITS_EXTRA),\
             patch.object(board,'ORIGINAL_SETUP') as setup:
            for args in (['--prepare-off'],['--execute-once','missing'],['--restore-b-drive-off','missing']):
                with self.assertRaises(SystemExit):board.main(args)
            setup.assert_not_called()
            with patch.object(low,'main',return_value=0):board.main([])
            self.assertEqual(low.POINTS,(600,))
            self.assertEqual(low.LIMITS_EXTRA,dict(PLAUSIBLE_RPM='1000',REJECT_BUSY='1',OBS_AFTER_ACK='1'))


if __name__=='__main__':unittest.main()
