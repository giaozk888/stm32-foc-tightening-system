import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import mechanical_encoder_fix_board as fixed
low=fixed.low


class EncoderFixBoardTests(unittest.TestCase):
    def test_image_identity_and_real_previous_restore_files_only(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/mechanical_encoder_fix_board.py')],
            capture_output=True,text=True,cwd=ROOT)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('1 mechanical points; no devices',p.stdout)
        fixed.image()
        r=json.loads(fixed.ROOT_RESTORE.read_text())
        self.assertTrue(r['pass_']);self.assertTrue(r['b_application_not_run'])
        self.assertEqual(r['metadata'][8:10],[227964,627317606])

    def test_fresh_operator_gates_before_setup(self):
        with patch.multiple(low,setup=low.setup,POINTS=low.POINTS,TRIP_RPM=low.TRIP_RPM,
            TRAVEL_DEG=low.TRAVEL_DEG,CLOSURE_SECONDS=low.CLOSURE_SECONDS,
            LIMITS_QUERY=low.LIMITS_QUERY,LIMITS_EXTRA=low.LIMITS_EXTRA),\
             patch.object(fixed,'ORIGINAL_SETUP') as setup:
            for args in (['--prepare-off'],['--execute-once','missing'],['--restore-b-drive-off','missing']):
                with self.assertRaises(SystemExit):fixed.main(args)
            setup.assert_not_called()

    def test_only_one_600_point_and_strict_fix_limits(self):
        with patch.multiple(low,setup=low.setup,POINTS=low.POINTS,TRIP_RPM=low.TRIP_RPM,
            TRAVEL_DEG=low.TRAVEL_DEG,CLOSURE_SECONDS=low.CLOSURE_SECONDS,
            LIMITS_QUERY=low.LIMITS_QUERY,LIMITS_EXTRA=low.LIMITS_EXTRA),\
             patch.object(low,'main',return_value=0) as main:
            fixed.main(['--execute-once','stage','--operator-present-whole-batch-drive-on-no-alarm-05a'])
            self.assertEqual(low.POINTS,(600,))
            self.assertEqual(low.LIMITS_EXTRA,dict(PLAUSIBLE_RPM='1000',REJECT_BUSY='1'))
            self.assertIn('--execute-six',main.call_args.args[0])
            self.assertNotIn('--prepare-off',main.call_args.args[0])


if __name__=='__main__':unittest.main()
