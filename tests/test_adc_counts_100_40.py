"""A-only requested thresholds; no devices or fabricated real-fault replay."""
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from test_torque_chain import FROZEN,function
from test_torque350_five_second import expanded
import test_foc_fast_current_reject as fast

ROOT=Path(__file__).resolve().parents[1]
PRESET='Tightening240rpmAdc100Return40Candidate'

class Adc100Return40Tests(unittest.TestCase):
    def test_compiled_boundaries_and_independent_real_safety_at_os_o2(self):
        out=ROOT/'tests/adc_counts_100_40_build'; out.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=out/('thresholds'+opt+'.exe')
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',fast.COMMON,*fast.FLAGS,'-DFOC_CURRENT_JUMP_THRESHOLD_COUNTS=100U',
                '-DFOC_CURRENT_RETURN_TOL_COUNTS=40U',ROOT/'tests/adc_counts_100_40_host.c','-o',exe)
            self.assertIn('PASS 100/40 inclusive boundaries',fast.run(exe))

    def test_only_three_uses_of_the_two_selected_thresholds_change(self):
        old=expanded('a','Tightening240rpmTravel20000Candidate')
        new=expanded('a',PRESET)
        for name in FROZEN+('FocFeedbackSafety_Push','FocOcConfirm_Push','FocFp_PushRawSafety',
                'ProtectedLoop_PwmCommitPermit','LatestOriginal_Admit','IntentPort_Config',
                'TighteningTask','Encoder_ElectricalAngleRad','MotorControl_SetSpeed','MotorControl_SetIq'):
            before=function(old,name); after=function(new,name)
            if name=='FocCurrentValidation_Push':
                for current,prior in (('d_old<=100U','d_old<=60U'),
                        ('d_old<=40U','d_old<=25U'),('d_cand<=100U','d_cand<=60U')):
                    self.assertEqual(after.count(current),1,current)
                    after=after.replace(current,prior)
            self.assertEqual(before,after,name)
        command=function(new,'ProtectedLoop_Command')
        self.assertIn('100U,40U,25U,3U',command.replace(' ','').replace('\n',''))

    def test_default_off_a_only_explicit_definitions(self):
        cm=(ROOT/'foc2_app_a/CMakeLists.txt').read_text()
        self.assertRegex(cm,r'option\(FOC_ADC_COUNTS_100_40_CANDIDATE [^\n]+ OFF\)')
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())
        p=next(p for p in presets['configurePresets'] if p['name']==PRESET)
        self.assertEqual(p['inherits'],'Tightening240rpmTravel20000Candidate')
        self.assertEqual(p['cacheVariables'],{'FOC_ADC_COUNTS_100_40_CANDIDATE':'ON'})
        self.assertNotIn(PRESET,(ROOT/'foc2_app_b/CMakePresets.json').read_text())
        commands=json.loads((ROOT/f'foc2_app_a/build/{PRESET}/compile_commands.json').read_text())
        command=next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
        for flag in ('FOC_CURRENT_JUMP_THRESHOLD_COUNTS=100U','FOC_CURRENT_RETURN_TOL_COUNTS=40U'):
            self.assertEqual(command.count('-D'+flag),1)
        for unchanged in ('FOC_CURRENT_CONFIRM_TOL_COUNTS','FOC_CURRENT_UNRESOLVED_LIMIT'):
            self.assertNotIn('-D'+unchanged,command)
        self.assertIn('-DFOC_CURRENT_FAULT_TRACE_ENABLE=0',command)

    def test_previous_images_and_default_thresholds_preserved(self):
        for name,sha in [('foc2_app_a/build/Tightening240rpmTravel20000Candidate/foc2.bin',
                         '585410c17c75142dc07db3a6b6567500a212b167435f108a59b3b4364f2c2325'),
                        ('foc2_app_b/build/TighteningCommonModeCandidate/foc2.bin',
                         '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')]:
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),sha)
        defaults=(ROOT/'firmware_common/foc_current_fast_reject.h').read_text()
        self.assertIn('#define FOC_CURRENT_JUMP_THRESHOLD_COUNTS 60U',defaults)
        self.assertIn('#define FOC_CURRENT_RETURN_TOL_COUNTS 25U',defaults)

if __name__=='__main__': unittest.main()
