"""Real C first-failure latch, unchanged admission, binding order and decoder."""
import json
import struct
import subprocess
import sys
import unittest
from test_torque_chain import GCC,ROOT,FROZEN,function
from test_torque350_five_second import expanded
sys.path.insert(0,str(ROOT/'tools'))
import motor_ident_timing_report as report


class TimingTests(unittest.TestCase):
    def compile_run(self,source,name):
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/(name+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(exe)],
                input=source,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_first_failure_bits_boundaries_no_overwrite_and_wrap(self):
        self.compile_run(r'''
#include <assert.h>
#include <stddef.h>
#define FOC_IDENT_CURRENT_REJECT_ENABLE 1
#define FOC_IDENT_TIMING_TRACE_ENABLE 1
#define MID_TRAVEL_EXIT_ENABLE 0
#include "motor_identification.h"
int main(void){float d,q;
 assert(sizeof(MotorIdentification)==1724 && offsetof(MotorIdentification,timing_failure)==1660);
 for(unsigned ds=1;ds<=3;++ds)for(unsigned dt=44;dt<=56;++dt){
  MotorIdentification s={.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f,.used=1};
  assert(MotorIdent_Reference(&s,100,10,0,0,.05f,0,&d,&q));
  unsigned bits=(ds!=1?1:0)|(dt<45?2:0)|(dt>55?4:0);
  unsigned ok=MotorIdent_Reference(&s,100+dt,10+ds,0,0,.05f,0,&d,&q);
  assert(ok==!bits);
  if(bits){MotorIdentTimingFailure t=s.timing_failure;
   assert(s.reason==MID_TIMING && t.valid && t.flags==bits);
   assert(t.prev_seq==10 && t.prev_us==100 && t.seq==10+ds && t.us==100+dt);
   assert(t.delta_seq==ds && t.delta_us==dt && !t.context_valid);
   assert(s.last_seq==10 && s.last_us==100 && d==0 && q==0);
   MotorIdent_TimingLatch(&s,999,999,7);assert(!memcmp(&t,&s.timing_failure,sizeof t));
   assert(MotorIdent_Reference(&s,999,999,0,0,.05f,0,&d,&q));
   assert(!memcmp(&t,&s.timing_failure,sizeof t));
  }else assert(!s.timing_failure.valid);
 }
 MotorIdentification s={.mode=MID_RS,.status=MID_ACTIVE,.start_us=0xffffff00U,
   .last_us=0xfffffff0U,.last_seq=0xffffffffU,.current_a=.05f};
 assert(MotorIdent_Reference(&s,34,0,0,0,.05f,0,&d,&q));assert(!s.timing_failure.valid);
 assert(!MotorIdent_Reference(&s,90,1,0,0,.05f,0,&d,&q));
 assert(s.timing_failure.delta_us==56 && s.timing_failure.flags==4);
 return 0;}
''','motor-ident-timing')

    def test_actual_binding_before_stop_context_and_read_only_uart(self):
        text=(ROOT/'tests/test_motor_identification.py').read_text()
        start=text.index("code=r'''",text.index('def test_real_binding_'))+len("code=r'''")
        code=text[start:text.index("'''",start)]
        code='#define FOC_IDENT_TIMING_TRACE_ENABLE 1\n#define __DMB() ((void)0)\n'+code
        code=code.replace('struct {unsigned source_us;} cl_frame;',
            'struct {unsigned source_us,source_seq;} cl_frame;\n'
            'static unsigned injected_seq_count,cl_last_us,current_hold_total,cl_current_path;')
        code=code.replace('encoder_speed_rpm=3;cl_seq=2;cl_frame.source_us=100;',r'''
 MotorIdent_Command("MOTOR TEST IDENT TIMING",out,sizeof out);assert(strstr(out,"ERR"));
 cl_seq=3;cl_frame.source_us=150;cl_frame.source_seq=3;
 injected_seq_count=3;cl_last_us=150;current_hold_total=1;cl_current_path=1;
''')
        code=code.replace('assert(motor_ident.used && !critical);',r'''
 assert(motor_ident.used && !critical);
 assert(motor_ident.reason==MID_TIMING && motor_ident.timing_failure.valid);
 assert(motor_ident.timing_failure.prev_seq==1 && motor_ident.timing_failure.seq==3);
 assert(motor_ident.timing_failure.flags==5 && motor_ident.timing_failure.context_valid);
 assert(motor_ident.timing_failure.hold_before==0 && motor_ident.timing_failure.hold_now==1);
 MotorIdent_Command("MOTOR TEST IDENT TIMING",out,sizeof out);
 assert(strstr(out,"TV=1") && strstr(out,"DS=2 DT=100 WHY=5"));
 MotorIdent_Command("MOTOR TEST IDENT TIMING CONTEXT",out,sizeof out);
 assert(strstr(out,"CV=1 ADC=3 FRAME=3 PAIR_US=150 HB=0 HN=1 PATH=1"));
''')
        self.compile_run(code,'motor-ident-timing-binding')

    def test_decoder_preserves_evidence_distinguishes_hold_and_dt(self):
        raw=bytearray(1724)
        def pack(ds,dt,flags,holds=0):
            struct.pack_into('<15I',raw,1660,10,100,10+ds,100+dt,ds,dt,flags,1,
                             10+ds,10+ds,100+dt,7,7+holds,1,1)
        pack(1,68,4)
        self.assertEqual(report.decode(raw)['classification'],'SOFTWARE_TIMESTAMP_INTERVAL')
        pack(2,100,5,1)
        self.assertEqual(report.decode(raw)['classification'],'ACCEPTED_SEQUENCE_GAP_WITH_DISCRIMINATOR_HOLD')
        pack(1,50,0)
        with self.assertRaises(ValueError):report.decode(raw)
        with self.assertRaises(ValueError):report.decode(bytes(1660))
        self.assertIn('NO_CONTINUITY_SNAPSHOT',report.decode(bytes(1724))['classification'])

    def test_frozen_controller_and_default_off(self):
        import re
        a=expanded('a','MotorParameterIdentificationNoTravelDiagnostic')
        b=expanded('a','MotorParameterIdentificationTimingDiagnostic')
        for name in set(FROZEN+('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_Stop',
                              'ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage')):
            self.assertEqual(re.sub(r'\s+','',function(a,name)),re.sub(r'\s+','',function(b,name)),name)
        cmd=json.loads((ROOT/'foc2_app_a/build/MotorParameterIdentificationTimingDiagnostic/compile_commands.json').read_text())
        self.assertIn('-DFOC_IDENT_TIMING_TRACE_ENABLE=1',cmd[0]['command'])
        self.assertNotIn('FOC_IDENT_TIMING_TRACE_ENABLE',a)


if __name__=='__main__':unittest.main()
