"""Read-only experiment identity, real C S-curve/FF/AW, candidate isolation."""
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from test_torque_chain import ROOT,GCC,function
from test_torque350_five_second import expanded
sys.path.insert(0,str(ROOT/'tools'))
import accel_ff_audit_report as report
PRESETS=('AccelFfAuditGain0','AccelFfAuditGain025','AccelFfAuditGain050','AccelFfAuditGain100')
VALUES=('0.0000000','0.000046875','0.00009375','0.0001875')


class AccelAuditTests(unittest.TestCase):
    def test_actual_c_direction_units_limits_sync_reset_and_passive_observer(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/('tmp/accel-audit-host'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/speed_accel_audit_host.c'),
                *[str(ROOT/'firmware_common'/f) for f in ('speed_accel_audit.c','speed_scurve.c',
                    'speed_accel_feedforward.c','speed_friction_compensation.c')],'-o',str(exe)],
                text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_history_identifies_wrong_feature_not_invented_accel_off_run(self):
        r=report.history(ROOT/'tmp/bemf-repeat-batch-1792643207376578900.json')
        self.assertEqual(r['feature_actually_switched'],'BEMF_VOLTAGE_FF')
        self.assertFalse(r['acceleration_on_off_comparison']);self.assertTrue(r['all_accel_ff_on'])
        self.assertEqual({x['ka_na_per_rpm_s'] for x in r['runs']},{187500})
        self.assertEqual(r['observed_log_max_abs_accel_rpm_s'],200)
        self.assertAlmostEqual(r['observed_log_max_abs_acc_ff_a'],.0375)
        self.assertTrue(all(x['iq_saturation_ms']==0 for x in r['runs']))

    def test_actual_owner_and_frozen_control_math_all_four_builds(self):
        old=expanded('a','BemfFittedFluxCandidate')
        for preset,value in zip(PRESETS,VALUES):
            new=expanded('a',preset).replace(value+'f','0.0001875f')
            new=new.replace('speed_accel_audit_ka','0.0001875f')
            for name in ('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','FOC_ResetController',
                'SpeedPiAntiWindup_Apply','SpeedBumpless_Apply','MotorControl_SetSpeed',
                'Encoder_ElectricalAngleRad','ProtectedLoop_PwmEntry','ProtectedLoop_SetDuty',
                'ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody','PowerStage_Enable',
                'PowerStage_Disable','TighteningTask','SpeedAccelFf_Reset'):
                before=function(old,name);after=function(new,name)
                after=after.replace('++speed_accel_audit.meta.trajectory_updates;','')
                after=after.replace('SpeedAccelAudit_Reset(&speed_accel_audit);','')
                after=re.sub(r'SpeedAccelAudit_Push\([\s\S]*?\);','',after)
                self.assertEqual(re.sub(r'\s+','',before),re.sub(r'\s+','',after),preset+':'+name)
            outer=function(new,'FOC_EncoderSpeedUpdate')
            self.assertEqual(outer.count('SpeedScurve_Step('),1)
            self.assertLess(outer.index('SpeedScurve_Step('),outer.index('SpeedFriction_Apply('))
            self.assertLess(outer.index('foc_iq_ref_A = iq_cmd;'),outer.index('SpeedAccelAudit_Push('))
            self.assertNotIn('SpeedAccelAudit_',function(new,'FOC_CurrentLoopStep'))
            for obj in ('speed_scurve.c.obj','speed_friction_compensation.c.obj','speed_accel_feedforward.c.obj'):
                before=next((ROOT/'foc2_app_a/build/BemfFittedFluxCandidate').rglob(obj)).read_bytes()
                after=next((ROOT/f'foc2_app_a/build/{preset}').rglob(obj)).read_bytes()
                self.assertEqual(before,after,preset+':'+obj)

    def test_default_bin_b_and_default_off_audit_unchanged(self):
        self.assertEqual(hashlib.sha256((ROOT/'foc2_app_a/build/BemfFittedFluxCandidate/foc2.bin').read_bytes()).hexdigest(),
            '6e66984d9867de2f25b362c14b6549eec2043406905f031bdf12c1594cbaad3f')
        self.assertEqual(hashlib.sha256((ROOT/'foc2_app_b/build/FrictionBUnchanged/foc2.bin').read_bytes()).hexdigest(),
            '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfE64861d1e98dd366'.lower())
        self.assertNotIn('FOC_ACCEL_FF_AUDIT',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        self.assertRegex((ROOT/'foc2_app_a/CMakeLists.txt').read_text(),r'option\(FOC_ACCEL_FF_AUDIT [^\n]+ OFF\)')
        for preset,value in zip(PRESETS,VALUES):
            cmd=next(c['command'] for c in json.loads((ROOT/f'foc2_app_a/build/{preset}/compile_commands.json').read_text())
                if c['file'].endswith('/Core/Src/main.c'))
            self.assertIn('-DSPEED_ACCEL_FF_KA_A_PER_RPM_S='+value+'f ',cmd)
            self.assertIn('-DFOC_BEMF_ENABLED_DEFAULT=0 ',cmd)
            self.assertIn('-DSPEED_FRICTION_I_A=0.105f ',cmd)
            self.assertIn('-DFOC_ACCEL_FF_AUDIT=1 ',cmd)

    @staticmethod
    def frame():
        return dict(seq=1,ms=0,trajectory_update=1,speed_ref=1.,speed_meas=0.,speed_error=1.,
            accel_ref=200.,iq_pi=.1,iq_acc_ff=.0375,iq_fric=.105,iq_raw=.2425,iq_cmd=.2425,
            integrator=.01,trajectory_phase=2,flags=1,dt_s=.001)

    def test_offline_checks_zero_direction_sum_clamp_sync_and_pi_counteraction(self):
        f=self.frame();self.assertEqual(report.checks([f],.0001875)['problems'],[])
        for field,value in (('iq_acc_ff',-.0375),('accel_ref',0),('iq_raw',.4),('iq_cmd',.8),('speed_error',-1)):
            bad=copy.deepcopy(f);bad[field]=value
            self.assertTrue(report.checks([bad],.0001875)['problems'],field)
        later=copy.deepcopy(f);later.update(seq=101,ms=100,trajectory_update=100)
        self.assertTrue(report.checks([f,later],.0001875)['problems'])
        f.update(iq_pi=-.1,iq_raw=.0425,iq_cmd=.0425)
        r=report.checks([f],.0001875)
        self.assertEqual(r['problems'],[]);self.assertEqual(r['pi_ff_opposed_frames'],1)
        self.assertFalse(r['opposed_is_automatic_fault'])

    def test_compare_rejects_bemf_confounded_or_nonzero_baseline(self):
        r=dict(bemf_runtime='1',meta=dict(max_abs_ff=0),checks=dict(problems=[]),frames=[])
        with self.assertRaises(ValueError):report.compare(r,r)
        r['bemf_runtime']='0';r['meta']['max_abs_ff']=.0375
        with self.assertRaises(ValueError):report.compare(r,r)

    def test_real_compressed_log_codec_same_seq_no_truncation(self):
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
        exe=ROOT/'tmp/accel-audit-log-codec.exe'
        cmd=[str(Path(GCC).with_name('g++.exe')),'-std=c++17','-Os','-Wall','-Wextra','-Werror',
            '-UNDEBUG','-DPW_LOG_TOKENIZED_ENCODING_BUFFER_SIZE_BYTES=32']
        for i in inc:cmd+=['-I',str(i)]
        cmd += [str(ROOT/'tests/speed_accel_audit_log_host.cc'),str(pw/'pw_log_tokenized/log_tokenized.cc'),
            str(pw/'pw_tokenizer/encode_args.cc'),str(pw/'pw_varint/varint.cc'),'-o',str(exe)]
        p=subprocess.run(cmd,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],text=True,capture_output=True,check=True)
        formats=re.findall(r'PW_LOG_INFO\("([^"\n]+)"',(ROOT/'firmware_common/speed_accel_audit_log.cc').read_text())
        decoder=detokenize.Detokenizer(tokens.Database([
            tokens.TokenizedStringEntry(tokens.pw_tokenizer_65599_hash(f),f) for f in formats]))
        self.assertEqual(len(p.stdout.splitlines()),4)
        for line in p.stdout.splitlines():
            size,data=line.split();self.assertLessEqual(int(size),32)
            out=decoder.detokenize(bytes.fromhex(data));self.assertTrue(out.ok(),str(out))
            self.assertIn('seq=4294967295',str(out))


if __name__=='__main__':unittest.main()
