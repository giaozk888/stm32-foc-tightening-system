import ctypes as ct
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import unittest
from test_torque350_five_second import expanded
from test_torque_chain import function
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import current_pi_compare as pi


class AuditTests(unittest.TestCase):
    def test_actual_audit_zero_first500_wrap_signs_and_saturation_all_modes(self):
        for mode in range(4):
            for opt in ('-Os','-O2'):
                exe=ROOT/f'tmp/dqa-{mode}{opt}.exe'
                p=subprocess.run([str(pi.GCC),'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                    '-DDECOUPLING_SIGN_TEST=1',f'-DDECOUPLING_SIGN_MODE={mode}',
                    '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/foc_dq_audit_host.c'),
                    str(ROOT/'firmware_common/foc_dq_audit.c'),'-o',str(exe)],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                p=subprocess.run([str(exe)],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_park_derivative_not_just_textbook_sign_and_encoder_same_direction(self):
        # Differentiate the actual rotation convention, independent of dq helper.
        theta=.7;w=31.;alpha=.3;beta=-.2;dt=1e-7
        park=lambda t:(alpha*math.cos(t)+beta*math.sin(t),-alpha*math.sin(t)+beta*math.cos(t))
        d,q=park(theta);d2,q2=park(theta+w*dt)
        self.assertAlmostEqual((d2-d)/dt,w*q,delta=2e-5)
        self.assertAlmostEqual((q2-q)/dt,-w*d,delta=2e-5)
        # v=R*i + d(flux)/dt + omega*J*flux => d:-we*Lq*Iq, q:+we*Ld*Id.
        code=r'''#include <assert.h>
#include <math.h>
#include "as5047p_protocol.h"
int main(void){for(int sign=-1;sign<=1;sign+=2){
uint16_t a=10507,b=(uint16_t)(a+sign*3);
float t1=AS5047P_ElectricalAngleRad(a,10507,10,-1);
float t2=AS5047P_ElectricalAngleRad(b,10507,10,-1);
float diff=remainderf(t2-t1,6.283185307179586f);
float rpm=AS5047P_InstantRpm(AS5047P_Delta14(b,a),-1,.001f);
float we=rpm*6.283185307179586f/60*10;
assert(fabsf(diff/.001f-we)<.001f);}
return 0;}'''
        exe=ROOT/'tmp/dqa-angle.exe'
        p=subprocess.run([str(pi.GCC),'-O2','-Wall','-Werror','-I',str(ROOT/'foc2_app_a/Core/Inc'),
            '-x','c','-','-o',str(exe)],input=code,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertEqual(subprocess.run([str(exe)]).returncode,0)

    def test_candidate_formula_signs_and_no_enable_without_diagnostic(self):
        for mode in range(4):
            dll=ROOT/f'tmp/dqa-helper-{mode}.dll'
            code='''#include "foc_dq_decoupling.h"
__declspec(dllexport) unsigned apply(unsigned on,float w,float id,float iq,float *o) {
return FocDqDecoupling_Apply((uint8_t)on,w,id,iq,o,o+1);}'''
            args=[str(pi.GCC),'-O2','-shared','-Wall','-Werror',
                '-DDECOUPLING_SIGN_TEST=1',f'-DDECOUPLING_SIGN_MODE={mode}',
                '-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(dll)]
            p=subprocess.run(args,input=code,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            lib=ct.CDLL(str(dll));lib.apply.argtypes=[ct.c_uint]+[ct.c_float]*3+[ct.POINTER(ct.c_float)]
            out=(ct.c_float*2)()
            for w in (-314.1593,0,314.1593):
                self.assertEqual(lib.apply(1,w,.1,.5,out),1)
                self.assertAlmostEqual(out[0],-w*.00001118*.5*(-1 if mode&1 else 1),places=8)
                self.assertAlmostEqual(out[1], w*.00002003*.1*(-1 if mode&2 else 1),places=8)
                self.assertEqual(lib.apply(0,w,.1,.5,out),1)
                self.assertEqual(list(out),[0,0])
            args.remove('-DDECOUPLING_SIGN_TEST=1')
            args[-1]=str(ROOT/f'tmp/dqa-helper-disabled-{mode}.dll')
            p=subprocess.run(args,input=code,capture_output=True,text=True)
            self.assertEqual(p.returncode==0,mode==0)

    def test_control_protection_and_irq_owners_frozen_audit_vs_wire(self):
        old=expanded('a','DqDecouplingWireCandidate');new=expanded('a','DqAuditCurrent')
        for name in ('FOC_EncoderSpeedUpdate','Encoder_ElectricalAngleRad','ProtectedLoop_PwmEntry',
            'ProtectedLoop_SetDuty','ProtectedLoop_TimerHealthy','ProtectedLoop_AdcIrq',
            'ProtectedLoop_GuardIrqBody','TighteningTask','MotorControl_SetIq','MotorControl_SetSpeed',
            'SpeedPiAntiWindup_Apply','FocOcConfirm_Push','FocFeedbackSafety_Push'):
            self.assertEqual(function(old,name),function(new,name),name)
        # Raw #if/#else alternatives need not have balanced braces together.
        # Inspect the actual compiled audit branch, not a raw-text brace scan.
        p=function(new,'FOC_CurrentLoopStep')
        self.assertLess(p.index('vd+=vd_ff'),p.index('mag2 = vd * vd'))
        self.assertLess(p.index('FocDqAudit_Record'),p.index('v_alpha = vd * c - vq * s;'))
        helper=(ROOT/'firmware_common/foc_dq_audit.c').read_text()
        for forbidden in ('printf','UART','HAL_','NVIC_','__disable_irq','malloc','TIM1->'):
            self.assertNotIn(forbidden,helper)
        b=ROOT/'foc2_app_b/build/FrictionBUnchanged/foc2.bin'
        self.assertEqual(hashlib.sha256(b.read_bytes()).hexdigest(),
            '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')
        # Strip ONLY the added post-PI observer, then compare the whole real
        # FOC body: PI ordering/tracking, inverse Park, SVPWM and pipeline tail.
        oldf=function(old,'FOC_CurrentLoopStep');newf=function(new,'FOC_CurrentLoopStep')
        cut=newf.index('_Static_assert(10U==10U')
        end=newf.index('FocDqAudit_Record(&dq_audit,&dq_record);',cut)+len('FocDqAudit_Record(&dq_audit,&dq_record);')
        restored=newf[:cut]+newf[end:]
        self.assertEqual(re.sub(r'\s+','',oldf),re.sub(r'\s+','',restored))

    def test_real_tokenized_log_codec_32bytes_and_arm_dictionary(self):
        import test_pw_log_tokenized_default
        from pw_tokenizer import detokenize,tokens
        import struct
        pw=ROOT/'third_party/pigweed'
        includes=[ROOT/'firmware_common',ROOT/'firmware_common/pw_log_tokenized_override',
            pw/'pw_log_tokenized/public_overrides',pw/'pw_assert/print_and_abort_assert_public_overrides',
            pw/'pw_assert/print_and_abort_check_public_overrides',
            pw/'third_party/fuchsia/repo/sdk/lib/stdcompat/include']
        includes += [pw/m/'public' for m in ('pw_log','pw_log_tokenized','pw_log_string',
            'pw_tokenizer','pw_preprocessor','pw_polyfill','pw_span','pw_bytes','pw_status',
            'pw_result','pw_assert','pw_varint','pw_numeric','pw_containers','pw_toolchain')]
        exe=ROOT/'tmp/dqa-log-codec.exe'
        cmd=[str(pi.GCC.with_name('g++.exe')),'-std=c++17','-Os','-Wall','-Wextra','-Werror',
            '-UNDEBUG','-DPW_LOG_TOKENIZED_ENCODING_BUFFER_SIZE_BYTES=32']
        for inc in includes:cmd+=['-I',str(inc)]
        cmd += [str(ROOT/'tests/foc_dq_audit_log_host.cc'),str(pw/'pw_log_tokenized/log_tokenized.cc'),
            str(pw/'pw_tokenizer/encode_args.cc'),str(pw/'pw_varint/varint.cc'),'-o',str(exe)]
        p=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        formats=re.findall(r'PW_LOG_INFO\("([^"\n]+)"',(ROOT/'firmware_common/foc_dq_audit_log.cc').read_text())
        decoder=detokenize.Detokenizer(tokens.Database([
            tokens.TokenizedStringEntry(tokens.pw_tokenizer_65599_hash(f),f) for f in formats]))
        rows=p.stdout.splitlines();self.assertEqual(len(rows),9)
        decoded=[]
        for row in rows:
            size,data=row.split();self.assertLessEqual(int(size),32)
            result=decoder.detokenize(bytes.fromhex(data));self.assertTrue(result.ok(),str(result))
            decoded.append(str(result))
        self.assertIn('us=4294967295',decoded[0]);self.assertIn('mech_rpm=-240.000000',decoded[0])
        self.assertIn('vq_dec=0.004000000',decoded[3])
        target=ROOT/'foc2_app_a/build/DqAuditCurrent/foc2.elf'
        arm=detokenize.Detokenizer(target)
        entry=next(e for e in arm.database.entries() if formats[0] in e.string)
        payload=struct.pack('<I',entry.token)+bytes.fromhex(rows[0].split()[1])[4:]
        self.assertTrue(arm.detokenize(payload).ok())
        self.assertNotIn(b'DQA R seq=',target.with_suffix('.bin').read_bytes())
        # Use the deployed metadata-bearing ARM dictionary for ALL frame rows.
        # The module/file trailer touches the last numeric argument directly.
        import dq_decoupling_audit_report as report
        target_rows=[]
        for i in range(4):
            entry=next(e for e in arm.database.entries() if formats[i] in e.string)
            data=struct.pack('<I',entry.token)+bytes.fromhex(rows[i].split()[1])[4:]
            decoded=str(arm.detokenize(data))
            self.assertIn('\u25a0module\u2666',decoded)
            target_rows.append(dict(decoded=decoded))
        frames,missing=report.coherent_frames(dict(tokenized_decoded=target_rows))
        self.assertEqual(missing,0);self.assertEqual(len(frames),1)
        self.assertAlmostEqual(frames[0]['vq_cmd'],.024,places=8)
        self.assertAlmostEqual(frames[0]['speed_meas'],-239.5,places=5)

    def test_metadata_trailer_does_not_contaminate_last_numeric_field(self):
        import dq_decoupling_audit_report as report
        line='\u25a0msg\u2666DQA V seq=7 vq_cmd=0.123000000\u25a0module\u2666DQ_AUDIT\u25a0file\u2666D:/new project/file.cc'
        self.assertEqual(report.fields(line),dict(seq='7',vq_cmd='0.123000000'))

    def test_conflicting_duplicate_sequence_is_not_joined_across_resets(self):
        import dq_decoupling_audit_report as report
        r=dict(decoded='DQA R seq=1 us=50 flags=1 mech_rpm=0 we_rad_s=0')
        receipt=dict(tokenized_decoded=[r,r.copy()])
        self.assertEqual(report.coherent_frames(receipt),([],1))
        receipt['tokenized_decoded'].append(dict(decoded=r['decoded'].replace('us=50','us=100')))
        with self.assertRaisesRegex(ValueError,'Conflicting DQA'):report.coherent_frames(receipt)

    def test_report_coherence_units_legacy_missing_maxima_and_vq_difference(self):
        import dq_decoupling_audit_report as report
        old={'dq_samples':[dict(command='MOTOR TEST DQ VOLTAGE',values=
            dict(VALID='1',SAT='0',VQ_UV='1000',VD_FF_UV='0',VQ_FF_UV='0'))]}
        r=report.compare(old,old)
        self.assertIsNone(r['on']['startup_500ms_abs_peak_v'])
        self.assertIsNone(r['on_voltage_saturates_earlier'])
        self.assertEqual(r['on_minus_off_observed_mean_vq_v'],0)
        lines=['DQA R seq=7 us=500 flags=3 mech_rpm=240 we_rad_s=251.327412',
               'DQA S seq=7 speed_ref=240 speed_meas=240 elapsed_us=0',
               'DQA I seq=7 id=0.1 iq=0.2 vd_pi=0.01 vq_pi=0.2',
               'DQA V seq=7 vd_dec=-0.000561968 vq_dec=0.000503409 vd_cmd=0.009438032 vq_cmd=0.200503409']
        sample=dict(tokenized_decoded=[dict(decoded=t) for t in lines])
        frames,missing=report.coherent_frames(sample);self.assertEqual(len(frames),1);self.assertEqual(missing,0)
        self.assertEqual(report.frame_checks(frames)['configured_math_bad'],0)
        frames[0]['we_rad_s']*=10
        self.assertEqual(report.frame_checks(frames)['configured_math_bad'],1)
        incomplete=dict(tokenized_decoded=[dict(decoded=t) for t in lines[:3]])
        self.assertEqual(report.coherent_frames(incomplete),([],1))

    def test_sram_stats_require_matching_complete_flash_elf_and_vtor(self):
        import dq_decoupling_audit_report as report
        from foc_path_profile_report import symbols
        import struct
        import tempfile
        elf=ROOT/'foc2_app_a/build/DqAuditCurrent/foc2.elf'
        addr,size=symbols(elf)['dq_audit'];self.assertEqual(size,148)
        ram=bytearray(0x20000)
        struct.pack_into('<13I8f',ram,addr-0x20000000+64,
            102,100,2,10,90,1,25,0,0,0,0,1,900,
            1e-6,2e-6,.001,.002,.09,.18,254.,0.)
        flash=bytearray(512*1024);image=elf.with_suffix('.bin').read_bytes()
        flash[0x8000:0x8000+len(image)]=image
        with tempfile.TemporaryDirectory() as d:
            ramfile=Path(d)/'ram.bin';flashfile=Path(d)/'flash.bin'
            ramfile.write_bytes(ram);flashfile.write_bytes(flash)
            r=dict(ram_capture=str(ramfile),flash_capture=str(flashfile),vtor='0x08008000',
                   elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest())
            s=report.evidence(r,elf)
            self.assertEqual(s['voltage_first_saturation_us'],25)
            self.assertAlmostEqual(s['startup_500ms_abs_peak_v'][0],.001,places=8)
            self.assertAlmostEqual(s['cruise_mean_dec_v'][1],.002,places=8)
            flash[0x8000]^=1;flashfile.write_bytes(flash)
            with self.assertRaisesRegex(ValueError,'Flash/VTOR'):report.evidence(r,elf)

    def test_four_presets_are_compile_only_and_diagnostic_off_by_default(self):
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())['configurePresets']
        modes={p['name']:p['cacheVariables']['DECOUPLING_SIGN_MODE'] for p in presets if p['name'].startswith('DqAudit')}
        self.assertEqual(modes,dict(DqAuditCurrent='0',DqAuditReverseD='1',DqAuditReverseQ='2',DqAuditReverseBoth='3'))
        cm=(ROOT/'foc2_app_a/CMakeLists.txt').read_text()
        self.assertIn('automatic excitation" OFF)',cm)
        self.assertNotIn('DECOUPLING_SIGN_TEST',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())


if __name__=='__main__':unittest.main()
