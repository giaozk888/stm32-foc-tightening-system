"""Old successful 240rpm runtime identity; no board operation/limit changes."""
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
SHA='95f36d0226fd25a33d74fbe61cc778264bf15ce565fa02f1225fcfe21095160e'


def commands(name):
    root=ROOT/'foc2_app_a/build'/name
    return {row['file']:set(x for x in row['command'].split() if x.startswith('-D'))
            for row in json.loads((root/'compile_commands.json').read_text())}


class OriginalRuntimeTests(unittest.TestCase):
    def test_build_matches_previous_successful_DQ_wire_image_byte_for_byte(self):
        a=ROOT/'foc2_app_a/build/DqOriginalRuntime/foc2.bin'
        b=ROOT/'foc2_app_a/build/DqDecouplingWireCandidate/foc2.bin'
        self.assertEqual(a.read_bytes(),b.read_bytes())
        self.assertEqual(hashlib.sha256(a.read_bytes()).hexdigest(),SHA)
        elf=a.with_suffix('.elf').read_bytes()
        self.assertNotIn(b'DQA R seq=',elf)

    def test_every_translation_unit_has_the_original_compile_definitions(self):
        old=commands('DqDecouplingWireCandidate');new=commands('DqOriginalRuntime')
        self.assertEqual(new,old)
        main=next(v for k,v in new.items() if k.endswith('/Core/Src/main.c'))
        self.assertIn('-DFOC_ONE_CYCLE_PWM_PIPELINE=1',main)
        self.assertIn('-DSPEED_FRICTION_I_A=0.105f',main)
        self.assertNotIn('-DFOC_DQ_AUDIT_ENABLE=1',main)
        self.assertNotIn('-DAS_DMA_TRANSACTION_US=400U',main)

    def test_timing_contracts_have_not_been_added_or_relaxed(self):
        gcc=Path('D:/Qt/Tools/mingw1310_64/bin/gcc.exe')
        code='''#include "as5047p_timing_policy.h"
_Static_assert(AS_DMA_TRANSACTION_US==200U,"old transaction");
_Static_assert(AS_DMA_SCHEDULE_LATE_US==200U,"old schedule");
_Static_assert(AS_DMA_PERIOD_US==1000U,"old period");
_Static_assert(AS_DMA_SAMPLE_MAX_AGE_US==1500U,"old freshness");
_Static_assert(AS_DMA_CONTROL_WATCHDOG_US==2500U,"old watchdog");
int main(void){return 0;}
'''
        p=subprocess.run([str(gcc),'-std=c11','-Wall','-Wextra','-Werror','-fsyntax-only',
            '-I',str(ROOT/'firmware_common'),'-x','c','-'],input=code,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_audit_candidates_and_historical_stable_B_are_preserved(self):
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())['configurePresets']
        p=next(x for x in presets if x['name']=='DqOriginalRuntime')
        self.assertEqual(p['inherits'],'DqDecouplingWireCandidate')
        self.assertEqual(p['cacheVariables']['FOC_DQ_AUDIT_ENABLE'],'OFF')
        for name in ('DqAuditCurrent','DqAuditReverseD','DqAuditReverseQ','DqAuditReverseBoth'):
            self.assertTrue((ROOT/f'foc2_app_a/build/{name}/foc2.bin').is_file())
        b=ROOT/'foc2_app_b/build/FrictionBUnchanged/foc2.bin'
        self.assertEqual(hashlib.sha256(b.read_bytes()).hexdigest(),
            '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')


if __name__=='__main__':unittest.main()
