import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import outer_completion_full_batch as batch
low=batch.low


class FullBatchTests(unittest.TestCase):
    def test_exact_current_image_and_baseline_files_only(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/outer_completion_full_batch.py')],
            cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('12 mechanical points; no devices',p.stdout)
        self.assertEqual(batch.POINTS,(500,)*3+(600,)*3+(700,)*3+(800,)*3)
        r=json.loads(batch.ROOT_RESTORE.read_text())
        self.assertTrue(r['pass_']);self.assertTrue(r['b_application_not_run'])
        self.assertEqual(r['image_sha256'],batch.previous.SHA)

    def test_operator_gates_before_setup_and_no_extra_motion_flags(self):
        with patch.multiple(low,setup=low.setup,POINTS=low.POINTS,TRIP_RPM=low.TRIP_RPM,
            TRAVEL_DEG=low.TRAVEL_DEG,CLOSURE_SECONDS=low.CLOSURE_SECONDS,
            LIMITS_QUERY=low.LIMITS_QUERY,LIMITS_EXTRA=low.LIMITS_EXTRA),\
             patch.object(batch,'ORIGINAL_SETUP') as setup:
            for args in (['--prepare-off'],['--execute-twelve','missing'],['--restore-b-drive-off','missing']):
                with self.assertRaises(SystemExit):batch.main(args)
            setup.assert_not_called()
            with patch.object(low,'main',return_value=0):batch.main([])
            self.assertEqual(low.POINTS,batch.POINTS)
            self.assertEqual(low.LIMITS_EXTRA,dict(PLAUSIBLE_RPM='1000',REJECT_BUSY='1',OBS_AFTER_ACK='1'))

    def test_readonly_receipt_uses_exact_current_image_not_old_fixed_image(self):
        with patch.object(batch.readonly,'staged',return_value='ok') as staged:
            self.assertEqual(batch.staged(Path('stage'),b'image'),'ok')
            self.assertEqual(staged.call_args.kwargs,dict(expected_sha=batch.previous.SHA,
                expected_elf_sha=batch.previous.ELF_SHA,points=batch.POINTS))
        self.assertNotEqual(batch.previous.SHA,batch.readonly.fixed.SHA)


if __name__=='__main__':unittest.main()
