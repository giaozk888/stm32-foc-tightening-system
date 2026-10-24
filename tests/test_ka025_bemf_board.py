import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import ka025_bemf_board as board

class BoardTests(unittest.TestCase):
    def test_exact_readback_no_gain_and_original_owner(self):
        board.image()
        board.ff_status('OK AFF ON=1 KA_NA_PER_RPM_S=46875 ACCEL_MAX_RPM_S=200 FF_PEAK_UA=9375 TOKENIZED=1')
        with self.assertRaises(RuntimeError):board.ff_status('OK AFF ON=1 KA_NA_PER_RPM_S=27900')
        with patch.object(board.gain,'ORIGINAL_MOTION') as owner:
            for enabled in (False,True):
                board.motion(object(),dict(manual_ka=board.KA,bemf_enabled=enabled,friction_enabled=True))
            self.assertEqual(owner.call_count,2)

    def test_mismatched_plan_and_protection_never_retry(self):
        with patch.object(Path,'read_text',return_value=json.dumps(dict(bemf_enabled=False))),\
             patch.object(board.base,'execute') as run:
            with self.assertRaises(ValueError):board.execute(dict(bemf_enabled=True),'fake',Path('fake'),b'')
            run.assert_not_called()
        with patch.object(Path,'read_text',return_value=json.dumps(dict(bemf_enabled=True))),\
             patch.object(board.base,'execute',side_effect=RuntimeError('protection')) as run:
            with self.assertRaisesRegex(RuntimeError,'protection'):board.execute(dict(bemf_enabled=True),'fake',Path('fake'),b'')
            self.assertEqual(run.call_count,1)

    def test_default_no_devices_and_confirmation(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/ka025_bemf_board.py')],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)
        with patch.object(board,'setup') as setup:
            for args in (['--prepare-off'],['--execute-powered','missing'],['--restore-b-drive-off','missing']):
                with self.assertRaises(SystemExit):board.main(args)
            setup.assert_not_called()

if __name__=='__main__':unittest.main()
