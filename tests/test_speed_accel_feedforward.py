"""A-only FF math, real owner, ON/OFF guards, metrics and build isolation."""
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
import accel_ff_compare
BASE='Tightening240rpmScurveTokenizedCandidate'
ON='Tightening240rpmAccelFfOnCandidate'
OFF='Tightening240rpmAccelFfOffCandidate'

class AccelFfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=expanded('a',BASE); cls.after=expanded('a',ON)
        cls.out=ROOT/'tests/speed_accel_ff_build'; cls.out.mkdir(exist_ok=True)

    def compile_run(self,source,name):
        for opt in ('-Os','-O2'):
            exe=self.out/(name+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',str(ROOT/'firmware_common'),'-x','c','-',
                str(ROOT/'firmware_common/speed_accel_feedforward.c'),'-o',str(exe)],
                input=source,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_signed_combined_limit_unwind_off_grid_and_phase_stats(self):
        self.compile_run((ROOT/'tests/speed_accel_feedforward_host.c').read_text(),'math')

    def test_real_final_speed_owner_with_and_without_ff_position_unchanged(self):
        code='''#include <assert.h>
#include <math.h>
#include "speed_accel_feedforward.h"
#include "speed_scurve.h"
#define MOTOR_MODE_SPEED 2
static float ClampFloat(float v,float lo,float hi){return v<lo?lo:v>hi?hi:v;}
'''
        for label,source in (('old',self.before),('ff',self.after)):
            outer=function(source,'FOC_EncoderSpeedUpdate')
            start=re.search(r'i_candidate\s*=\s*ClampFloat\(i_candidate',outer).start()
            end=outer.index('foc_iq_ref_A = iq_cmd;',start)+len('foc_iq_ref_A = iq_cmd;')
            code+='''static void run_'''+label+'''(int mode,unsigned on,float prev,float candidate,float p,
float accel,float *out_i,float *out_current) {
  float speed_integrator_A=prev,sb2_previous_A=prev,i_candidate=candidate,p_term=p;
  float speed_iq_limit_A=.5f,iq_unsat=0,iq_cmd=0,foc_iq_ref_A=0,speed_err=1;
  unsigned speed_integrator_bleed_active=0,speed_overspeed_bleed_active=0;
  SpeedScurve speed_scurve={0}; speed_scurve.acceleration_rpm_s=accel;
  unsigned speed_accel_ff_enabled=on; SpeedAccelFfResult aff;
  (void)speed_scurve; (void)speed_accel_ff_enabled; (void)aff;
'''+outer[start:end]+'''
  *out_i=speed_integrator_A; *out_current=foc_iq_ref_A;
}
'''
        code+='''int main(void) {
  float ai,bi,ac,bc;
  for(int sign=-1;sign<=1;sign+=2) {
    float s=(float)sign;
    run_old(2,0,s*.24f,s*.29f,s*.2f,s*200,&ai,&ac);
    run_ff(2,0,s*.24f,s*.29f,s*.2f,s*200,&bi,&bc);
    assert(ai==bi && ac==bc);
    run_ff(2,1,s*.24f,s*.29f,s*.2f,s*200,&bi,&bc);
    assert(fabsf(bi-s*.2625f)<1e-6f && fabsf(bc-s*.5f)<1e-6f);
    run_old(1,0,s*.24f,s*.29f,s*.2f,s*200,&ai,&ac);
    run_ff(1,1,s*.24f,s*.29f,s*.2f,s*200,&bi,&bc);
    assert(ai==bi && ac==bc);
  }
  return 0;
}'''
        self.compile_run(code,'owner')

    def test_frozen_math_current_safety_pipeline_scurve_and_b(self):
        for name in FROZEN+('TighteningTask','SpeedPiAntiWindup_Apply','SpeedBumpless_Apply',
                'MotorControl_SetSpeed','MotorControl_SetIq','MotorControl_SetIdle',
                'Encoder_ElectricalAngleRad','FocFeedbackSafety_Push','FocOcConfirm_Push',
                'FocFp_PushRawSafety','ProtectedLoop_Ready','PowerStage_Disable','Protocol_PrintStatus'):
            old=function(self.before,name); new=function(self.after,name)
            if name=='FOC_EncoderSpeedUpdate':
                new=new.replace('SpeedAccelFfResult aff;','')
                new=re.sub(r'if \(mode==MOTOR_MODE_SPEED\) SpeedAccelFf_Reset\(\);','',new)
                start=new.index('aff=SpeedAccelFf_Apply(')
                end=new.index('iq_cmd=aff.iq_ref_a;',start)+len('iq_cmd=aff.iq_ref_a;')
                original=re.search(r'SpeedPiAntiWindupResult aw=SpeedPiAntiWindup_Apply\([\s\S]*?iq_cmd=aw.current_A;',old)[0]
                new=new[:start]+original+new[end:]
                start=re.search(r'if \(mode==MOTOR_MODE_SPEED\) \{\s*speed_accel_ff_frame=',new).start()
                _,end=braced(new,start); new=new[:start]+new[end:]
                self.assertLess(function(self.after,name).index('foc_iq_ref_A = iq_cmd;'),
                    function(self.after,name).index('SpeedAccelFf_Observe('))
            if name=='FOC_ResetController': new=new.replace('SpeedAccelFf_Reset();','')
            self.assertEqual(re.sub(r'\s+','',old),re.sub(r'\s+','',new),name)
        for obj in ('foc_adc_timing_stm32.c.obj','stm32g4xx_it.c.obj','speed_scurve.c.obj'):
            files=[next((ROOT/f'foc2_app_a/build/{p}').rglob(obj)).read_bytes() for p in (BASE,ON)]
            self.assertEqual(*files,obj)
        for path,sha in (
            ('foc2_app_a/build/Tightening240rpmScurveTokenizedCandidate/foc2.bin',
             '8ebb728b8b3a368fdd0b1a75daf2de72b792f0c0c407d376cbafc41920ef82f0'),
            ('foc2_app_b/build/AccelFfBUnchanged/foc2.bin',
             '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)

    def test_runtime_toggle_requires_idle_gates_off_and_monitor_only_logs(self):
        code='''#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "speed_accel_feedforward.h"
#include "speed_scurve.h"
static unsigned critical,logs,busy;
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
static unsigned tightening_start_request,tightening_stop_request;
static unsigned char speed_accel_ff_enabled;
static SpeedAccelFfStats speed_accel_ff_stats;
static SpeedAccelFfFrame speed_accel_ff_frame;
static unsigned Tightening_IsBusy(void){return busy;}
void SpeedAccelFf_Log(const SpeedAccelFfFrame *f){assert(!critical && f->valid);++logs;}
static int checked_format(char *out,size_t n,const char *format,...) {
  assert(!critical); va_list a;va_start(a,format);int r=vsnprintf(out,n,format,a);va_end(a);return r;
}
#define snprintf checked_format
#include "speed_accel_feedforward_binding.inc"
int main(void) {
  char out[192]; SpeedAccelFf_Reset();
  assert(SpeedAccelFf_Command("MOTOR TEST FF ON",out,sizeof out));
  assert(speed_accel_ff_enabled && strstr(out,"ON=1") && strstr(out,"FF_PEAK_UA=37500"));
  speed_accel_ff_frame.valid=1;speed_accel_ff_frame.seq=1;
  SpeedAccelFf_Monitor();SpeedAccelFf_Monitor(); assert(logs==1);
  for(unsigned reason=0;reason<8;++reason) {
    busy=reason==0; motor_control_mode=reason==1?2:0;
    gpio.ODR=reason==2?DRIVER_SD_Pin:0;
    tim.BDTR=reason==3?TIM_BDTR_MOE:reason==4?TIM_BDTR_AOE:0;tim.CCER=reason==5;
    tightening_start_request=reason==6;tightening_stop_request=reason==7;
    SpeedAccelFf_Command("MOTOR TEST FF OFF",out,sizeof out);
    assert(strstr(out,"ERR AFF") && speed_accel_ff_enabled);
  }
  busy=0;motor_control_mode=0;gpio.ODR=0;tim.BDTR=tim.CCER=0;
  tightening_start_request=tightening_stop_request=0;
  SpeedAccelFf_Command("MOTOR TEST FF OFF",out,sizeof out);
  assert(!speed_accel_ff_enabled && !speed_accel_ff_frame.valid && !speed_accel_ff_stats.samples);
  SpeedAccelFf_Command("MOTOR TEST FF METRICS",out,sizeof out); assert(strstr(out,"DEC_MAE_MRPM=-1"));
  SpeedAccelFf_Command("MOTOR TEST FF METRICS2",out,sizeof out); assert(strstr(out,"SETTLE_MS=-1"));
  assert(!SpeedAccelFf_Command("STATUS",out,sizeof out));
  assert(!critical); return 0;
}'''
        self.compile_run(code,'binding')

    def test_on_off_builds_keep_tokenization_and_config_guard(self):
        for preset,on in ((ON,1),(OFF,0)):
            base=ROOT/f'foc2_app_a/build/{preset}'
            cmd=next(c['command'] for c in json.loads((base/'compile_commands.json').read_text())
                if c['file'].endswith('/Core/Src/main.c'))
            self.assertIn('-DFOC_ACCEL_FF_ENABLED_DEFAULT='+str(on),cmd)
            self.assertIn('firmware_common/pw_log_tokenized_override',cmd)
            self.assertIn('-DSPEED_ACCEL_FF_KA_A_PER_RPM_S=0.0001875f',cmd)
            image=(base/'foc2.bin').read_bytes()
            self.assertIn(b'SPEED_CTRL=AF1',image)
            self.assertNotIn(b'AFF R seq=',image) # format must live only in ELF dictionary
            self.assertIn(b'AFF R seq=',(base/'foc2.elf').read_bytes())
            self.assertLessEqual(len(image),229376)
        for label,flags in (('no_token',['-DPW_LOG_TOKENIZED_DEFAULT=OFF']),
                            ('large_ka',['-DFOC_ACCEL_FF_KA_A_PER_RPM_S=0.0003'])):
            p=subprocess.run(['cmake','--preset',ON,'-B',str(ROOT/'tmp'/('aff-invalid-'+label)),*flags],
                cwd=ROOT/'foc2_app_a',capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0)
            self.assertRegex(p.stdout+p.stderr,r'Acceleration FF requires|caps Ka')

    def test_no_new_main_compiler_warnings(self):
        warnings=[]
        for preset in (BASE,ON,OFF):
            base=ROOT/f'foc2_app_a/build/{preset}'
            cmd=next(c['command'] for c in json.loads((base/'compile_commands.json').read_text())
                if c['file'].endswith('/Core/Src/main.c'))
            p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),cwd=base,
                capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            warnings.append(set(re.findall(r'warning: (.*)',p.stderr)))
        self.assertFalse(warnings[1]-warnings[0],warnings[1]-warnings[0])
        self.assertFalse(warnings[2]-warnings[0],warnings[2]-warnings[0])

    def test_saved_reply_comparison_missing_decel_is_null(self):
        def capture(on):
            return ('OK AFF ON=%d KA_NA_PER_RPM_S=187500\n'%on+
                'OK AFF N=8000 MAX_ERR_MRPM=20000 ACC_MAE_MRPM=10000 DEC_MAE_MRPM=-1 SEG=1\n'+
                'OK AFF OV_MRPM=3000 SETTLE_MS=-1 IQ_REF_PEAK_MA=400 IQ_MEAS_PEAK_MA=410 I_PEAK_MA=300 SAT_MS=100 SAT_RUN_MS=50\n')
        r=accel_ff_compare.compare(capture(0),capture(1))
        self.assertEqual(r['metrics']['max_speed_error_rpm']['ff_on'],20)
        self.assertIsNone(r['metrics']['deceleration_mae_rpm']['ff_on'])
        self.assertIsNone(r['metrics']['settling_time_s']['on_minus_off'])
        with self.assertRaises(ValueError): accel_ff_compare.compare(capture(1),capture(0))
        with self.assertRaises(ValueError): accel_ff_compare.compare('OK AFF ON=0',capture(1))
        with self.assertRaises(ValueError):
            accel_ff_compare.compare(capture(0)+'OK AFF N=9000',capture(1))
        with self.assertRaises(ValueError):
            accel_ff_compare.compare(capture(0)+'OK AFF ON=1',capture(1))

    def test_real_compressed_log_payload_fits_32_bytes_and_roundtrips(self):
        import test_pw_log_tokenized_default  # Registers the official tokenizer Python paths.
        from pw_tokenizer import detokenize,tokens,encode
        import struct
        pw=ROOT/'third_party/pigweed'
        includes=[ROOT/'firmware_common',ROOT/'firmware_common/pw_log_tokenized_override',
            pw/'pw_log_tokenized/public_overrides',
            pw/'pw_assert/print_and_abort_assert_public_overrides',
            pw/'pw_assert/print_and_abort_check_public_overrides',
            pw/'third_party/fuchsia/repo/sdk/lib/stdcompat/include']
        includes += [pw/m/'public' for m in ('pw_log','pw_log_tokenized','pw_log_string',
            'pw_tokenizer','pw_preprocessor','pw_polyfill','pw_span','pw_bytes','pw_status',
            'pw_result','pw_assert','pw_varint','pw_numeric','pw_containers','pw_toolchain')]
        exe=self.out/'log-codec.exe'
        cmd=[str(Path(GCC).with_name('g++.exe')),'-std=c++17','-Os','-Wall','-Wextra','-Werror',
             '-UNDEBUG','-DPW_LOG_TOKENIZED_ENCODING_BUFFER_SIZE_BYTES=32']
        for inc in includes: cmd += ['-I',str(inc)]
        cmd += [str(ROOT/'tests/speed_accel_feedforward_log_host.cc'),
            str(pw/'pw_log_tokenized/log_tokenized.cc'),str(pw/'pw_tokenizer/encode_args.cc'),
            str(pw/'pw_varint/varint.cc'),'-o',str(exe)]
        p=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],capture_output=True,text=True,check=True)
        formats=re.findall(r'PW_LOG_INFO\("([^"\n]+)"',
            (ROOT/'firmware_common/speed_accel_feedforward_log.cc').read_text())
        decoder=detokenize.Detokenizer(tokens.Database([
            tokens.TokenizedStringEntry(tokens.pw_tokenizer_65599_hash(f),f) for f in formats]))
        rows=p.stdout.splitlines(); self.assertEqual(len(rows),2)
        for row,expected in zip(rows,('accel_ref=-200.000','speed_integrator=-0.100000')):
            size,data=row.split(); self.assertLessEqual(int(size),32)
            result=decoder.detokenize(bytes.fromhex(data))
            self.assertTrue(result.ok(),str(result)); self.assertIn(expected,str(result))
            self.assertIn('seq=4294967295',str(result))
        # Match the deployed ARM dictionary as well, with real module/file metadata.
        decoder=detokenize.Detokenizer(ROOT/f'foc2_app_a/build/{ON}/foc2.elf')
        entry=next(e for e in decoder.database.entries() if formats[1] in e.string)
        data=struct.pack('<I',entry.token)+encode.encode_args(4294967295,1,-.25,-.0375,-.2875,-.2875,-.1)
        self.assertLessEqual(len(data),32)
        self.assertTrue(decoder.detokenize(data).ok())

if __name__=='__main__': unittest.main()
