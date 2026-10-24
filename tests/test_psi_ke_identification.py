import copy
import hashlib
import json
import math
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_torque_chain import ROOT,GCC,function
from test_torque350_five_second import expanded
sys.path.insert(0,str(ROOT/'tools'))
import psi_ke_report as report
import psi_ke_board as board


class PsiTests(unittest.TestCase):
    def test_real_c_model_stability_fixed_window_quality_and_fault(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/('tmp/psi-host'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/psi_ke_identification_host.c'),
                str(ROOT/'firmware_common/psi_ke_identification.c'),'-o',str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    @staticmethod
    def data(rpm,passed=True,psi=.0004,offset=.015):
        we=rpm*10*math.pi/30
        return dict(target_rpm=rpm,passed=passed,rs_ohm=.78,ld_h=20.03e-6,pole_pairs=10,
            mean_we_rad_s=we,mean_bemf_v=we*psi+offset)

    def test_multispeed_fit_offset_definition_and_no_activation(self):
        rows=[self.data(r) for r in (100,200,240)]
        before=copy.deepcopy(rows);r=report.fit(rows);c=r['candidate']
        self.assertAlmostEqual(c['psi_f_wb'],.0004,places=12)
        self.assertAlmostEqual(c['offset_v'],.015,places=12)
        self.assertAlmostEqual(c['ke_phase_peak_v_per_mech_rad_s'],.004,places=12)
        self.assertAlmostEqual(c['r_squared'],1,places=12)
        self.assertEqual(c['residual_dof'],1)
        self.assertFalse(r['automatic_feedforward_apply']);self.assertFalse(r['qualified_physical_flux'])
        self.assertEqual(rows,before)

    def test_two_points_r2_not_promoted_failed_point_not_used_or_filled(self):
        rows=[self.data(100),self.data(200),self.data(300,False,psi=9)]
        r=report.fit(rows)
        self.assertEqual(r['candidate']['residual_dof'],0)
        self.assertIn('ZERO_RESIDUAL_DOF',r['fit_warning'])
        self.assertEqual(r['valid_points'],2);self.assertEqual(len(r['points']),3)
        self.assertIsNone(report.fit([self.data(100)])['candidate'])
        rows[2]['fault']=True;self.assertIsNone(report.fit(rows)['candidate'])

    def test_parameter_mixture_degenerate_and_nonfinite_rejected(self):
        rows=[self.data(100),self.data(200)];rows[1]['rs_ohm']=.1
        with self.assertRaises(ValueError):report.fit(rows)
        rows=[self.data(100),self.data(200)];rows[1]['mean_we_rad_s']=float('nan')
        with self.assertRaises(ValueError):report.fit(rows)
        rows=[self.data(100),self.data(200)];rows[1]['mean_we_rad_s']=rows[0]['mean_we_rad_s']
        with self.assertRaises(ValueError):report.fit(rows)

    def test_allowed_batch_no_raise_limits(self):
        p=report.plan();self.assertEqual(p['runnable'],[100,200]);self.assertEqual(p['repeats'],1)
        self.assertEqual([r['rpm'] for r in p['skipped']],[300,400])
        self.assertFalse(p['auto_retry']);self.assertFalse(p['auto_apply'])

    def test_trace_joins_same_index_not_nearby_or_stale_parts(self):
        rows=[dict(decoded=f'PSI {part} index={index} value=1')
              for index in (1,2) for part in 'RIES']
        self.assertTrue(report.trace_coverage(rows,2,2)['complete'])
        r=report.trace_coverage(rows[:-1],2,2)
        self.assertFalse(r['complete']);self.assertEqual(r['missing_or_partial_indices'],[2])
        rows.append(dict(decoded='PSI E index=1 value=2'))
        with self.assertRaises(ValueError):report.trace_coverage(rows,2,2)

    def test_actual_foc_speed_and_safety_owners_unchanged(self):
        old=expanded('a','BemfFeedforwardCandidate');new=expanded('a','PsiKeIdentificationDiagnostic')
        for name in ('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','FOC_ResetController',
                     'ProtectedLoop_PwmEntry','ProtectedLoop_SetDuty','ProtectedLoop_GuardIrqBody',
                     'ProtectedLoop_AdcIrq','Encoder_ElectricalAngleRad','MotorControl_SetSpeed',
                     'PowerStage_Enable','PowerStage_Disable'):
            self.assertEqual(function(old,name),function(new,name),name)
        self.assertNotIn('PsiIdent_',function(new,'FOC_CurrentLoopStep'))
        self.assertIn('PSI_USE_EXPLICIT_COMMAND',function(new,'TighteningTask'))
        self.assertNotIn('FOC_PSI_IDENT_DIAG',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        self.assertEqual(hashlib.sha256((ROOT/'foc2_app_b/build/FrictionBUnchanged/foc2.bin').read_bytes()).hexdigest(),
            '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')

    def test_actual_idle_point_admission_and_local_dispatch(self):
        src=(ROOT/'firmware_common/psi_ke_identification_binding.inc').read_text()
        for guard in ('!psi_ident.used','!cl_session.used','!bemf_enabled','TIM1->CCER','TIM_BDTR_MOE',
                      '!tightening_start_request','!tightening_stop_request'):
            self.assertIn(guard,src)
        self.assertLess(src.index('PsiIdent_Allowed'),src.index('psi_ident=(PsiIdentification)'))
        self.assertNotIn('BSRR',src);self.assertNotIn('TIM1->CCR',src)
        self.assertIn('RESULT_NOT_FINISHED',src)
        self.assertIn('Protocol_SendError(req,PROTO_ERR_BUSY',src)

    def test_compiled_real_command_gate_one_shot_and_skip_without_motion(self):
        source=(ROOT/'firmware_common/psi_ke_identification_binding.inc').read_text()
        scale=(ROOT/'firmware_common/foc_bemf_feedforward_binding.inc').read_text()
        code=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include "psi_ke_identification.h"
#define CURRENT_PI_CANDIDATE_RS_OHM .78f
#define CURRENT_PI_CANDIDATE_LD_H .00002003f
#define POLE_PAIRS 10U
#define MOTOR_SPEED_API_LIMIT_RPM 250.f
#define CL_OVERSPEED_RPM 300U
#define CL_READY 1
#define MOTOR_MODE_IDLE 0
#define TIM_BDTR_MOE 0x8000U
#define TIM_BDTR_AOE 0x4000U
#define DRIVER_SD_Pin 64U
static unsigned critical,busy,ready=1,bemf_enabled,motor_control_mode,tightening_start_request,tightening_stop_request;
static struct {unsigned state,used;} cl_session={.state=CL_READY};
static struct {unsigned ODR;} gpio;
static struct {unsigned BDTR,CCER;} tim;
#define DRIVER_SD_GPIO_Port (&gpio)
#define TIM1 (&tim)
#define taskENTER_CRITICAL() (++critical)
#define taskEXIT_CRITICAL() (--critical)
static PsiIdentification psi_ident;
static unsigned ProtectedLoop_Ready(void){return ready;}
static unsigned Tightening_IsBusy(void){return busy;}
'''+ 'static int32_t '+function(scale,'BemfWire_Scaled')+'\nstatic uint8_t '+function(source,'PsiIdent_Command')+r'''
int main(void) {
 char out[384];
 assert(PsiIdent_Command("MOTOR TEST PSI RUN 300",out,sizeof out));
 assert(strstr(out,"SKIPPED") && !psi_ident.used && !critical);
 assert(PsiIdent_Command("MOTOR TEST PSI RUN 400",out,sizeof out));
 assert(strstr(out,"SKIPPED") && !psi_ident.used);
 unsigned *blockers[]={&busy,&bemf_enabled,&motor_control_mode,&tightening_start_request,
  &tightening_stop_request,&gpio.ODR,&tim.BDTR,&tim.CCER,&cl_session.used};
 for(unsigned n=0;n<sizeof blockers/sizeof blockers[0];n++) {
  *blockers[n]=n==5?DRIVER_SD_Pin:n==6?TIM_BDTR_MOE:1;
  assert(PsiIdent_Command("MOTOR TEST PSI RUN 100",out,sizeof out));
  assert(strstr(out,"NOT_READY") && !psi_ident.used && !critical);
  *blockers[n]=0;
 }
 ready=0;PsiIdent_Command("MOTOR TEST PSI RUN 100",out,sizeof out);assert(!psi_ident.used);ready=1;
 assert(PsiIdent_Command("MOTOR TEST PSI RUN 100",out,sizeof out));
 assert(strstr(out,"QUEUED RPM=100") && psi_ident.used && psi_ident.queued && !critical);
 assert(!tim.BDTR && !tim.CCER && !gpio.ODR);
 PsiIdent_Command("MOTOR TEST PSI RUN 200",out,sizeof out);assert(strstr(out,"NOT_READY"));
 PsiIdent_Command("MOTOR TEST PSI RESULT",out,sizeof out);assert(strstr(out,"NOT_FINISHED"));
 PsiIdent_Command("MOTOR TEST PSI PLAN",out,sizeof out);
 assert(strstr(out,"RS_UOHM=780000") && strstr(out,"LD_NH=20030") && strstr(out,"BEMF_AUTO_APPLY=0"));
 return 0;
}
'''
        exe=ROOT/'tmp/psi-command-host.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror',
            '-I',str(ROOT/'firmware_common'),'-x','c','-',str(ROOT/'firmware_common/psi_ke_identification.c'),
            '-o',str(exe)],input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_files_default_and_no_physical_flags_no_hardware(self):
        with patch.object(board,'configure') as cfg:
            with self.assertRaises(SystemExit):board.main(['--stage-off'])
            cfg.assert_not_called()
            with self.assertRaises(SystemExit):board.main(['--execute-batch','missing.json'])
            cfg.assert_not_called()
        with patch.object(board,'configure',return_value=b'fake'),patch.object(board.base,'stage') as stage,\
             patch.object(board.base.hw,'debug') as debug:
            self.assertEqual(board.main([]),0);stage.assert_not_called();debug.assert_not_called()

    def test_batch_exact_allowed_points_and_fault_stops_without_retry(self):
        p={};data=b'a'
        with patch.object(board.base,'staged',return_value=(Path('unused'),data)),\
             patch.object(board.base.old.prior,'checkpoint'),patch.object(board,'run_point',side_effect=RuntimeError('guard')) as run:
            with self.assertRaisesRegex(RuntimeError,'guard'):board.execute(dict(powered_no_alarm=True),'test',Path('x'),data)
            self.assertEqual(run.call_count,1)
        with patch.object(board.base,'staged') as staged:
            with self.assertRaises(ValueError):board.execute(p,'test',Path('x'),data)
            staged.assert_not_called()

    def test_batch_success_exactly_100_200_quality_failure_retained(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            capture=Path(directory)/'synthetic-flash.bin';capture.write_bytes(b'unit-test-no-device')
            parent=dict(powered_no_alarm=True)
            calls=[]
            def run(child,name,source,before,data,rpm,first):
                calls.append((rpm,first))
                child.update(result=self.data(rpm,passed=(rpm==100)),pass_=True,
                    final_capture=str(capture),final_outputs_off=True,final_cpu_halted=True)
            with patch.object(board.base,'staged',return_value=(capture,b'unit-test-no-device')),\
                 patch.object(board.base.old.prior,'checkpoint'),patch.object(board,'run_point',side_effect=run),\
                 patch.object(board.base.old.zero,'latest_meta',return_value=(0,0,1,0,0)):
                board.execute(parent,'test',Path('unused'),b'a')
            self.assertEqual(calls,[(100,True),(200,False)])
            self.assertTrue(parent['acquisition_complete']);self.assertEqual(len(parent['results']),2)
            self.assertFalse(parent['results'][1]['passed']);self.assertIsNone(parent['analysis']['candidate'])

    def test_pinned_files_configure_and_new_log_formats_not_in_flash(self):
        self.assertEqual(board.image(),board.IMAGE.read_bytes())
        board.configure(board.ROOT_RESTORE) # Files-only preservation chain, NO devices.
        data=board.IMAGE.read_bytes();elf=board.ELF.read_bytes()
        for tag in (b'PSI R index=',b'PSI I index=',b'PSI E index=',b'PSI S index='):
            self.assertNotIn(tag,data);self.assertIn(tag,elf)

    def test_real_compressed_log_codec_no_truncation_coherent_index(self):
        import test_pw_log_tokenized_default
        from pw_tokenizer import detokenize,tokens
        pw=ROOT/'third_party/pigweed'
        inc=[ROOT/'firmware_common',ROOT/'firmware_common/pw_log_tokenized_override',
            pw/'pw_log_tokenized/public_overrides',pw/'pw_assert/print_and_abort_assert_public_overrides',
            pw/'pw_assert/print_and_abort_check_public_overrides',
            pw/'third_party/fuchsia/repo/sdk/lib/stdcompat/include']
        inc += [pw/m/'public' for m in ('pw_log','pw_log_tokenized','pw_log_string','pw_tokenizer',
            'pw_preprocessor','pw_polyfill','pw_span','pw_bytes','pw_status','pw_result','pw_assert',
            'pw_varint','pw_numeric','pw_containers','pw_toolchain')]
        exe=ROOT/'tmp/psi-log-codec.exe'
        cmd=[str(Path(GCC).with_name('g++.exe')),'-std=c++17','-Os','-Wall','-Wextra','-Werror',
            '-UNDEBUG','-DPW_LOG_TOKENIZED_ENCODING_BUFFER_SIZE_BYTES=32']
        for i in inc:cmd+=['-I',str(i)]
        cmd += [str(ROOT/'tests/psi_ke_log_host.cc'),str(pw/'pw_log_tokenized/log_tokenized.cc'),
            str(pw/'pw_tokenizer/encode_args.cc'),str(pw/'pw_varint/varint.cc'),'-o',str(exe)]
        p=subprocess.run(cmd,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],text=True,capture_output=True,check=True)
        formats=re.findall(r'PW_LOG_INFO\("([^"\n]+)"',
            (ROOT/'firmware_common/psi_ke_identification_log.cc').read_text())
        decoder=detokenize.Detokenizer(tokens.Database([
            tokens.TokenizedStringEntry(tokens.pw_tokenizer_65599_hash(f),f) for f in formats]))
        lines=p.stdout.splitlines();self.assertEqual(len(lines),4)
        for line,field in zip(lines,('rpm=200.00000','iq=0.1600000','psi=0.000400000','fault=4294967295')):
            size,data=line.split();self.assertLessEqual(int(size),32)
            result=decoder.detokenize(bytes.fromhex(data));self.assertTrue(result.ok(),str(result))
            self.assertIn('index=4294967295',str(result));self.assertIn(field,str(result))


if __name__=='__main__':unittest.main()
