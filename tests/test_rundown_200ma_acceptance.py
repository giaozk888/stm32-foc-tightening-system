"""Exact new full-FSM profile: mocked tests only, no live devices."""
import contextlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
from unittest.mock import patch
import unittest
import test_rundown_guard_acceptance as previous_tests
from test_torque_chain import FROZEN, function

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import rundown_200ma_acceptance as runner


class FullFsm200Tests(previous_tests.AcceptanceTests):
    def setUp(self):
        binding=patch.object(previous_tests,'runner',runner); binding.start()
        self.addCleanup(binding.stop)

    def test_exact_new_image_and_preserved_B665(self):
        self.assertEqual(len(runner.image()),228220)
        self.assertEqual(runner.old.zero.latest_meta(runner.baseline())[2:6],(2,0,0,689))
        with patch.object(runner,'IMAGE',runner.torque_previous.IMAGE):
            with self.assertRaises(ValueError): runner.image()

    def test_confirmed_prestart_resume_rejects_ambiguous_start(self):
        with self.assertRaisesRegex(ValueError,'No pre-START resume'):
            runner.resume_receipt(runner.BASE,runner.image())

    def test_full_only_cli_no_speed_or_resume(self):
        for args in (['--execute-powered','x','--drive-on-no-alarm-fixed-05a-emergency-off-ready'],
                     ['--resume-prestart-powered','x']):
            with patch.object(sys,'argv',['fsm',*args]),patch.object(runner,'image') as image, \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): runner.main()
                image.assert_not_called()

    def test_fsm_profile_excludes_fixed_iq_and_preserves_math(self):
        for slot in 'ab':
            texts=[]
            for preset in ('TorqueChain200mADirectLimitDiagnostic','Rundown200mADirectLimitTrial'):
                base=ROOT/f'foc2_app_{slot}/build/{preset}'
                commands=json.loads((base/'compile_commands.json').read_text())
                command=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
                if preset=='Rundown200mADirectLimitTrial':
                    self.assertNotIn('-DFOC_TORQUE_CHAIN_DIAG=',command)
                    self.assertIn('-DFOC_LOADED_FSM_TRIAL=1',command)
                texts.append(subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',command),cwd=base,
                             capture_output=True,text=True,check=True).stdout)
            # Power ownership/admission intentionally changes from IQ-only to
            # the existing FSM. Current math, pipeline and protection do not.
            for name in FROZEN+('MotorControl_SetIq','FocFp_PushRawSafety','FocOcConfirm_Push',
                               'FocFeedbackSafety_Push','ProtectedLoop_GuardIrqBody'):
                self.assertEqual(function(texts[0],name),function(texts[1],name),name)
            self.assertNotIn('TorqueChain_Command(',texts[1])
            self.assertIn('CL_MAX_US=12000000U',texts[1])


if __name__=='__main__': unittest.main()
