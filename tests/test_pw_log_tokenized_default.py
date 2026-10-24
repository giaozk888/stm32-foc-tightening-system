"""Official codec round trips, ELF dictionary/Flash audit, frozen control API."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from test_torque_chain import GCC,FROZEN,function
from test_torque350_five_second import expanded

ROOT=Path(__file__).resolve().parents[1]
PW=ROOT/'third_party/pigweed'
sys.path.insert(0,str(ROOT/'tools'))
import detokenize_hmi_logs as hmi
from pw_tokenizer import detokenize,tokens

PROFILES=(('a','Tightening240rpmScurveCandidate','Tightening240rpmScurveTokenizedCandidate'),
          ('b','TighteningCommonModeCandidate','TighteningCommonModeTokenizedCandidate'))

def compile_cmd(slot,preset,source='/Core/Src/main.c'):
    base=ROOT/f'foc2_app_{slot}/build/{preset}'
    command=next(x['command'] for x in json.loads((base/'compile_commands.json').read_text())
        if x['file'].endswith(source))
    return base,command

def preprocess(slot,preset,source):
    base,cmd=compile_cmd(slot,preset,source)
    return subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',cmd),cwd=base,
        capture_output=True,text=True,check=True).stdout

class DefaultTokenizedTests(unittest.TestCase):
    def test_actual_cpp17_cpp20_codec_signed_float_func_once_template(self):
        out=ROOT/'tests/pw_log_tokenized_default_build'; out.mkdir(exist_ok=True)
        includes=[ROOT/'firmware_common/pw_log_tokenized_override',
            PW/'pw_log_tokenized/public_overrides',
            PW/'pw_assert/print_and_abort_assert_public_overrides',
            PW/'pw_assert/print_and_abort_check_public_overrides',
            PW/'third_party/fuchsia/repo/sdk/lib/stdcompat/include']
        includes += [PW/m/'public' for m in ('pw_log','pw_log_tokenized','pw_log_string',
            'pw_tokenizer','pw_preprocessor','pw_polyfill','pw_span','pw_bytes','pw_status',
            'pw_result','pw_assert','pw_varint','pw_numeric','pw_containers','pw_toolchain')]
        formats=['literal only','signed=%d unsigned=%u','float=%.2f','str=%s','func=%s',
                 'once=%d','template=%d','bad=%d','long=%s','c=%d','c-func=%s','c-empty']
        db=tokens.Database([tokens.TokenizedStringEntry(tokens.pw_tokenizer_65599_hash(f),f) for f in formats])
        decoder=detokenize.Detokenizer(db)
        for std,opt in (('c++17','-Os'),('c++20','-O2')):
            exe=out/('codec-'+std+'.exe')
            command=[str(Path(GCC).with_name('g++.exe')),'-std='+std,opt,'-Wall','-Wextra','-Werror',
                '-UNDEBUG','-DPW_LOG_TOKENIZED_ENCODING_BUFFER_SIZE_BYTES=32']
            for inc in includes: command += ['-I',str(inc)]
            obj=out/('c-frontend-'+std+'.o')
            ccmd=[GCC,'-std=gnu11',opt,'-Wall','-Wextra','-Werror','-UNDEBUG']
            for inc in includes: ccmd += ['-I',str(inc)]
            p=subprocess.run(ccmd+['-c',str(ROOT/'tests/pw_log_tokenized_default_host.c'),'-o',str(obj)],
                capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            command += [str(ROOT/'tests/pw_log_tokenized_default_host.cc'),
                str(PW/'pw_log_tokenized/log_tokenized.cc'),str(PW/'pw_tokenizer/encode_args.cc'),
                str(PW/'pw_varint/varint.cc'),str(obj),'-o',str(exe)]
            p=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            rows=[x.split() for x in p.stdout.splitlines()]
            self.assertEqual(len(rows),12)
            decoded=[]
            for i,(meta,size,data) in enumerate(rows):
                payload=bytes.fromhex(data)
                self.assertEqual(int(size),len(payload))
                self.assertLessEqual(len(payload),32)
                self.assertEqual(int(meta)&7,([2,3,4,2,2,2,2,4,2,2,3,4][i]))
                result=decoder.detokenize(payload)
                self.assertTrue(result.ok(),str(result))
                decoded.append(str(result))
            self.assertEqual(decoded[:8],['literal only','signed=-7 unsigned=42','float=1.25',
                'str=ok','func=main','once=1','template=17','bad=-2'])
            self.assertEqual(int(rows[8][1]),32) # original codec's bounded string truncation
            self.assertTrue(decoded[8].startswith('long=0123456789'))
            self.assertEqual(decoded[9:],['c=1','c-func=CLog','c-empty'])

    def test_all_control_protocol_frozen_functions_and_irq_objects_unchanged(self):
        for slot,base,new in PROFILES:
            before=expanded(slot,base); after=expanded(slot,new)
            for name in FROZEN+('TighteningTask','MotorControl_SetSpeed','MotorControl_SetIq',
                    'Encoder_ElectricalAngleRad','FocFeedbackSafety_Push','FocOcConfirm_Push',
                    'FocFp_PushRawSafety','ProtectedLoop_Ready','ProtectedLoop_Command',
                    'Protocol_HandleLine','Protocol_PrintStatus','PowerStage_Disable'):
                self.assertEqual(function(before,name),function(after,name),(slot,name))
            backend_before=preprocess(slot,base,'/Middleware/pigweed/pw_log_backend.c')
            backend_after=preprocess(slot,new,'/Middleware/pigweed/pw_log_backend.c')
            for name in ('PW_Log_EnqueueTokenized','pw_log_string_HandleMessageVaList','PW_Log_Task'):
                self.assertEqual(function(backend_before,name),function(backend_after,name),(slot,name))
            for obj in ('foc_adc_timing_stm32.c.obj','stm32g4xx_it.c.obj'):
                files=[next((ROOT/f'foc2_app_{slot}/build/{p}').rglob(obj)).read_bytes() for p in (base,new)]
                self.assertEqual(*files,(slot,obj))

    def test_backend_selected_and_new_compile_warnings_absent(self):
        for slot,base,new in PROFILES:
            warnings=[]
            for preset in (base,new):
                directory,cmd=compile_cmd(slot,preset,'/Middleware/pigweed/pw_smoke_test.cc')
                if preset==new:
                    self.assertIn('firmware_common/pw_log_tokenized_override',cmd)
                    self.assertNotIn('pw_log_string/public_overrides',cmd)
                    self.assertIn('pw_log_tokenized/public_overrides',cmd)
                p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),cwd=directory,
                    capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                warnings.append(set(re.findall(r'warning: (.*)',p.stderr)))
            self.assertFalse(warnings[1]-warnings[0],warnings[1]-warnings[0])
            cm=(ROOT/f'foc2_app_{slot}/CMakeLists.txt').read_text()
            self.assertRegex(cm,r'option\(PW_LOG_TOKENIZED_DEFAULT [^\n]+ OFF\)')

    def test_dictionary_only_not_flashed_and_real_format_roundtrip(self):
        for slot,base,new in PROFILES:
            directory=ROOT/f'foc2_app_{slot}/build/{new}'
            image=(directory/'foc2.bin').read_bytes(); elf=directory/'foc2.elf'
            decoder=detokenize.Detokenizer(elf)
            entries=decoder.database.entries()
            matches=[e for e in entries if 'pw_allocator test pass=%u allocs=%u before=%u low=%u after=%u' in e.string]
            self.assertEqual(len(matches),1)
            entry=matches[0]
            self.assertNotIn(b'pw_allocator test pass=',image)
            self.assertNotIn(b'Pigweed alive',image)
            self.assertIn(b'Pigweed alive',elf.read_bytes())
            # Official Python encoder + HMI decoder against the actual ARM ELF.
            from pw_tokenizer import encode
            import base64,struct
            payload=struct.pack('<I',entry.token)+encode.encode_args(1,2,300,200,300)
            item=dict(kind='pigweed_log',tokenized=True,message='$'+base64.b64encode(payload).decode(),
                token_bytes=len(payload),raw='immutable original')
            result=hmi.decode_record(item,decoder)
            self.assertEqual(result['decode_status'],'decoded')
            self.assertIn('pw_allocator test pass=1 allocs=2 before=300 low=200 after=300',result['decoded_message'])
            self.assertEqual(result['raw'],item['raw'])
            section=subprocess.run(['D:/software/arm/bin/arm-none-eabi-objdump.exe','-h',str(elf)],
                capture_output=True,text=True,check=True).stdout
            line=re.search(r'\.pw_tokenizer.entries[^\n]*\n([^\n]*)',section)[1]
            self.assertNotIn('ALLOC',line); self.assertNotIn('LOAD',line)
            self.assertLessEqual(len(image),229376)
            # Existing machine-facing text stays readable and wire-compatible.
            for marker in (b'OK STATUS STAGE=',b'OK FW CURRENT=',b'OK MOTOR TEST FILTER',
                           b'METHOD=TWO_SAMPLE',b'TRIP_MA=4000'):
                self.assertIn(marker,image)

    def test_original_a_b_images_and_board_pins_preserved(self):
        for path,sha in (
                ('foc2_app_a/build/Tightening240rpmScurveCandidate/foc2.bin',
                 'be4a89f500cd542f82e3cd1d447ee6c7ed45fabe45b55c35bcf25a62f551024f'),
                ('foc2_app_b/build/TighteningCommonModeCandidate/foc2.bin',
                 '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)

if __name__=='__main__': unittest.main()
