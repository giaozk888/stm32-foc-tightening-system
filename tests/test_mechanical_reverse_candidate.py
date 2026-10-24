import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_torque_chain import GCC,function
from test_torque350_five_second import expanded
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import mechanical_reverse_batch as board
import mechanical_bidirectional_fit as paired
OLD='MechanicalReadinessSnapshotCandidate'
NEW='MechanicalReverseIdentificationCandidate'


class ReverseCandidateTests(unittest.TestCase):
    def test_native_signed_whitelist_and_existing_rundown_guard(self):
        code=r'''
#include <assert.h>
#include "friction_calibration.h"
#include "tightening_rundown_guard.h"
int main(void){
int32_t rpm=0;
const char *neg[]={"MOTOR TEST MECH RUN NEG 600","MOTOR TEST MECH RUN NEG 700","MOTOR TEST MECH RUN NEG 800"};
const char *pos[]={"MOTOR TEST MECH RUN POS 600","MOTOR TEST MECH RUN POS 700","MOTOR TEST MECH RUN POS 800"};
for(unsigned i=0;i<3;i++){
#ifdef FOC_MECHANICAL_REVERSE_IDENT_DIAG
 assert(Fcal_Parse(neg[i],&rpm) && rpm==-(int32_t)(600+i*100));assert(!Fcal_Parse(pos[i],&rpm));
#else
 assert(Fcal_Parse(pos[i],&rpm) && rpm==(int32_t)(600+i*100));assert(!Fcal_Parse(neg[i],&rpm));
#endif
}
const char *bad[]={"START","MOTOR TEST MECH RUN NEG 900","MOTOR TEST MECH RUN NEG 500",
 "MOTOR TEST MECH RUN NEG -600","MOTOR TEST MECH RUN NEG 600x","MOTOR TEST MECH RUN POS -600"};
for(unsigned i=0;i<sizeof bad/sizeof bad[0];i++)assert(!Fcal_Parse(bad[i],&rpm));
TightenRundownGuard g;TightenRundown_Begin(&g);
for(unsigned ms=10;ms<=120;ms+=10)
 assert(!TightenRundown_Update(&g,ms,-600,-400,-400,-(float)ms,-.2f,1));
assert(g.state==RUNDOWN_ARMED);
TightenRundown_Begin(&g);int failed=0;
for(unsigned ms=10;ms<=1600;ms+=10)failed|=TightenRundown_Update(&g,ms,-600,0,0,0,-.4f,1);
assert(failed && !TightenRundown_CanContact(&g));
TightenRundown_Begin(&g);
for(unsigned ms=10;ms<=120;ms+=10)
 TightenRundown_Update(&g,ms,-600,400,400,(float)ms,-.2f,1);
assert(g.state!=RUNDOWN_ARMED);return 0;}
'''
        for reverse in (False,True):
            for opt in ('-Os','-O2'):
                exe=ROOT/'tmp'/('reverse-whitelist-'+str(reverse)+opt+'.exe')
                args=[GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                    '-DFOC_MECHANICAL_HIGH_SPEED_DIAG=1','-DFOC_MECHANICAL_MOTION_DIAG=1']
                if reverse:args+=['-DFOC_MECHANICAL_REVERSE_IDENT_DIAG=1']
                args+=['-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(exe)]
                p=subprocess.run(args,input=code,text=True,capture_output=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                p=subprocess.run([str(exe)],text=True,capture_output=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_actual_compiled_control_protection_timing_and_task_frozen(self):
        old=expanded('a',OLD);new=expanded('a',NEW)
        for name in ('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_TaskService',
            'ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody','ProtectedLoop_HealthCaptured',
            'ProtectedLoop_TimerHealthy','ProtectedLoop_GatesMatch','ProtectedLoop_AdcReady',
            'ProtectedLoop_Ready','FaultDiag_CapturePacked','ProtectedLoop_PwmEntry',
            'ProtectedLoop_PwmStage','LatestOriginal_Admit','LatestOriginal_Ready',
            'PowerStage_Enable','PowerStage_Disable','MotorControl_SetIq','MotorControl_SetSpeed',
            'Encoder_ElectricalAngleRad','OuterObservation_Flush','TighteningTask'):
            self.assertEqual(function(old,name),function(new,name),name)
        a=function(old,'FrictionCalibration_Command');b=function(new,'FrictionCalibration_Command')
        start=b.index('if (!strcmp(cmd,"MOTOR TEST MECH DIRECTION"))');end=b.index('if (!strcmp(cmd,"MOTOR TEST MECH LIMITS"))',start)
        self.assertEqual(re.sub(r'\s+','',a),re.sub(r'\s+','',b[:start]+b[end:]))
        for basename in ('stm32g4xx_it.c.obj','foc_adc_timing_stm32.c.obj','as5047p_dma_stm32.c.obj',
            'foc_zero_robust.c.obj','tightening_intent_fsm.c.obj','speed_scurve.c.obj',
            'mechanical_identification.c.obj','speed_accel_feedforward.c.obj','speed_friction_compensation.c.obj'):
            self.assertEqual(next((ROOT/'foc2_app_a/build'/OLD).rglob(basename)).read_bytes(),
                next((ROOT/'foc2_app_a/build'/NEW).rglob(basename)).read_bytes(),basename)
        paired.matching_profiles(board.previous.ELF,board.ELF)

    def test_no_b_changes_or_warnings_added(self):
        for p,sha in ((ROOT/'foc2_app_a/build'/OLD/'foc2.bin',board.previous.SHA),
            (ROOT/'foc2_app_b/build/MechanicalReviewB/foc2.bin','7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),sha)
        self.assertNotIn('FOC_MECHANICAL_REVERSE_IDENT_DIAG',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        sets=[]
        for preset in (OLD,NEW):
            directory=ROOT/'foc2_app_a/build'/preset
            command=next(c['command'] for c in json.loads((directory/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
            p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',command),cwd=directory,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            sets.append(set(re.findall(r'warning: (.*)',p.stderr)))
        self.assertEqual(*sets)

    def test_files_only_default_exact_new_image_and_actual_preserved_b(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/mechanical_reverse_batch.py')],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('9 mechanical points; no devices',p.stdout)
        board.image()
        r=json.loads(board.ROOT_RESTORE.read_text())
        self.assertTrue(r['pass_']);self.assertTrue(r['b_application_not_run'])
        self.assertEqual(r['image_sha256'],board.previous.SHA)

    def test_fresh_physical_gates_before_setup_and_fixed_negative_plan(self):
        low=board.low
        with patch.multiple(low,setup=low.setup,POINTS=low.POINTS,TRIP_RPM=low.TRIP_RPM,
            TRAVEL_DEG=low.TRAVEL_DEG,CLOSURE_SECONDS=low.CLOSURE_SECONDS,
            LIMITS_QUERY=low.LIMITS_QUERY,LIMITS_EXTRA=low.LIMITS_EXTRA),\
             patch.object(board,'ORIGINAL_SETUP') as setup:
            for args in (['--prepare-off'],['--execute-nine','missing'],['--restore-b-drive-off','missing']):
                with self.assertRaises(SystemExit):board.main(args)
            setup.assert_not_called()
            with patch.object(low,'main',return_value=0):board.main([])
            self.assertEqual(low.POINTS,(-600,)*3+(-700,)*3+(-800,)*3)
            self.assertEqual(low.TRIP_RPM,1000);self.assertEqual(low.TRAVEL_DEG,30000)

    def test_direction_identity_required_before_any_negative_run(self):
        def new():
            b=object.__new__(board.ReverseBoard);b.record={};return b
        run='MOTOR TEST MECH RUN NEG 600'
        with patch.object(board.ORIGINAL_BOARD,'command',side_effect=[
            '1 OK MECH REVERSE_IDENT=1 SIGN=-1 GRID_RPM=600,700,800 DOB_CONTROL=0','2 OK MECH QUEUED RPM=-600']) as send:
            self.assertIn('QUEUED',new().command(run))
            self.assertEqual([x.args[0] for x in send.call_args_list],['MOTOR TEST MECH DIRECTION',run])
        with patch.object(board.ORIGINAL_BOARD,'command',return_value='1 OK MECH SIGN=1') as send:
            with self.assertRaisesRegex(RuntimeError,'no motion'):new().command(run)
            self.assertEqual(send.call_count,1)
        with patch.object(board.ORIGINAL_BOARD,'command') as send:
            with self.assertRaises(ValueError):new().command('MOTOR TEST MECH RUN POS 600')
            send.assert_not_called()


if __name__=='__main__':unittest.main()
