"""A-only Coulomb compensation, frozen AF1/FOC and real token evidence."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from test_speed_pi_anti_windup import ROOT,GCC,braced
from test_torque_chain import FROZEN,function
from test_torque350_five_second import expanded
sys.path.insert(0,str(ROOT/'tools'))
import friction_compare
BASE='Tightening240rpmAccelFfOnCandidate'
ON='Tightening240rpmFrictionOnCandidate'
OFF='Tightening240rpmFrictionOffCandidate'

class FrictionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=expanded('a',BASE);cls.after=expanded('a',ON)
        cls.out=ROOT/'tests/speed_friction_build';cls.out.mkdir(exist_ok=True)

    def compile_run(self,source,name):
        for opt in ('-Os','-O2'):
            exe=self.out/(name+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',str(ROOT/'firmware_common'),'-x','c','-',
                str(ROOT/'firmware_common/speed_friction_compensation.c'),
                str(ROOT/'firmware_common/speed_accel_feedforward.c'),'-o',str(exe)],
                input=source,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_signed_deadband_limits_off_equivalence_aw_and_direction_stats(self):
        self.compile_run((ROOT/'tests/speed_friction_compensation_host.c').read_text(),'math')

    def test_real_speed_output_owner_off_and_position_unchanged(self):
        code='''#include <assert.h>
#include <math.h>
#include "speed_friction_compensation.h"
#include "speed_scurve.h"
#define MOTOR_MODE_SPEED 2
static float ClampFloat(float v,float lo,float hi){return v<lo?lo:v>hi?hi:v;}
'''
        for label,source in (('old',self.before),('new',self.after)):
            outer=function(source,'FOC_EncoderSpeedUpdate')
            start=re.search(r'i_candidate\s*=\s*ClampFloat\(i_candidate',outer).start()
            end=outer.index('foc_iq_ref_A = iq_cmd;',start)+len('foc_iq_ref_A = iq_cmd;')
            code+='''static void run_'''+label+'''(int mode,unsigned on,float prev,float candidate,float p,
float speed,float accel,float *out_i,float *out_current) {
float speed_integrator_A=prev,sb2_previous_A=prev,i_candidate=candidate,p_term=p;
float speed_iq_limit_A=.5f,iq_unsat=0,iq_cmd=0,foc_iq_ref_A=0,speed_err=1,speed_ref_rpm=speed;
unsigned speed_integrator_bleed_active=0,speed_overspeed_bleed_active=0;
SpeedScurve speed_scurve={0};speed_scurve.acceleration_rpm_s=accel;
unsigned speed_accel_ff_enabled=1,speed_friction_enabled=on;
SpeedAccelFfResult aff;SpeedFrictionResult friction;
(void)friction;(void)speed_friction_enabled;(void)speed_ref_rpm;
'''+outer[start:end]+'''
*out_i=speed_integrator_A;*out_current=foc_iq_ref_A;
}
'''
        code+='''int main(void){float ai,bi,ac,bc;
for(int sign=-1;sign<=1;sign+=2){float s=(float)sign;
run_old(2,0,s*.04f,s*.15f,s*.2f,s*240,s*200,&ai,&ac);
run_new(2,0,s*.04f,s*.15f,s*.2f,s*240,s*200,&bi,&bc);
assert(ai==bi && ac==bc);
run_new(2,1,s*.04f,s*.15f,s*.2f,s*240,s*200,&bi,&bc);
assert(fabsf(bi-s*.0625f)<1e-6f && fabsf(bc-s*.5f)<1e-6f);
run_old(1,0,s*.04f,s*.15f,s*.2f,s*240,s*200,&ai,&ac);
run_new(1,1,s*.04f,s*.15f,s*.2f,s*240,s*200,&bi,&bc);
assert(ai==bi && ac==bc);}
return 0;}'''
        self.compile_run(code,'owner')

    def test_frozen_foc_pipeline_pi_scurve_ff_safety_irq_and_b(self):
        for name in FROZEN+('TighteningTask','SpeedPiAntiWindup_Apply','SpeedBumpless_Apply',
            'MotorControl_SetSpeed','MotorControl_SetIq',
            'MotorControl_SetIdle','Encoder_ElectricalAngleRad','FocFeedbackSafety_Push',
            'FocOcConfirm_Push','FocFp_PushRawSafety','ProtectedLoop_Ready','PowerStage_Disable'):
            old=function(self.before,name);new=function(self.after,name)
            if name=='FOC_EncoderSpeedUpdate':
                new=new.replace('SpeedFrictionResult friction;','')
                start=new.index('friction=SpeedFriction_Apply(')
                end=new.index('aff=friction.speed;',start)+len('aff=friction.speed;')
                original=re.search(r'aff=SpeedAccelFf_Apply\([\s\S]*?speed_accel_ff_enabled\);',old)[0]
                new=new[:start]+original+new[end:]
                start=new.index('speed_friction_frame=(SpeedFrictionFrame)')
                end=new.index('SpeedFriction_Observe(',start)
                end=new.index(';',end)+1
                new=new[:start]+new[end:]
                self.assertLess(function(self.after,name).index('foc_iq_ref_A = iq_cmd;'),
                    function(self.after,name).index('SpeedFriction_Observe('))
            self.assertEqual(re.sub(r'\s+','',old),re.sub(r'\s+','',new),name)
        for obj in ('foc_adc_timing_stm32.c.obj','stm32g4xx_it.c.obj','speed_scurve.c.obj','speed_accel_feedforward.c.obj'):
            files=[next((ROOT/f'foc2_app_a/build/{p}').rglob(obj)).read_bytes() for p in (BASE,ON)]
            self.assertEqual(*files,obj)
        for path,sha in (
            ('foc2_app_a/build/Tightening240rpmAccelFfOnCandidate/foc2.bin','9a7a0c9d57d8017dea55c31687c3ee2a69dac0d969dbac33a07b70eec0cb2642'),
            ('foc2_app_a/build/Tightening240rpmAccelFfOnCandidate/foc2.elf','726e57051efdadec67f1cfdf4dbdb99d61e9c743d2fd3927f7c994c9a9890ae9'),
            ('foc2_app_b/build/FrictionBUnchanged/foc2.bin','7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)

    def test_configuration_and_no_new_main_warnings(self):
        warnings=[]
        for preset in (BASE,ON,OFF):
            base=ROOT/f'foc2_app_a/build/{preset}'
            cmd=next(c['command'] for c in json.loads((base/'compile_commands.json').read_text())
                if c['file'].endswith('/Core/Src/main.c'))
            if preset!=BASE:
                self.assertIn('-DSPEED_FRICTION_I_A=0.20f',cmd)
                self.assertIn('-DSPEED_FRICTION_DEADBAND_RPM=2.0f',cmd)
                self.assertIn('-DFOC_FRICTION_ENABLED_DEFAULT='+('1' if preset==ON else '0'),cmd)
                self.assertIn('firmware_common/pw_log_tokenized_override',cmd)
                image=(base/'foc2.bin').read_bytes()
                self.assertIn(b'SPEED_CTRL=FR1',image);self.assertNotIn(b'FRC C seq=',image)
            p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),cwd=base,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            warnings.append(set(re.findall(r'warning: (.*)',p.stderr)))
        self.assertFalse(warnings[1]-warnings[0]);self.assertFalse(warnings[2]-warnings[0])

    def test_idle_toggle_reset_consistency_monitor_only_and_missing_direction(self):
        code='''#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "speed_friction_compensation.h"
#include "speed_scurve.h"
#define FOC_SPEED_FRICTION_CANDIDATE 1
static unsigned critical,logs,busy,tightening_start_request,tightening_stop_request;
#define taskENTER_CRITICAL() (++critical)
#define taskEXIT_CRITICAL() (--critical)
#define MOTOR_MODE_IDLE 0
#define TIM_BDTR_MOE (1U<<15)
#define TIM_BDTR_AOE (1U<<14)
#define DRIVER_SD_Pin (1U<<6)
static struct {unsigned ODR;} gpio;
static struct {unsigned BDTR,CCER;} tim;
#define DRIVER_SD_GPIO_Port (&gpio)
#define TIM1 (&tim)
static unsigned motor_control_mode;
static unsigned char speed_accel_ff_enabled=1,speed_friction_enabled;
static SpeedAccelFfStats speed_accel_ff_stats;
static SpeedAccelFfFrame speed_accel_ff_frame;
static SpeedFrictionStats speed_friction_stats;
static SpeedFrictionFrame speed_friction_frame;
static void SpeedFriction_Reset(void);
static void SpeedFriction_Monitor(void);
static unsigned Tightening_IsBusy(void){return busy;}
void SpeedFriction_Log(const SpeedFrictionFrame *f){assert(!critical && f->control.valid);++logs;}
static int checked_format(char *out,size_t n,const char *format,...) {
 assert(!critical);va_list a;va_start(a,format);int r=vsnprintf(out,n,format,a);va_end(a);return r;
}
#define snprintf checked_format
#include "speed_accel_feedforward_binding.inc"
#include "speed_friction_compensation_binding.inc"
int main(void){char out[192];SpeedAccelFf_Reset();
 assert(SpeedFriction_Command("MOTOR TEST FRIC ON",out,sizeof out));
 assert(speed_friction_enabled && speed_accel_ff_enabled && strstr(out,"I_UA=200000") && strstr(out,"DB_MRPM=2000"));
 speed_friction_frame.control.valid=1;speed_friction_frame.control.seq=1;
 SpeedAccelFf_Monitor();SpeedAccelFf_Monitor();assert(logs==1);
 for(unsigned reason=0;reason<8;++reason){
 busy=reason==0;motor_control_mode=reason==1?2:0;gpio.ODR=reason==2?DRIVER_SD_Pin:0;
 tim.BDTR=reason==3?TIM_BDTR_MOE:reason==4?TIM_BDTR_AOE:0;tim.CCER=reason==5;
 tightening_start_request=reason==6;tightening_stop_request=reason==7;
 SpeedFriction_Command("MOTOR TEST FRIC OFF",out,sizeof out);
 assert(strstr(out,"ERR FRC") && speed_friction_enabled && speed_accel_ff_enabled);}
 busy=0;motor_control_mode=0;gpio.ODR=0;tim.BDTR=tim.CCER=0;
 tightening_start_request=tightening_stop_request=0;
 SpeedFriction_Command("MOTOR TEST FRIC OFF",out,sizeof out);
 assert(!speed_friction_enabled && speed_accel_ff_enabled && !speed_friction_frame.control.valid);
 SpeedFriction_Command("MOTOR TEST FRIC METRICS NEG",out,sizeof out);
 assert(strstr(out,"N=0") && strstr(out,"START_MS=-1") && strstr(out,"LOW_MAE_MRPM=-1"));
 SpeedFriction_Command("MOTOR TEST FRIC METRICS2 POS",out,sizeof out);assert(strstr(out,"PI_PEAK_MA=0"));
 SpeedFriction_Command("MOTOR TEST FRIC BOGUS",out,sizeof out);assert(strstr(out,"ERR FRC COMMAND"));
 assert(!SpeedFriction_Command("STATUS",out,sizeof out));
 assert(SpeedAccelFf_Command("MOTOR TEST FF STATUS",out,sizeof out));
 assert(!critical && speed_accel_ff_enabled);return 0;
}'''
        self.compile_run(code,'binding')

    def test_real_32_byte_token_roundtrip_all_three_rows_and_elf(self):
        import test_pw_log_tokenized_default
        from pw_tokenizer import detokenize,tokens,encode
        import struct
        pw=ROOT/'third_party/pigweed'
        includes=[ROOT/'firmware_common',ROOT/'firmware_common/pw_log_tokenized_override',
            pw/'pw_log_tokenized/public_overrides',pw/'pw_assert/print_and_abort_assert_public_overrides',
            pw/'pw_assert/print_and_abort_check_public_overrides',
            pw/'third_party/fuchsia/repo/sdk/lib/stdcompat/include']
        includes += [pw/m/'public' for m in ('pw_log','pw_log_tokenized','pw_log_string','pw_tokenizer',
            'pw_preprocessor','pw_polyfill','pw_span','pw_bytes','pw_status','pw_result','pw_assert',
            'pw_varint','pw_numeric','pw_containers','pw_toolchain')]
        exe=self.out/'log.exe'
        cmd=[str(Path(GCC).with_name('g++.exe')),'-std=c++17','-Os','-Wall','-Wextra','-Werror','-UNDEBUG',
             '-DPW_LOG_TOKENIZED_ENCODING_BUFFER_SIZE_BYTES=32']
        for inc in includes:cmd+=['-I',str(inc)]
        cmd += [str(ROOT/'tests/speed_friction_log_host.cc'),str(pw/'pw_log_tokenized/log_tokenized.cc'),
            str(pw/'pw_tokenizer/encode_args.cc'),str(pw/'pw_varint/varint.cc'),'-o',str(exe)]
        p=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],capture_output=True,text=True,check=True)
        formats=re.findall(r'PW_LOG_INFO\("([^"\n]+)"',
            (ROOT/'firmware_common/speed_friction_compensation_log.cc').read_text())
        decoder=detokenize.Detokenizer(tokens.Database([
            tokens.TokenizedStringEntry(tokens.pw_tokenizer_65599_hash(f),f) for f in formats]))
        rows=p.stdout.splitlines();self.assertEqual(len(rows),3)
        for row,expected in zip(rows,('speed_ref=-240.000','iq_fric=-0.200000','speed_integrator=-0.100000')):
            size,data=row.split();self.assertLessEqual(int(size),32)
            result=decoder.detokenize(bytes.fromhex(data));self.assertTrue(result.ok(),str(result))
            self.assertIn(expected,str(result));self.assertIn('seq=4294967295',str(result))
        # No string dictionary bytes are flashed; matching actual ARM ELF retains them.
        base=ROOT/f'foc2_app_a/build/{ON}'
        decoder=detokenize.Detokenizer(base/'foc2.elf')
        arguments=((4294967295,4294967295,1,1,-240.,-235.,-200.,-240.),
                   (4294967295,1,-.3,-.0375,-.2,-.5375,-.5),(4294967295,-.1,-.48))
        for fmt,args in zip(formats,arguments):
            entry=next(e for e in decoder.database.entries() if fmt in e.string)
            data=struct.pack('<I',entry.token)+encode.encode_args(*args)
            self.assertLessEqual(len(data),32)
            self.assertTrue(decoder.detokenize(data).ok())
            self.assertNotIn(fmt.encode(),(base/'foc2.bin').read_bytes())

    def test_bad_configurations_rejected(self):
        for label,flags in (('no_ff',['-DFOC_ACCEL_FEEDFORWARD_CANDIDATE=OFF']),
            ('ff_off',['-DFOC_ACCEL_FF_ENABLED_DEFAULT=OFF']),
            ('negative',['-DFOC_FRICTION_I_A=-0.2']),('over_limit',['-DFOC_FRICTION_I_A=0.6']),
            ('nan_deadband',['-DFOC_FRICTION_DEADBAND_RPM=nan'])):
            p=subprocess.run(['cmake','--preset',ON,'-B',str(ROOT/'tmp'/('friction-bad-'+label)),*flags],
                cwd=ROOT/'foc2_app_a',capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0,label)
            self.assertRegex(p.stdout+p.stderr,r'Friction comparison requires|nonnegative finite|cannot exceed')

    def test_comparison_missing_direction_signed_mean_and_conflicting_capture(self):
        def capture(on):
            return ('OK FRC ON=%d I_UA=200000 DB_MRPM=2000 FF_ON=1 KA_NA_PER_RPM_S=187500\n'%on+
                'OK FRC DIR=POS N=8000 START_MS=100 LOW_MAE_MRPM=3000 CRUISE_MAE_MRPM=1000\n'+
                'OK FRC DIR=POS I_PEAK_MA=100 PI_PEAK_MA=200 IQ_REF_PEAK_MA=400 IQ_MEAS_PEAK_MA=500 MEAN_MRPM=239000 WRONG_MS=0\n')
        a=capture(0);b=capture(1)
        self.assertEqual(friction_compare.compare(a,b)['directions']['POS']['start_delay_s']['on'],.1)
        self.assertIsNone(friction_compare.compare(a,b)['directions']['NEG'])
        both=lambda text:text+text[text.index('OK FRC DIR=POS'):].replace('POS','NEG').replace('239000','-238000')
        r=friction_compare.compare(both(a),both(b))
        self.assertEqual(r['directions']['NEG']['mean_signed_speed_rpm']['on'],-238)
        self.assertEqual(r['direction_asymmetry']['on']['speed_magnitude_difference_rpm'],1)
        with self.assertRaises(ValueError):friction_compare.compare(a+'OK FRC ON=1',b)
        with self.assertRaises(ValueError):friction_compare.compare(a,b.replace('I_UA=200000','I_UA=250000'))
        with self.assertRaises(ValueError):friction_compare.compare(a,b.replace('DIR=POS','DIR=NEG'))

if __name__=='__main__':unittest.main()
