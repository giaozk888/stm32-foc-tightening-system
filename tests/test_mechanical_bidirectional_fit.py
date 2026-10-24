import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import mechanical_bidirectional_fit as paired
import current_pi_compare as compiler
from test_mechanical_identification import simulated


class BidirectionalTests(unittest.TestCase):
    def test_signed_intercepts_joint_separation_and_units(self):
        r=paired.report(simulated())
        self.assertTrue(r['normalized_bidirectional_qualified'],r['problems'])
        s=r['directional_separation']
        for k,v in [('c_plus_a',.09),('c_minus_a',-.07),('coulomb_equivalent_a',.08),('current_bias_a',.01)]:
            self.assertAlmostEqual(s[k],v,places=10)
        m=r['candidate_dob_shadow_model']
        for k,v in [('j_over_kt',.004),('b_over_kt',.002),('coulomb_over_kt',.08),('bias_a',.01)]:
            self.assertAlmostEqual(m[k],v,places=10)
        self.assertIsNone(r['absolute_parameters']);self.assertFalse(r['dob_control_enabled'])
        self.assertFalse(r['parameter_writes']);self.assertFalse(r['kt_independently_identified'])
        json.dumps(r,allow_nan=False)

    def test_missing_direction_quality_fault_and_asymmetry_never_enable_model(self):
        c=simulated();onlypos=[s for s in c if s['rows'][0]['omega_mean_rad_s']>0]
        r=paired.report(onlypos);self.assertFalse(r['normalized_bidirectional_qualified'])
        self.assertIsNone(r['candidate_dob_shadow_model'])
        for mode in ('fault','residual','asymmetric','wrong_command'):
            c=simulated()
            if mode=='fault':c[0]['board_verified']=False
            if mode=='wrong_command':c[0]['expected_sign']=1
            if mode=='residual':
                for i,row in enumerate(c[0]['rows']):row['iq_matched_mean_a']+=.4 if i%2 else -.4
            if mode=='asymmetric':
                for session in c:
                    if session['rows'][0]['omega_mean_rad_s']<0:
                        for row in session['rows']:
                            row['iq_matched_mean_a']+=.004*(row['omega_end_rad_s']-row['omega_start_rad_s'])/row['dt_s']
            r=paired.report(c)
            self.assertFalse(r['normalized_bidirectional_qualified'],mode)
            self.assertIsNone(r['candidate_dob_shadow_model'],mode)
            if mode=='asymmetric':self.assertIn('DIRECTION_ASYMMETRY_J_OVER_KT',r['problems'])

    def test_known_zero_friction_positive_bias_is_not_forced_into_friction(self):
        c=simulated()
        for session in c:
            for row in session['rows']:
                row['iq_matched_mean_a']-=.08*(1 if row['omega_mean_rad_s']>0 else -1)
        r=paired.report(c)
        s=r['directional_separation']
        self.assertAlmostEqual(s['current_bias_a'],.01,places=10)
        self.assertAlmostEqual(s['coulomb_equivalent_a'],0,places=10)

    def test_native_qualified_model_drives_observer_only_not_actuator(self):
        m=paired.report(simulated())['candidate_dob_shadow_model']
        values=','.join(format(m[k],'.12g')+'f' for k in ('j_over_kt','b_over_kt','coulomb_over_kt','bias_a','bandwidth_rad_s','min_speed_rad_s'))
        code=r'''
#include <assert.h>
#include <math.h>
#include "mechanical_dob_shadow.h"
int main(void){
MechanicalNormalizedModel m={'''+values+r''',1};MechanicalDobShadow s;
for(int sign=-1;sign<=1;sign+=2){
 MechanicalDob_Reset(&s,0);
 float w=20.f*sign,external=.05f*sign;
 float iq=m.b_over_kt*w+m.coulomb_over_kt*sign+m.bias_a+external;
 for(unsigned i=0;i<1500;i++)MechanicalDob_Observe(&s,&m,iq,w,.001f,1,0);
 assert(s.valid && fabsf(s.disturbance_a-external)<1e-5f);
 MechanicalDob_Observe(&s,&m,iq,w,.001f,1,1);
 assert(!s.valid && s.status==DOB_SHADOW_FAULT);
}
m.qualified=0;MechanicalDob_Observe(&s,&m,.2f,20,.001f,1,0);
assert(!s.valid && s.status==DOB_SHADOW_UNCONFIGURED);
return 0;}
'''
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('mechanical-bidirectional-dob'+opt+'.exe')
            p=subprocess.run([str(compiler.GCC),'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(exe)],input=code,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        source=(ROOT/'firmware_common/mechanical_dob_shadow.h').read_text()
        for forbidden in ('foc_iq_ref_A','MotorControl_Set','TIM1','PWM_SetDuty'):
            self.assertNotIn(forbidden,source)

    def test_load_requires_nine_independent_real_sessions_and_matching_build_flags(self):
        pos=ROOT/'foc2_app_a/build/MechanicalReadinessSnapshotCandidate/foc2.elf'
        neg=ROOT/'foc2_app_a/build/MechanicalReverseIdentificationCandidate/foc2.elf'
        paired.matching_profiles(pos,neg)
        with self.assertRaises(ValueError):paired.matching_profiles(neg,pos)
        actual=ROOT/'tmp/mechanical-ident-batch-1792675998078677600.json'
        captures,context=paired.load_batch(actual,pos,1)
        self.assertEqual(len(captures),9);self.assertEqual(context[:3],(.000046875,.00034866,True))
        with self.assertRaises(ValueError):paired.load_batch(actual,pos,-1)
        d=json.loads(actual.read_text());d['runs'][1]=d['runs'][0]
        with patch.object(Path,'read_text',return_value=json.dumps(d)):
            with self.assertRaises(ValueError):paired.load_batch(actual,pos,1)


if __name__=='__main__':unittest.main()
