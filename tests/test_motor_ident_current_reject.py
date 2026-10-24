"""Bounded diagnostic sample rejection; immutable original controller/firmware."""
import hashlib
import json
import subprocess
import sys
import unittest
from test_torque_chain import GCC,ROOT,FROZEN,function
from test_torque350_five_second import expanded
sys.path.insert(0,str(ROOT/'tools'))
import motor_identification_report as report
import test_motor_identification as old


class RejectDiagnosticTests(unittest.TestCase):
    def test_c_isolated_reject_recovery_budgets_timeout_and_voltage(self):
        source=r'''
#include <assert.h>
#define FOC_IDENT_CURRENT_REJECT_ENABLE 1
#include "motor_identification.h"
int main(void){
 float d=0,q=0;
 MotorIdentification s={.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f,.used=1};
 assert(MotorIdent_Reference(&s,200000,1,0,0,.21f,0,&d,&q));
 assert(s.sample_rejected && s.current_reject_count==1 && s.current_reject_run==1);
 assert(d==.05f && q==0);
 assert(MotorIdent_Record(&s,(MotorIdentFrame){.us=200000,.id=.21f,.vd=.01f}));
 assert(!s.count);
 assert(MotorIdent_Reference(&s,200050,2,0,0,.05f,0,&d,&q));
 assert(!s.sample_rejected && s.current_reject_run==0 && s.current_good_count==1);
 assert(MotorIdent_Record(&s,(MotorIdentFrame){.us=200050,.id=.05f,.vd=.005f}));
 assert(s.count==1 && s.rows[0].id==.05f);
 for(unsigned k=0;k<3;++k){
  unsigned ok=MotorIdent_Reference(&s,200100+50*k,3+k,0,0,0,-.21f,&d,&q);
  assert(ok==(k<2));
 }
 assert(s.status==MID_ABORT && s.reason==MID_CURRENT && s.max_current_reject_run==3);
 assert(s.used && d==0 && q==0);
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 for(unsigned k=0;k<33;++k){
  unsigned ok=MotorIdent_Reference(&s,50*(k+1),k+1,0,0,k%2?.05f:.21f,0,&d,&q);
  assert(ok==(k<32));
 }
 assert(s.current_reject_count==17 && s.max_current_reject_run==1 && s.status==MID_ABORT);
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 assert(MotorIdent_Reference(&s,50,1,0,0,.21f,0,&d,&q));
 assert(!MotorIdent_Record(&s,(MotorIdentFrame){.vd=.201f,.id=.21f}));
 assert(s.reason==MID_VOLTAGE); /* Reject must NOT bypass voltage exit. */
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 assert(MotorIdent_Reference(&s,50,1,0,0,.21f,0,&d,&q));
 assert(!MotorIdent_Reference(&s,400000,2,0,0,.05f,0,&d,&q));
 assert(s.status==MID_DONE); /* No lease extension to replace rejected data. */
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 assert(!MotorIdent_Reference(&s,50,1,0,3,.21f,0,&d,&q));
 assert(s.reason==MID_MOTION);return 0;
}'''
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('motor-ident-reject'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(exe)],
                input=source,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            subprocess.run([str(exe)],check=True,capture_output=True)

    def test_actual_binding_first_reject_before_stop_raw_saved_once(self):
        # Reuse the actual existing binding fixture, inserting the opt-in and
        # isolated/continuous current frames before its original motion abort.
        text=(ROOT/'tests/test_motor_identification.py').read_text()
        start=text.index("code=r'''",text.index('def test_real_binding_'))+len("code=r'''")
        source=text[start:text.index("'''",start)]
        source='#define FOC_IDENT_CURRENT_REJECT_ENABLE 1\n#define __DMB() ((void)0)\n'+source
        source=source.replace('struct {unsigned source_us;} cl_frame;',
            'struct {unsigned source_us; unsigned short u,v;} cl_frame;')
        anchor='encoder_speed_rpm=3;cl_seq=2;cl_frame.source_us=100;'
        source=source.replace(anchor,r'''
 cl_seq=2;cl_frame.source_us=100;cl_frame.u=1700;cl_frame.v=1500;
 foc_id_ref_A=.05f;foc_iq_ref_A=0;
 assert(MotorIdent_Ref(.25f,-.01f));
 assert(motor_ident.first_reject_valid && motor_ident.first_raw_u==1700);
 assert(motor_ident.first_reject.seq==2 && motor_ident.first_reject.id==.25f);
 assert(motor_ident.first_reject.id_ref==.05f && !stops);
 cl_seq=3;cl_frame.source_us=150;assert(MotorIdent_Ref(.05f,0));
 cl_seq=4;cl_frame.source_us=200;cl_frame.u=1800;assert(MotorIdent_Ref(-.3f,0));
 assert(motor_ident.first_raw_u==1700 && motor_ident.first_reject.seq==2);
 encoder_speed_rpm=3;cl_seq=5;cl_frame.source_us=250;
''')
        exe=ROOT/'tmp/motor-ident-reject-binding.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror','-pedantic',
            '-UNDEBUG','-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(exe)],
            input=source,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        subprocess.run([str(exe)],check=True,capture_output=True)

    def test_accepted_estimates_do_not_include_reject_and_l_gaps_refused(self):
        run=old.rs_run(.05)
        run['current_admission']=dict(REJECT=1,GOOD=7997,MAX_RUN=1,REJECT_MAX=16,RUN_LIMIT=3)
        result=report.fit_rs([run,old.rs_run(.075),old.rs_run(.1)])
        self.assertAlmostEqual(result['rs_ohm'],.1)
        for bad in (dict(REJECT=17,MAX_RUN=1),dict(REJECT=3,MAX_RUN=3)):
            run['current_admission'].update(bad)
            with self.assertRaises(report.Insufficient):report.guard(run)
        run=old.l_run('LD');run['rows'][10]['seq']+=1
        with self.assertRaises(report.Insufficient):report.fit_l(run,.1)

    def test_control_pipeline_and_old_image_pins_preserved(self):
        before=expanded('a','MotorParameterIdentificationDiagnostic')
        after=expanded('a','MotorParameterIdentificationRejectDiagnostic')
        import re
        for name in set(FROZEN+('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_Stop')):
            self.assertEqual(re.sub(r'\s+','',function(before,name)),
                             re.sub(r'\s+','',function(after,name)),name)
        for path,sha in (
            ('foc2_app_a/build/MotorParameterIdentificationDiagnostic/foc2.bin',
             '15511c9bd4c3bb579773928bb70a2ffc5e08250b6ddf899bbfda6c10a3d81e4d'),
            ('foc2_app_a/build/Tightening240rpmFriction105OnCandidate/foc2.bin',
             '3adf71acf9579d455f9e0f27e27d121a863c570cde9f0baabb65b9f587ef2899'),
            ('foc2_app_b/build/FrictionBUnchanged/foc2.bin',
             '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)
        commands=json.loads((ROOT/'foc2_app_a/build/MotorParameterIdentificationRejectDiagnostic/compile_commands.json').read_text())
        self.assertIn('-DFOC_IDENT_CURRENT_REJECT_ENABLE=1',commands[0]['command'])


if __name__=='__main__':unittest.main()
