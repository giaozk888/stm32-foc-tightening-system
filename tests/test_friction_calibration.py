"""No device access; exercise actual C admission table/measurement and report."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
import re
from test_torque_chain import GCC,ROOT
from test_torque350_five_second import expanded
from test_torque_chain import FROZEN,function
sys.path.insert(0,str(ROOT/'tools'))
import friction_calibration_report as report


class CalibrationTests(unittest.TestCase):
    def test_c_measurement(self):
        out=ROOT/'tmp/friction-cal-host.exe'
        source=r'''
#include <assert.h>
#include "friction_calibration.h"
int main(void) {
 int32_t rpm=0;
 assert(Fcal_Parse("MOTOR TEST FCAL RUN NEG 80",&rpm) && rpm==-80);
 assert(!Fcal_Parse("MOTOR TEST FCAL RUN POS 300",&rpm));
 assert(!Fcal_Parse("START",&rpm));
 for(int sign=-1;sign<=1;sign+=2) {
 FrictionCalibration s={.rpm=sign*80,.active=1};
 for(unsigned n=0;n<4000;++n)
   Fcal_Observe(&s,sign*80,sign*80,0,sign*.1f,sign*.1f,.001f,sign*(float)n*.48f,.001f,1);
 Fcal_Finish(&s,1);assert(s.passed && s.valid_s>3.4f);
 assert(fabsf(s.iq_sum/s.valid_s-sign*.1f)<.0001f);
 unsigned before=s.valid;
 Fcal_Observe(&s,80,80,0,9,9,9,0,.001f,1);assert(s.valid==before);
 }
 FrictionCalibration bad={.rpm=40,.active=1};
 for(unsigned n=0;n<5000;++n)
   Fcal_Observe(&bad,40,0,0,.5f,.5f,0,0,.001f,1);
 Fcal_Finish(&bad,1);assert(!bad.passed && bad.valid==0);
 FrictionCalibration accel={.rpm=240,.active=1};
 for(unsigned n=0;n<3000;++n)
   Fcal_Observe(&accel,240,240,200,.4f,.4f,0,n,.001f,1);
 assert(!accel.valid);Fcal_Finish(&accel,1);assert(!accel.passed);
 FrictionCalibration fault={.rpm=40,.active=1,.valid=3000,.valid_s=3,.net_travel=20};
 Fcal_Finish(&fault,0);assert(!fault.passed);
 return 0;
}'''
        p=subprocess.run([GCC,'-x','c','-','-std=c11','-O2','-Wall','-Wextra','-Werror',
            '-I',str(ROOT/'firmware_common'),'-o',str(out)],input=source,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertEqual(subprocess.run([str(out)]).returncode,0)

    @staticmethod
    def stats(rpm):
        iq=.01+(.08 if rpm>0 else -.08)+.0002*rpm
        return dict(passed=1,valid_s=3.,valid=3000,reject=0,rpm=rpm,iq_sum=iq*3,
            iq_ref_sum=iq*3,id_sum=0.,abs_id_sum=.01*3,speed_sum=rpm*3,
            speed_error_sum=0.,iq_sq_sum=iq*iq*3,net_travel=rpm*18,abs_travel=abs(rpm*18))

    def test_fit_repeated_grid(self):
        result=report.report([self.stats(r) for _ in range(3) for r in report.POINTS])
        self.assertTrue(result['complete_repeated_grid'])
        for key,value in [('bias_a',.01),('coulomb_a',.08),('viscous_a_per_rpm',.0002)]:
            self.assertAlmostEqual(result['fit'][key],value,places=6)
        self.assertFalse(result['automatic_parameter_write'])

    def test_high_grid_fit_uses_measured_speed_and_correct_grid(self):
        grid=(200,240,260,280,-200,-240,-260,-280)
        data=[]
        for _ in range(3):
            for rpm in grid:
                s=self.stats(rpm);measured=.98*rpm
                iq=.01+(.08 if rpm>0 else -.08)+.0002*measured
                s.update(speed_sum=measured*3,iq_sum=iq*3,iq_ref_sum=iq*3,iq_sq_sum=iq*iq*3)
                data.append(s)
        result=report.report(data,grid)
        self.assertTrue(result['complete_repeated_grid'])
        self.assertAlmostEqual(result['fit']['viscous_a_per_rpm'],.0002,places=7)

    def test_exploratory_fit_never_promotes_failed_points_or_changes_input(self):
        grid=(200,240,260,280,-200,-240,-260,-280)
        data=[self.stats(r) for r in grid]
        for s in data:s['passed']=0
        before=json.dumps(data,sort_keys=True)
        self.assertIsNone(report.report(data,grid)['fit'])
        sensitivity=report.admitted_window_sensitivity(data,grid)
        self.assertIsNotNone(sensitivity['fit'])
        self.assertFalse(sensitivity['calibration_accepted'])
        self.assertEqual(len(sensitivity['original_failed_points_included']),8)
        self.assertEqual(json.dumps(data,sort_keys=True),before)

    def test_missing_negative_and_bad_current_are_not_fitted(self):
        self.assertIsNone(report.report([self.stats(40)])['fit'])
        stats=[self.stats(r) for r in report.POINTS]
        stats[-1]['abs_id_sum']=3.
        self.assertEqual(report.report(stats)['fit']['clean_point_count'],7)
        self.assertIn('ID_NOT_SMALL',report.report(stats)['points'][-1]['quality_flags'])
        stats[-1]['passed']=0
        self.assertEqual(len(report.report(stats)['invalid_points']),1)

    def test_default_is_files_only(self):
        result=subprocess.run([sys.executable,str(ROOT/'tools/friction_calibration_report.py')],
            text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        plan=json.loads(result.stdout)
        self.assertEqual(plan['iq_limit_a_unchanged'],.5)
        self.assertEqual(plan['board_lease_seconds_unchanged'],12)
        self.assertFalse(plan['automatic_current_increase'])

    def test_no_enable_writes_or_protection_changes_in_adapter(self):
        source=(ROOT/'firmware_common/friction_calibration_binding.inc').read_text()
        for forbidden in ('BDTR |=','CCER=','NVIC_SetPriority','FOC_EncoderSpeedUpdate(',
                          'ClSession_Start','cl_session.used=','ClearFault'):
            self.assertNotIn(forbidden,source)
        self.assertIn('LatestOriginal_Admit()',source)
        self.assertIn('ProtectedLoop_Stop()',source)
        self.assertIn('speed_friction_enabled',source)

    def test_actual_preprocessed_control_and_protection_frozen(self):
        old=expanded('a','Tightening240rpmFrictionOnCandidate')
        new=expanded('a','FrictionCalibrationDiagnostic')
        for name in FROZEN+('MotorControl_SetSpeed','MotorControl_SetIdle',
            'FocFeedbackSafety_Push','FocFp_PushRawSafety','FocCurrentValidation_Push',
            'SpeedPiAntiWindup_Apply','SpeedBumpless_Apply','ProtectedLoop_Ready'):
            a=function(old,name);b=function(new,name)
            if name=='FOC_EncoderSpeedUpdate':b=b.replace('FrictionCalibration_Observe(dt_meas);','')
            self.assertEqual(re.sub(r'\s+','',a),re.sub(r'\s+','',b),name)


if __name__=='__main__':unittest.main()
