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
import ka_identification_report as fit


def windows(ka=.00015,b=.012,direction=1):
    frames=[];speed=direction*80.0
    for i in range(24):
        accel=direction*((i%6)*60.0-90.0);end=speed+.1*accel
        frames.append(dict(seq=i+1,start_us=i*100000,end_us=(i+1)*100000,flags=0,
            speed_start_rpm=speed,speed_end_rpm=end,mean_iq_a=direction*.105+ka*accel+b,
            mean_friction_a=direction*.105,mean_speed_ref_rpm=direction*240,
            mean_speed_meas_rpm=(speed+end)*.5))
        speed=end
    return frames


class KaIdentificationTests(unittest.TestCase):
    def test_actual_c_mean_measured_current_wrap_and_passive_observer(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/('tmp/ka-ident'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/ka_identification_host.c'),
                str(ROOT/'firmware_common/ka_identification.c'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_known_physical_slope_intercept_and_reverse(self):
        for direction in (1,-1):
            r=fit.fit_direction(windows(direction=direction),direction)
            self.assertTrue(r['trusted'],r)
            self.assertAlmostEqual(r['ka_identified'],.00015)
            self.assertAlmostEqual(r['b_a'],.012)
            self.assertAlmostEqual(r['r2'],1)
            self.assertEqual([c['multiplier'] for c in r['candidates']],[.5,.75,1,1.25])
        self.assertEqual(fit.fit_direction(windows(),-1)['n'],0)

    def test_no_accel_reference_or_iq_command_substitution(self):
        frames=windows()
        for f in frames:f.update(accel_ref=99999,iq_ref=99,t_stable=99999)
        r=fit.report(dict(windows=frames))['directions'][0]
        self.assertAlmostEqual(r['ka_identified'],.00015)

    def test_flags_rest_missing_and_nonfinite_never_silently_fit(self):
        frames=windows()
        for f in frames:f['flags']=2
        self.assertFalse(fit.fit_direction(frames,1)['trusted'])
        for what in ('mean_iq_a','mean_friction_a','speed_end_rpm'):
            frames=windows();frames[0][what]=float('nan')
            r=fit.fit_direction(frames,1)
            self.assertEqual(r['n'],23)
            self.assertIn('MISSING_OR_NONFINITE',r['rejected'][0]['reasons'])
        frames=windows();frames[0]['speed_start_rpm']=0
        self.assertEqual(fit.fit_direction(frames,1)['n'],23)

    def test_constant_accel_cannot_separate_ka_and_b(self):
        frames=windows()
        for f in frames:f['speed_end_rpm']=f['speed_start_rpm']+10
        r=fit.fit_direction(frames,1)
        self.assertIsNone(r['ka_identified']);self.assertFalse(r['trusted'])
        self.assertIn('INSUFFICIENT_ACCELERATION_EXCITATION',r['problems'])

    def test_bad_model_not_residual_cherry_picked_or_written(self):
        r=fit.report(dict(windows=windows(ka=-.00015)))
        self.assertFalse(r['directions'][0]['trusted']);self.assertFalse(r['parameter_writes'])
        frames=windows()
        for f in frames:f['mean_iq_a']+=f['mean_speed_meas_rpm']*.01
        r=fit.fit_direction(frames,1)
        self.assertEqual(r['n'],24);self.assertFalse(r['trusted'])
        self.assertIn('RESIDUAL_DEPENDS_ON_SPEED',r['problems'])

    def test_existing_ka_cap_never_raised_by_multiplier(self):
        r=fit.fit_direction(windows(ka=.00024),1)
        self.assertTrue(r['trusted'])
        self.assertFalse(r['candidates'][-1]['enabled_for_manual_review'])
        self.assertTrue(r['candidates'][2]['enabled_for_manual_review'])

    def test_saved_real_capture_is_not_trusted_if_one_window_dominates(self):
        path=ROOT/'tmp/ka-ident-run-1792652514849299800.json'
        if not path.exists():self.skipTest('Real acquisition not present')
        r=fit.report(json.loads(path.read_text())['ka_capture'])['directions'][0]
        self.assertAlmostEqual(r['ka_identified'],.00008882743186093729)
        self.assertEqual(r['dominant_window_seq'],6)
        self.assertGreater(r['max_window_leverage'],.8)
        self.assertLess(r['leave_one_out_ka_min'],0)
        self.assertFalse(r['trusted'])
        self.assertIn('SINGLE_WINDOW_DOMINATES_FIT',r['problems'])
        self.assertTrue(all(not c['enabled_for_manual_review'] for c in r['candidates']))

    def test_window_sensitivity_weighted_averages_and_unverified_board(self):
        frames=windows();rough=fit.coarsen(frames)
        self.assertEqual(len(rough),12)
        self.assertAlmostEqual(rough[0]['mean_iq_a'],(frames[0]['mean_iq_a']+frames[1]['mean_iq_a'])/2)
        r=fit.report(dict(windows=frames,source='hardware_receipt',closure_verified=False))
        self.assertFalse(r['directions'][0]['trusted'])
        self.assertIn('BOARD_ACCEPTANCE_NOT_VERIFIED',r['directions'][0]['problems'])
        self.assertTrue(all(not c['enabled_for_manual_review'] for c in r['directions'][0]['candidates']))

    def test_no_mixed_runs_and_only_files_cli(self):
        f=windows();f[5]['seq']=1
        with self.assertRaises(ValueError):fit.report(dict(windows=f))
        p=subprocess.run([sys.executable,str(ROOT/'tools/ka_identification_report.py'),'--help'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0);self.assertIn('FILES ONLY',p.stdout)
        source=(ROOT/'tools/ka_identification_report.py').read_text()
        self.assertNotIn('import serial',source);self.assertNotIn('exec_command',source)

    def test_b_and_normal_a_unchanged_and_no_isr_hook(self):
        self.assertEqual(hashlib.sha256((ROOT/'foc2_app_b/build/FrictionBUnchanged/foc2.bin').read_bytes()).hexdigest(),
            '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')
        self.assertEqual(hashlib.sha256((ROOT/'foc2_app_a/build/BemfFittedFluxCandidate/foc2.bin').read_bytes()).hexdigest(),
            '6e66984d9867de2f25b362c14b6549eec2043406905f031bdf12c1594cbaad3f')
        old=expanded('a','BemfFittedFluxCandidate')
        new=expanded('a','KaIdentificationDiagnostic').replace('0.0000000f','0.0001875f')
        for name in ('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','FOC_ResetController',
            'MotorControl_SetSpeed','Encoder_ElectricalAngleRad','ProtectedLoop_PwmEntry',
            'ProtectedLoop_SetDuty','ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody',
            'PowerStage_Enable','PowerStage_Disable','TighteningTask','SpeedPiAntiWindup_Apply'):
            after=function(new,name)
            after=re.sub(r'KaIdent_Observe\([\s\S]*?\);','',after)
            self.assertEqual(re.sub(r'\s+','',function(old,name)),re.sub(r'\s+','',after),name)
        self.assertIn('KaIdent_Observe(',function(new,'FOC_EncoderSpeedUpdate'))
        self.assertNotIn('KaIdent_',function(new,'FOC_CurrentLoopStep'))
        # Protected profile bypasses the HAL callback, but its real early-ack
        # IRQ DOES advance this same accepted-sample counter before FOC.
        irq=function(new,'ProtectedLoop_AdcIrq')
        self.assertIn('++current_valid_count',irq)
        self.assertLess(irq.index('++current_valid_count'),irq.index('FOC_CurrentLoopStep('))
        self.assertIn('current_valid_count',function(new,'FOC_EncoderSpeedUpdate'))

    def test_real_compressed_log_maximum_integer_values_no_truncation(self):
        import test_pw_log_tokenized_default
        from pw_tokenizer import detokenize,tokens
        pw=ROOT/'third_party/pigweed'
        inc=[ROOT/'firmware_common',ROOT/'firmware_common/pw_log_tokenized_override',
            pw/'pw_log_tokenized/public_overrides',pw/'pw_assert/print_and_abort_assert_public_overrides',
            pw/'pw_assert/print_and_abort_check_public_overrides',pw/'third_party/fuchsia/repo/sdk/lib/stdcompat/include']
        inc += [pw/m/'public' for m in ('pw_log','pw_log_tokenized','pw_log_string','pw_tokenizer',
            'pw_preprocessor','pw_polyfill','pw_span','pw_bytes','pw_status','pw_result','pw_assert',
            'pw_varint','pw_numeric','pw_containers','pw_toolchain')]
        exe=ROOT/'tmp/ka-ident-codec.exe'
        cmd=[str(Path(GCC).with_name('g++.exe')),'-std=c++17','-Os','-Wall','-Wextra','-Werror',
            '-UNDEBUG','-DPW_LOG_TOKENIZED_ENCODING_BUFFER_SIZE_BYTES=32']
        for i in inc:cmd+=['-I',str(i)]
        cmd += [str(ROOT/'tests/ka_identification_log_host.cc'),str(pw/'pw_log_tokenized/log_tokenized.cc'),
            str(pw/'pw_tokenizer/encode_args.cc'),str(pw/'pw_varint/varint.cc'),'-o',str(exe)]
        p=subprocess.run(cmd,text=True,capture_output=True);self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],text=True,capture_output=True,check=True)
        formats=re.findall(r'PW_LOG_INFO\("([^"\n]+)"',(ROOT/'firmware_common/ka_identification_log.cc').read_text())
        decoder=detokenize.Detokenizer(tokens.Database([
            tokens.TokenizedStringEntry(tokens.pw_tokenizer_65599_hash(f),f) for f in formats]))
        self.assertEqual(len(p.stdout.splitlines()),3)
        for line in p.stdout.splitlines():
            size,data=line.split();self.assertLessEqual(int(size),32)
            out=decoder.detokenize(bytes.fromhex(data));self.assertTrue(out.ok(),str(out))
            self.assertIn('seq=4294967295',str(out))


if __name__=='__main__':unittest.main()
