import ctypes
import hashlib
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import current_pi_compare as compare
from test_torque350_five_second import expanded
from test_torque_chain import function


class CurrentPiCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old,cls.og=compare.compile_pi(False,ROOT/'tmp/current-pi-host-test')
        cls.new,cls.ng=compare.compile_pi(True,ROOT/'tmp/current-pi-host-test')

    def test_actual_c_pi_gains_and_first_update(self):
        for dll,g in ((self.old,self.og),(self.new,self.ng)):
            state=compare.State();v=(ctypes.c_float*2)()
            dll.step(ctypes.byref(state),.1,-.2,0.,0.,v)
            self.assertAlmostEqual(state.d,g[2]*.1*50e-6,places=7)
            self.assertAlmostEqual(v[0],g[0]*.1+state.d,places=7)
            self.assertAlmostEqual(v[1],g[1]*-.2+state.q,places=7)
        self.assertAlmostEqual(self.og[0],.08,places=7)
        self.assertAlmostEqual(self.og[2],188.,places=5)
        self.assertAlmostEqual(self.ng[0],.03775566,places=6)
        self.assertAlmostEqual(self.ng[1],.02107381,places=6)
        self.assertAlmostEqual(self.ng[2],1470.26536,places=3)

    def test_vector_saturation_and_existing_integrator_clamp(self):
        for dll,g in ((self.old,self.og),(self.new,self.ng)):
            s=compare.State();v=(ctypes.c_float*2)()
            for _ in range(1000):
                dll.step(ctypes.byref(s),100.,-100.,0.,0.,v)
                self.assertLessEqual(v[0]**2+v[1]**2,1.600001**2)
                self.assertLessEqual(abs(s.d),.750001)
                self.assertLessEqual(abs(s.q),.750001)

    def test_legacy_preprocess_identical_pi_and_other_owners_frozen(self):
        baseline=expanded('a','Tightening240rpmFriction105OnCandidate')
        old=expanded('a','CurrentPiLegacyCompare');new=expanded('a','CurrentPiIdentifiedCandidate')
        self.assertEqual(function(baseline,'FOC_CurrentLoopStep'),function(old,'FOC_CurrentLoopStep'))
        baseline_bin=ROOT/'foc2_app_a/build/Tightening240rpmFriction105OnCandidate/foc2.bin'
        legacy_bin=ROOT/'foc2_app_a/build/CurrentPiLegacyCompare/foc2.bin'
        self.assertEqual(baseline_bin.read_bytes(),legacy_bin.read_bytes())
        for name in ('FOC_EncoderSpeedUpdate','ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage',
                     'FocCurrentValidation_Push','PowerStage_Disable','FOC_ResetController'):
            self.assertEqual(function(old,name),function(new,name))
        before=function(old,'FOC_CurrentLoopStep');after=function(new,'FOC_CurrentLoopStep')
        start=before.index('err_d = foc_id_ref_A - id_A;')
        # Surrounding FOC/transform/PWM body is unchanged; only gain constants differ.
        self.assertEqual(before[:start],after[:after.index('err_d = foc_id_ref_A - id_A;')])
        self.assertEqual(before[before.index('v_alpha = vd * c - vq * s;'):],
                         after[after.index('v_alpha = vd * c - vq * s;'):])

    def test_model_response_and_sign_symmetry(self):
        for dll,g in ((self.old,self.og),(self.new,self.ng)):
            for axis in (0,1):
                pos=compare.simulate(dll,g,axis,.35)
                neg=compare.simulate(dll,g,axis,-.35)
                self.assertLess(pos['settled_mean_error_mA'],.35*.02*1000)
                self.assertEqual(pos['rise_to_90_ms'],neg['rise_to_90_ms'])
                self.assertAlmostEqual(pos['peak_abs_current_a'],neg['peak_abs_current_a'],places=7)

    def test_formal_b_no_candidate_binding_and_stable_image_hash(self):
        self.assertNotIn('current_pi_identified_candidate', (ROOT/'foc2_app_b/Core/Src/main.c').read_text())
        # The previously confirmed B BIN must stay byte-for-byte unchanged.
        stable=ROOT/'foc2_app_b/build/FrictionBUnchanged/foc2.bin'
        self.assertEqual(hashlib.sha256(stable.read_bytes()).hexdigest(),
                         '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')


if __name__=='__main__':unittest.main()
