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
import startup_timestamps_report as report


class StartupTimestampTests(unittest.TestCase):
    def test_real_c_independent_events_noise_and_32bit_wrap(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/('tmp/startup-times'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/startup_timestamps_host.c'),
                str(ROOT/'firmware_common/startup_timestamps.c'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_valid_zero_missing_events_and_wrapped_relative_times(self):
        s=dict(valid=1,t0_us=0,t_iq_us=0,t_motion_us=0,t_speed_us=0,t_stable_us=0,
            motion_begin_us=0,iq_at_event_a=0.,motion_direction=0,speed_at_event_rpm=0.)
        r=report.timings(s)
        self.assertEqual(r['absolute_us']['t0_us'],0)
        self.assertIsNone(r['absolute_us']['t_iq_us'])
        s.update(valid=31,t0_us=0xfffffff0,t_iq_us=16,t_motion_us=32,t_speed_us=48,t_stable_us=64)
        r=report.timings(s)
        self.assertEqual(r['relative_to_t0']['t_iq_delay_us'],32)
        self.assertEqual(r['relative_to_t0']['t_stable_delay_us'],80)

    def test_new_build_is_passive_task_only_and_control_owners_unchanged(self):
        old=expanded('a','AccelFfAuditGain025');new=expanded('a','StartupTimestampsDiagnostic')
        for name in ('FOC_CurrentLoopStep','FOC_ResetController','MotorControl_SetSpeed',
            'Encoder_ElectricalAngleRad','ProtectedLoop_PwmEntry','ProtectedLoop_SetDuty',
            'ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody','PowerStage_Enable','PowerStage_Disable',
            'TighteningTask','SpeedPiAntiWindup_Apply','SpeedBumpless_Apply'):
            self.assertEqual(function(old,name),function(new,name),name)
        before=function(old,'FOC_EncoderSpeedUpdate');after=function(new,'FOC_EncoderSpeedUpdate')
        after=re.sub(r'StartupTimes_Begin\([\s\S]*?\);','',after)
        after=re.sub(r'if \(mode==MOTOR_MODE_SPEED\)\s*StartupTimes_Observe\([\s\S]*?\);','',after)
        after=after.replace('uint8_t startup_was_moving=speed_friction_stats.moving;','')
        after=re.sub(r'if \(!startup_was_moving && speed_friction_stats.moving\)\s*StartupTimes_Stable\([\s\S]*?\);','',after)
        self.assertEqual(re.sub(r'\s+','',before),re.sub(r'\s+','',after))
        self.assertEqual(function(new,'FOC_EncoderSpeedUpdate').count('SpeedScurve_Step('),1)
        source=function(new,'FOC_EncoderSpeedUpdate')
        self.assertLess(source.index('StartupTimes_Begin('),source.index('SpeedScurve_Step('))
        self.assertLess(source.index('foc_iq_ref_A = iq_cmd;'),source.index('StartupTimes_Observe('))
        self.assertLess(source.index('SpeedFriction_Observe('),source.index('StartupTimes_Stable('))
        for obj in ('speed_scurve.c.obj','speed_friction_compensation.c.obj','speed_accel_feedforward.c.obj'):
            self.assertEqual(next((ROOT/'foc2_app_a/build/AccelFfAuditGain025').rglob(obj)).read_bytes(),
                next((ROOT/'foc2_app_a/build/StartupTimestampsDiagnostic').rglob(obj)).read_bytes())

    def test_default_off_and_existing_board_image_unchanged(self):
        self.assertRegex((ROOT/'foc2_app_a/CMakeLists.txt').read_text(),r'option\(FOC_STARTUP_TIMESTAMPS_DIAG [^\n]+ OFF\)')
        self.assertNotIn('FOC_STARTUP_TIMESTAMPS_DIAG',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        checks={
            'foc2_app_a/build/AccelFfAuditGain100/foc2.bin':'0f34df867e0f13ba9e544a89253400936efb4616d33bd2a2027da7731363f6b1',
            'foc2_app_a/build/BemfFittedFluxCandidate/foc2.bin':'6e66984d9867de2f25b362c14b6549eec2043406905f031bdf12c1594cbaad3f',
            'foc2_app_b/build/FrictionBUnchanged/foc2.bin':'7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366'}
        for path,digest in checks.items():self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest)

    def test_compressed_codec_same_seq_and_no_truncation(self):
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
        exe=ROOT/'tmp/startup-times-codec.exe'
        cmd=[str(Path(GCC).with_name('g++.exe')),'-std=c++17','-Os','-Wall','-Wextra','-Werror',
            '-UNDEBUG','-DPW_LOG_TOKENIZED_ENCODING_BUFFER_SIZE_BYTES=32']
        for i in inc:cmd+=['-I',str(i)]
        cmd += [str(ROOT/'tests/startup_timestamps_log_host.cc'),str(pw/'pw_log_tokenized/log_tokenized.cc'),
            str(pw/'pw_tokenizer/encode_args.cc'),str(pw/'pw_varint/varint.cc'),'-o',str(exe)]
        p=subprocess.run(cmd,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],text=True,capture_output=True,check=True)
        formats=re.findall(r'PW_LOG_INFO\("([^"\n]+)"',(ROOT/'firmware_common/startup_timestamps_log.cc').read_text())
        decoder=detokenize.Detokenizer(tokens.Database([
            tokens.TokenizedStringEntry(tokens.pw_tokenizer_65599_hash(f),f) for f in formats]))
        self.assertEqual(len(p.stdout.splitlines()),4)
        for line in p.stdout.splitlines():
            size,data=line.split();self.assertLessEqual(int(size),32)
            out=decoder.detokenize(bytes.fromhex(data));self.assertTrue(out.ok(),str(out))
            self.assertIn('seq=4294967295',str(out))


if __name__=='__main__':unittest.main()
