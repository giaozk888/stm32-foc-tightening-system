"""Remove only identification displacement STOP; keep every other exit."""
import hashlib
import json
import math
import subprocess
import sys
import unittest
from test_torque_chain import GCC,ROOT,FROZEN,function
from test_torque350_five_second import expanded
sys.path.insert(0,str(ROOT/'tools'))
import motor_identification_report as analysis
import test_motor_identification as fixtures


class NoTravelTests(unittest.TestCase):
    def test_compiled_travel_toggle_speed_voltage_current_timing_and_duration(self):
        source=r'''
#include <assert.h>
#define FOC_IDENT_CURRENT_REJECT_ENABLE 1
#include "motor_identification.h"
int main(void){float d=0,q=0;
 MotorIdentification s={.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f,.used=1};
 int ok=MotorIdent_Reference(&s,50,1,.11f,0,.05f,0,&d,&q);
 assert(ok==!MID_TRAVEL_EXIT_ENABLE);
#if !MID_TRAVEL_EXIT_ENABLE
 assert(s.status==MID_ACTIVE && d==.05f && q==0);
 assert(MotorIdent_Reference(&s,100,2,10,0,.05f,0,&d,&q));
#endif
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 assert(!MotorIdent_Reference(&s,50,1,0,2.01f,.05f,0,&d,&q));assert(s.reason==MID_MOTION);
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 assert(!MotorIdent_Record(&s,(MotorIdentFrame){.vd=.201f}));assert(s.reason==MID_VOLTAGE);
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 for(unsigned k=1;k<=3;++k){
  ok=MotorIdent_Reference(&s,k*50,k,0,0,.21f,0,&d,&q);assert(ok==(k<3));
 }
 assert(s.reason==MID_CURRENT && s.current_reject_count==3);
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 assert(MotorIdent_Reference(&s,50,1,0,0,.05f,0,&d,&q));
 assert(!MotorIdent_Reference(&s,150,3,0,0,.05f,0,&d,&q));assert(s.reason==MID_TIMING);
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 assert(!MotorIdent_Reference(&s,400000,8000,0,0,.05f,0,&d,&q));assert(s.status==MID_DONE);
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 assert(!MotorIdent_Reference(&s,50,1,NAN,0,.05f,0,&d,&q));assert(s.reason==MID_BAD_DATA);
 return 0;}
'''
        for enable in (0,1):
            for opt in ('-Os','-O2'):
                exe=ROOT/'tmp'/('motor-ident-no-travel-'+str(enable)+opt+'.exe')
                p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                    '-DMID_TRAVEL_EXIT_ENABLE='+str(enable),'-I',str(ROOT/'firmware_common'),
                    '-x','c','-','-o',str(exe)],input=source,capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                subprocess.run([str(exe)],check=True,capture_output=True)

    def test_no_other_control_change_and_offline_stationary_quality_remains(self):
        a=expanded('a','MotorParameterIdentificationRejectDiagnostic')
        b=expanded('a','MotorParameterIdentificationNoTravelDiagnostic')
        import re
        for name in set(FROZEN+('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_Stop')):
            self.assertEqual(re.sub(r'\s+','',function(a,name)),re.sub(r'\s+','',function(b,name)),name)
        run=fixtures.rs_run(.05);run['rows'][-1]['angle']+=math.radians(2)
        with self.assertRaises(analysis.Insufficient):analysis.guard(run)
        commands=json.loads((ROOT/'foc2_app_a/build/MotorParameterIdentificationNoTravelDiagnostic/compile_commands.json').read_text())
        main=next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
        self.assertIn('-DMID_TRAVEL_EXIT_ENABLE=0',main)
        self.assertIn('-DFOC_IDENT_CURRENT_REJECT_ENABLE=1',main)
        for path,sha in (
          ('foc2_app_a/build/MotorParameterIdentificationRejectDiagnostic/foc2.bin',
           '04cc4387e53614432c0671f6e7106763e5040789cbd6d8c6b6259606d6c41a6d'),
          ('foc2_app_b/build/FrictionBUnchanged/foc2.bin',
           '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)


if __name__=='__main__':unittest.main()
