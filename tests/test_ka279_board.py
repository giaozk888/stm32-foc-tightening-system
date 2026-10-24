from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_torque_chain import ROOT,FROZEN,function
from test_torque350_five_second import expanded
sys.path.insert(0,str(ROOT/'tools'))
import ka279_board as board

class ManualKaTests(unittest.TestCase):
    def test_exact_value_and_unmodified_control(self):
        before=expanded('a','AccelFfAuditGain100');after=expanded('a','Ka279ManualTrial')
        self.assertIn('speed_accel_audit_ka=0.0000279f',after)
        for name in FROZEN+('Protocol_HandleLine','TighteningTask','PowerStage_Disable'):
            self.assertEqual(function(before,name),function(after,name),name)
        board.image()
        board.ff_status('OK AFF ON=1 KA_NA_PER_RPM_S=27900 ACCEL_MAX_RPM_S=200 FF_PEAK_UA=5580 TOKENIZED=1')
        for line in ('OK AFF ON=0','OK AFF ON=1 KA_NA_PER_RPM_S=0'):
            with self.assertRaises(RuntimeError):board.ff_status(line)
        board.friction_status('OK FRC ON=1 I_UA=105000 DB_MRPM=2000 FF_ON=1 KA_NA_PER_RPM_S=27900 TOKENIZED=1',True)

    def test_one_original_owner_no_retry_and_no_false_ab_claim(self):
        r=dict(manual_ka=board.KA,bemf_enabled=False,friction_enabled=True)
        with patch.object(board.gain,'ORIGINAL_MOTION') as owner:
            obj=object();board.motion(obj,r);owner.assert_called_once_with(obj,r)
        with patch.object(board.base,'execute',side_effect=RuntimeError('protection')) as owner:
            with self.assertRaisesRegex(RuntimeError,'protection'):board.execute({},'fake',Path('fake'),b'')
            self.assertEqual(owner.call_count,1)
        new=dict(metrics={k:0 for k in ('accel_mae_rpm','cruise_mae_rpm','overshoot_rpm','iq_ref_peak_a','integrator_peak_a')})
        self.assertFalse(board.comparison(new)['strict_ab'])

    def test_default_files_only_and_fresh_confirmations(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/ka279_board.py')],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)
        with patch.object(board,'setup') as setup:
            for args in (['--prepare-off'],['--execute-powered','missing'],['--restore-b-drive-off','missing']):
                with self.assertRaises(SystemExit):board.main(args)
            setup.assert_not_called()

if __name__=='__main__':unittest.main()
