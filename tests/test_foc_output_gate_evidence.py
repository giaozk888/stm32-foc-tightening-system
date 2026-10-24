"""Offline-only regression for failed-gate pre-closure evidence."""
import hashlib
import subprocess
import unittest
import struct
import json
import re
from pathlib import Path
import test_current_step_ab as step
from foc_output_gate_evidence_report import decode_bytes, FIELDS, SIZE

ROOT=Path(__file__).resolve().parents[1]

class GateEvidenceTests(unittest.TestCase):
    def test_actual_binding_and_original_predicate(self):
        out=ROOT/'tmp/current-step-host';out.mkdir(exist_ok=True)
        for opt in ('-O2','-Os'):
            exe=out/f'gate-evidence-{opt}.exe'
            subprocess.run([str(step.pi.GCC),'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/foc_output_gate_evidence_host.c'),
                '-o',str(exe)],check=True,capture_output=True,text=True)
            result=subprocess.run([str(exe)],check=True,capture_output=True,text=True)
            self.assertIn('PASS gate evidence',result.stdout)

    def test_no_algorithm_shutdown_or_threshold_edits(self):
        old=step.expanded('a','CurrentStepAbDiagnostic')
        new=step.expanded('a','CurrentStepAbGateEvidence')
        for name in ('ProtectedLoop_EmergencyOff','ProtectedLoop_Stop','ProtectedLoop_TimerHealthy',
                     'ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage','ProtectedLoop_PwmCommitPermit',
                     'ProtectedLoop_Pair','ProtectedLoop_TaskService','FOC_EncoderSpeedUpdate',
                     'FocCurrentValidation_Push','FOC_ResetController','CurrentStep_FocReference'):
            self.assertEqual(step.function(old,name),step.function(new,name),name)
        source=(ROOT/'firmware_common/foc_output_gate_evidence_binding.inc').read_text()
        self.assertNotRegex(source,r'(?:TIM1|DRIVER_SD_GPIO_Port)->\w+\s*[|&]?=')
        self.assertNotRegex(source,r'\b(?:printf|snprintf|UART_|HAL_)')
        self.assertNotIn('UDIS',source)
        self.assertNotIn('ProtectedLoop_GatesObserved',old)
        self.assertNotIn('cl_output_gate_evidence',step.expanded('b','CurrentPiBUnchanged'))

    def test_original_builds_unchanged(self):
        expected={
            'a/build/CurrentStepAbDiagnostic':'d7b3dd465a113d1f7efcec85fcd472bd8706dbb34566317c5f4ef6b82c2ec9eb',
            'a/build/CurrentPiIdentifiedCandidate':'aaeee6b02372f9ecac2d8ec0ecb171f17bf87df41e54f43fe52b4ec9d404b56e',
            'a/build/CurrentPiLegacyCompare':'3adf71acf9579d455f9e0f27e27d121a863c570cde9f0baabb65b9f587ef2899',
            'b/build/FrictionBUnchanged':'7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366'}
        for directory,digest in expected.items():
            self.assertEqual(hashlib.sha256((ROOT/('foc2_app_'+directory)/'foc2.bin').read_bytes()).hexdigest(),digest)

    def test_new_build_has_no_new_main_warning(self):
        messages=[]
        for name in ('CurrentStepAbDiagnostic','CurrentStepAbGateEvidence'):
            directory=ROOT/'foc2_app_a/build'/name
            command=next(r['command'] for r in json.loads((directory/'compile_commands.json').read_text())
                         if r['file'].endswith('/Core/Src/main.c'))
            check=re.sub(r' -o \S+ -c ',' -fsyntax-only ',command)
            self.assertIn('-fsyntax-only',check)
            p=subprocess.run(check,cwd=directory,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            messages.append(set(re.findall(r'warning: (.*)',p.stderr)))
        self.assertFalse(messages[1]-messages[0],messages[1]-messages[0])

    def test_decoder_never_claims_a_writer_or_replaces_preoff_values(self):
        self.assertEqual(SIZE,80)
        self.assertEqual(decode_bytes(bytes(SIZE))['status'],'NO_FAILED_PREDICATE_CAPTURED')
        values=dict.fromkeys(FIELDS,0)
        values.update(valid=1,version=1,mismatch=16,state_before=2,state_used=2,state_after=2,
                      odr=64,bdtr_moe_read=32768,cr1=1,ccer=0x444,seq_before=700,seq_after=700)
        pack=lambda:struct.pack('<20I',*(values[k] for k in FIELDS))
        row=decode_bytes(pack())
        self.assertEqual(row['failed_inputs'],['CCER_UNEXPECTED'])
        self.assertFalse(row['observation_spanned_adc_or_state_change'])
        self.assertEqual(row['writer_attribution'],'NOT_PROVEN_BY_REGISTER_READS')
        values['seq_after']=701
        self.assertTrue(decode_bytes(pack())['observation_spanned_adc_or_state_change'])
        values['version']=2
        with self.assertRaises(ValueError):decode_bytes(pack())
        values['version']=1;values['mismatch']=8
        with self.assertRaises(ValueError):decode_bytes(pack())

if __name__=='__main__':unittest.main()
