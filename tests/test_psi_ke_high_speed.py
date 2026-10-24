"""High-speed plan/compiler/mocked batch verification. Never access a board."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_torque_chain import ROOT, GCC, function
from test_torque350_five_second import expanded
sys.path.insert(0,str(ROOT/'tools'))
import psi_ke_report as report
import psi_ke_board as low
import psi_ke_high_speed_board as high


class PsiHighSpeedTests(unittest.TestCase):
    def test_plan_only_requested_300_400_and_protection_unchanged(self):
        p=report.plan(400,500,(300,400))
        self.assertEqual(p['runnable'],[300,400]);self.assertEqual(p['skipped'],[])
        self.assertEqual(p['overspeed_trip_rpm'],500)
        self.assertFalse(p['auto_retry']);self.assertFalse(p['auto_apply'])
        self.assertEqual(report.plan()['runnable'],[100,200])
        with self.assertRaises(ValueError):report.plan(400,500,(400,400))

    def test_real_preprocessed_only_command_limit_changes(self):
        old=expanded('a','PsiKe500rpmTripDiagnostic')
        new=expanded('a','PsiKeHighSpeedDiagnostic')
        self.assertIn('CL_OVERSPEED_RPM=500U',new)
        for name in ('MotorControl_SetSpeed','FOC_EncoderSpeedUpdate'):
            self.assertEqual(function(old,name),function(new,name).replace('400.0f','250.0f'),name)
        for name in ('FOC_CurrentLoopStep','FOC_ResetController','ProtectedLoop_PwmEntry',
                     'ProtectedLoop_SetDuty','ProtectedLoop_GuardIrqBody','ProtectedLoop_AdcIrq',
                     'PowerStage_Enable','PowerStage_Disable','Encoder_ElectricalAngleRad','TighteningTask'):
            self.assertEqual(function(old,name),function(new,name),name)
        self.assertEqual(function(old,'PsiIdent_Command'),function(new,'PsiIdent_Command').replace('400.0f','250.0f'))
        self.assertNotIn('FOC_PSI_IDENT_API400',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())

    def test_real_allowed_function_300_400_no_higher_or_trip_equality(self):
        code='''#include <assert.h>
#include "psi_ke_identification.h"
int main(void) {
 assert(PsiIdent_Allowed(300,400,500));
 assert(PsiIdent_Allowed(400,400,500));
 assert(!PsiIdent_Allowed(500,400,500));
 assert(!PsiIdent_Allowed(400,400,400));
 assert(!PsiIdent_Allowed(400,250,500));
 assert(!PsiIdent_Allowed(300,400,300));
 return 0;
}'''
        exe=ROOT/'tmp/psi-high-admission.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror',
            '-I',str(ROOT/'firmware_common'),'-x','c','-',str(ROOT/'firmware_common/psi_ke_identification.c'),
            '-o',str(exe)],input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertEqual(subprocess.run([str(exe)]).returncode,0)

    def test_exact_two_point_batch_quality_failure_continues_guard_stops(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as d:
            capture=Path(d)/'fake.bin';capture.write_bytes(b'no-device')
            calls=[]
            def point(child,name,source,before,data,rpm,first):
                calls.append((rpm,first))
                child.update(result=dict(target_rpm=rpm,passed=False),pass_=True,
                    final_capture=str(capture),final_outputs_off=True,final_cpu_halted=True)
            with patch.multiple(low,API_LIMIT=400,TRIP_LIMIT=500,POINTS=(300,400)), \
                 patch.object(low.base,'staged',return_value=(capture,b'fake')), \
                 patch.object(low.base.old.prior,'checkpoint'), \
                 patch.object(low.base.old.zero,'latest_meta',return_value=(0,0,1,0,0)), \
                 patch.object(low,'run_point',side_effect=point):
                row=dict(powered_no_alarm=True)
                low.execute(row,'synthetic',Path('unused'),b'fake')
                self.assertEqual(calls,[(300,True),(400,False)])
                self.assertTrue(row['acquisition_complete'])
            with patch.multiple(low,API_LIMIT=400,TRIP_LIMIT=500,POINTS=(300,400)), \
                 patch.object(low.base,'staged',return_value=(capture,b'fake')), \
                 patch.object(low.base.old.prior,'checkpoint'), \
                 patch.object(low,'run_point',side_effect=RuntimeError('protection')) as run:
                with self.assertRaisesRegex(RuntimeError,'protection'):
                    low.execute(dict(powered_no_alarm=True),'synthetic',Path('unused'),b'fake')
                self.assertEqual(run.call_count,1)

    def test_pinned_high_files_default_only_and_no_hardware_without_confirmation(self):
        self.assertEqual(high.image(),high.IMAGE.read_bytes())
        p=subprocess.run([sys.executable,str(ROOT/'tools/psi_ke_high_speed_board.py')],
            text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('OFFLINE PASS: no devices',p.stdout)
        plan=json.loads(p.stdout.split('OFFLINE PASS:',1)[0])
        self.assertEqual(plan['runnable'],[300,400])
        p=subprocess.run([sys.executable,str(ROOT/'tools/psi_ke_high_speed_board.py'),
            '--execute-batch','missing.json'],text=True,capture_output=True)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('Fresh whole-batch supervised ON',p.stderr)


if __name__=='__main__':unittest.main()
