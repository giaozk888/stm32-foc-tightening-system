"""Fitted candidate, real formula and protected host driver; no devices."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_torque_chain import ROOT, GCC, function
from test_torque350_five_second import expanded
sys.path.insert(0,str(ROOT/'tools'))
import bemf_fitted_fsm_board as fitted


class BemfFittedTests(unittest.TestCase):
    def test_real_psi_formula_and_wire_units(self):
        code='''#include <assert.h>
#include "foc_bemf_feedforward.h"
int main(void) {
 float v;
 assert((int)(FOC_BEMF_PSI_WB*1e9f)==697320);
 assert(FocBemf_Configured());
 assert(FocBemf_Apply(1,251.327412f,&v));
 assert(fabsf(v-.17525565f)<.000001f);
 assert(FocBemf_Apply(1,-251.327412f,&v));assert(v<0);
 assert(FocBemf_Apply(1,0,&v));assert(v==0);
 assert(FocBemf_Apply(0,NAN,&v));assert(v==0);
 assert(!FocBemf_Apply(1,NAN,&v));assert(v==0);
 return 0;
}'''
        exe=ROOT/'tmp/bemf-fitted-formula.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror',
            '-DFOC_BEMF_PSI_WB=0.00069732f','-I',str(ROOT/'firmware_common'),
            '-x','c','-','-o',str(exe)],input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertEqual(subprocess.run([str(exe)]).returncode,0)

    def test_preprocessed_control_and_protection_only_flux_constant_differs(self):
        old=expanded('a','BemfFeedforwardCandidate');new=expanded('a','BemfFittedFluxCandidate')
        for name in ('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','Encoder_ElectricalAngleRad',
                     'ProtectedLoop_PwmEntry','ProtectedLoop_SetDuty','ProtectedLoop_TimerHealthy',
                     'ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody','PowerStage_Enable',
                     'PowerStage_Disable','TighteningTask','MotorControl_SetIq','MotorControl_SetSpeed',
                     'FocBemf_Apply','FocBemf_Configured','Bemf_Command'):
            self.assertEqual(function(old,name),function(new,name).replace('0.00069732f','0.0f'),name)
        self.assertIn('CL_OVERSPEED_RPM=300U',new)
        cmd=next(c['command'] for c in json.loads((fitted.IMAGE.parent/'compile_commands.json').read_text())
            if c['file'].endswith('/Core/Src/main.c'))
        self.assertIn('-DFOC_BEMF_ENABLED_DEFAULT=0 ',cmd)
        self.assertNotIn('-DFOC_PSI_IDENT',cmd)

    def test_exact_image_and_default_files_only(self):
        self.assertEqual(fitted.image(),fitted.IMAGE.read_bytes())
        p=subprocess.run([sys.executable,str(ROOT/'tools/bemf_fitted_fsm_board.py')],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('no devices',p.stdout)
        with patch.object(fitted,'configure') as cfg:
            for args in (['--stage-off'],['--execute-powered','missing.json']):
                with self.assertRaises(SystemExit):fitted.main(args)
            cfg.assert_not_called()

    @staticmethod
    def row():
        return dict(final_cpu_halted=True,final_outputs_off=True,all_app_private_unchanged=True,
            outputs=dict(VTOR=0x08008000,SD=0,BDTR=0,CCER=0),start_attempts=1,preflight_pass=True,
            fsm_observation_complete=True,terminal_status=dict(OUTCOME='RUNDOWN_TIMEOUT',FLT='0',CONTACT='0'),
            postflight={'MOTOR TEST FAULT':'1 OK MOTOR TEST FAULT VALID=0 FLAGS=0'},
            snapshot=dict(timing=dict(deadline_miss=0,actual_late_count=0,wall_max_us=30.,actual_margin_min_us=13.),
                first_fault=dict(valid=0),cur_confirm=dict(fault=0)),
            encoder_saved=dict(first_fault=dict(valid=0),counters=dict(timeouts=0,dma_errors=0,schedule_misses=0,control_stale=0)),
            bemf_samples=[dict(values=dict(VALID='1',ON='1',SAT='0',WE_MRAD_S='250000',VQ_FF_UV='174330'))])

    def test_classify_never_promotes_no_load_timeout_to_tightening_ok(self):
        r=self.row();result=fitted.classify(r)
        self.assertTrue(result['acquisition_complete']);self.assertFalse(result['tightening_ok'])
        self.assertEqual(result['outcome'],'RUNDOWN_TIMEOUT')
        for edit in ('guard','late','shutdown','encoder','missing_ff','wrong_formula'):
            r=self.row()
            if edit=='guard':r['snapshot']['first_fault']['valid']=1
            if edit=='late':r['snapshot']['timing']['actual_late_count']=1
            if edit=='shutdown':r['outputs']['BDTR']=0x8000
            if edit=='encoder':r['encoder_saved']['counters']['timeouts']=1
            if edit=='missing_ff':r['bemf_samples']=[]
            if edit=='wrong_formula':r['bemf_samples'][0]['values']['VQ_FF_UV']='10000'
            with self.assertRaises(RuntimeError,msg=edit):fitted.classify(r)

    def test_expected_process_timeout_not_mistaken_for_hardware_fault(self):
        r=self.row()
        r['snapshot']['first_fault']=dict(valid=1,domain=3,fault_reason=3,timeout_reason=0,protection_flags=0)
        r['postflight']['STATUS']='1 OK STATUS UDROP=150'
        result=fitted.classify(r)
        self.assertTrue(result['expected_process_timeout_snapshot'])
        self.assertFalse(result['tightening_ok']);self.assertFalse(result['full_uart_telemetry_complete'])
        self.assertEqual(result['uart_dropped_bytes'],150)
        for field,value in (('domain',2),('fault_reason',4),('timeout_reason',1),('protection_flags',8)):
            bad=copy.deepcopy(r);bad['snapshot']['first_fault'][field]=value
            with self.assertRaises(RuntimeError):fitted.classify(bad)

    def test_switch_before_single_original_motion_and_reject_wrong_flux(self):
        class Board:
            def __init__(self):self.commands=[]
            def command(self,cmd):
                self.commands.append(cmd)
                return '1 OK BEMF ON='+('1' if cmd.endswith(' ON') else '0')+' CONFIGURED=1 PSI_NWB=697320 DQ_CROSS=0'
        b=Board();row={}
        with patch.object(fitted,'ORIGINAL_MOTION') as motion:
            fitted.motion(b,row);motion.assert_called_once_with(b,row)
        self.assertEqual(b.commands,['MOTOR TEST BEMF STATUS','MOTOR TEST BEMF ON'])
        with self.assertRaises(RuntimeError):fitted.status('1 OK BEMF ON=1 CONFIGURED=1 PSI_NWB=588268 DQ_CROSS=0',True)

    def test_powered_reverify_commands_are_read_only_and_require_confirmation(self):
        with patch.object(fitted,'configure') as cfg:
            with self.assertRaises(SystemExit):fitted.main(['--verify-existing-powered'])
            cfg.assert_not_called()
        src=(ROOT/'tools/bemf_fitted_fsm_board.py').read_text()
        body=src.split('def verify_existing(',1)[1].split('\n\ndef staged(',1)[0]
        for forbidden in ('reset halt','reset run','write_mailbox','flash write_image','off_commands()'):
            self.assertNotIn(forbidden,body)
        self.assertIn('full_compare_commands',body)
        self.assertIn('before[0x8000:0x8000+len(data)]!=data',body)

    def test_read_only_receipt_cannot_disguise_programming_or_stale_capture(self):
        import tempfile,hashlib
        with tempfile.TemporaryDirectory(dir=fitted.TMP) as d:
            data=b'IMAGE';raw=b'\xff'*0x8000+data
            a=Path(d)/'a.bin';b=Path(d)/'b.bin';receipt=fitted.TMP/'bemf-readiness-unit.json'
            a.write_bytes(raw);b.write_bytes(raw)
            row=dict(read_only_existing_verified=True,mode='stage',image_sha256=fitted.SHA,
                elf_sha256=fitted.ELF_SHA,staged_capture=str(a),independent_capture=str(b),
                baseline_restore_receipt=str(fitted.ROOT_RESTORE),pass_=True,powered_no_alarm=True,
                independent_readback_pass=True,final_cpu_halted=True,final_outputs_off=True,
                flash_programming=False,activation=False,motor_commands=0,
                staged_sha256=hashlib.sha256(raw).hexdigest())
            # Exercise real private-root validation with mocks for the files,
            # not a weakened production directory check.
            a=fitted.TMP/'bemf-readiness-a-unit.bin';b=fitted.TMP/'bemf-readiness-b-unit.bin'
            row.update(staged_capture=str(a),independent_capture=str(b))
            original_read=Path.read_bytes
            original_text=Path.read_text
            def read_bytes(path):return raw if path in (a,b) else original_read(path)
            def read_text(path,*args,**kwargs):return json.dumps(row) if path==receipt else original_text(path,*args,**kwargs)
            with patch.object(Path,'read_bytes',read_bytes),patch.object(Path,'read_text',read_text), \
                 patch.object(fitted.base,'baseline',return_value=raw), \
                 patch.object(fitted.base,'BASE_RESTORE_RECEIPT',fitted.ROOT_RESTORE.resolve()):
                self.assertEqual(fitted.staged(receipt,data),(a,raw))
                row['flash_programming']=True
                with self.assertRaises(ValueError):fitted.staged(receipt,data)


if __name__=='__main__':unittest.main()
