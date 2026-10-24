"""Only the requested travel range/default/RAM override changes in new A."""
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from test_torque_chain import GCC,FROZEN,function
from test_torque350_five_second import expanded

ROOT=Path(__file__).resolve().parents[1]

class Travel20000CandidateTests(unittest.TestCase):
    def test_complete_control_and_protection_functions_frozen(self):
        old=expanded('a','Tightening240rpmCandidate')
        new=expanded('a','Tightening240rpmTravel20000Candidate')
        for name in FROZEN+('IntentPort_Config','TighteningTask','MotorControl_SetSpeed',
                'MotorControl_SetIq','LatestOriginal_Admit','LatestOriginal_RecipeReady',
                'ProtectedLoop_PwmCommitPermit','FocFeedbackSafety_Push','FocOcConfirm_Push'):
            self.assertEqual(function(old,name),function(new,name),name)
        before=function(old,'TightenParams_ApplyRundown240Candidate')
        after=function(new,'TightenParams_ApplyRundown240Candidate')
        self.assertEqual(after.count('recipe_state.params.max_travel_deg=20000U;'),1)
        self.assertEqual(before,after.replace('    recipe_state.params.max_travel_deg=20000U;\n',''))
        self.assertIn('TRAVEL=20000deg RAM only',new)
        self.assertIn('CL_SPEED_RPM=240U',new); self.assertIn('CL_OVERSPEED_RPM=300U',new)

    def test_default_off_separate_preset_and_old_images_preserved(self):
        cm=(ROOT/'foc2_app_a/CMakeLists.txt').read_text()
        self.assertRegex(cm,r'option\(FOC_RUNDOWN240_TRAVEL20000 [^\n]+ OFF\)')
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())
        p=next(p for p in presets['configurePresets'] if p['name']=='Tightening240rpmTravel20000Candidate')
        self.assertEqual(p['inherits'],'Tightening240rpmCandidate')
        self.assertEqual(p['cacheVariables'],{'FOC_RUNDOWN240_TRAVEL20000':'ON'})
        self.assertNotIn('Tightening240rpmTravel20000Candidate',(ROOT/'foc2_app_b/CMakePresets.json').read_text())
        for path,sha in [('foc2_app_a/build/Tightening240rpmCandidate/foc2.bin',
                         '478715341f0b6e52e58a9a2c5ff818257369f4e0c82fa76a40d7bede0076443d'),
                        ('foc2_app_b/build/TighteningCommonModeCandidate/foc2.bin',
                         '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')]:
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)

    def test_travel_profile_cannot_be_enabled_alone(self):
        p=subprocess.run([GCC,'-x','c','-','-fsyntax-only','-I',str(ROOT/'firmware_common'),
            '-DFOC_RUNDOWN240_TRAVEL20000=1'],input='#include "foc_rundown240_candidate.h"\n',
            capture_output=True,text=True,timeout=10)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('20000deg travel requires',p.stderr)

if __name__=='__main__': unittest.main()
