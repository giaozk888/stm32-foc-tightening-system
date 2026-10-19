"""Five-second firmware, full-window motion and batch abort tests. No devices."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import sys
import unittest
from unittest.mock import Mock,patch
from test_breakaway_current import ROOT,trace,evidence
from test_torque_chain import GCC,FROZEN,function

sys.path.insert(0,str(ROOT/'tools'))
import breakaway_current_report as report
import breakaway_current_batch as batch
import torque_chain_decode as torque


def five_evidence(sign=1,ma=100):
    data=trace([sign*i*.25 for i in range(25)],sign,ma)
    for i in range(25):
        values=list(torque.startup.FRAME.unpack_from(data,i*124)); values[0]=i*200000
        torque.startup.FRAME.pack_into(data,i*124,*values)
    terminal=list(torque.startup.FRAME.unpack_from(data,32*124)); terminal[0]=5001000
    torque.startup.FRAME.pack_into(data,32*124,*terminal)
    t=torque.analyze_samples(data,sign,0,ma)
    _,s=evidence(sign=sign,ma=ma)
    m=dict.fromkeys(report.MOTION_NAMES,0)
    m.update(count=5000,first_us=1000,last_us=4999000,max_gap_us=1000,
        net_counts=sign*280,absolute_counts=280,forward=280,stationary=4719,
        max_stationary_us=20000,tail_net_counts=sign*95,tail_absolute_counts=95)
    return t,s,m


class FiveSecondTests(unittest.TestCase):
    def test_real_owner_five_second_lease_all_grades_signed_and_observer(self):
        for opt in ('-O2','-Os'):
            exe=ROOT/f'tests/torque_chain_build/breakaway5{opt}.exe'
            r=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-DFOC_BREAKAWAY_CURRENT_TEST=1','-DFOC_BREAKAWAY_FIVE_SECOND=1',
                '-I',str(ROOT/'firmware_common'),'-I',str(ROOT/'foc2_app_a/Core/Inc'),
                str(ROOT/'tests/torque_chain_host.c'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            r=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_five_second_window_both_directions_and_sub_frame_oscillation(self):
        for sign in (-1,1):
            t,s,m=five_evidence(sign)
            r=report.evaluate(t,100,sign,s,200,True,True,m)
            self.assertEqual(r['classification'],'CONTINUOUS_ROTATION',r.get('reasons'))
            self.assertEqual(r['lease_us'],5000000)
            # Saved 200ms rows look monotonic, but task motion reveals oscillation.
            m['absolute_counts']=2000; m['forward']=1000; m['backward']=1000; m['stationary']=2999
            r=report.evaluate(t,100,sign,s,200,True,True,m)
            self.assertEqual(r['classification'],'STICK_SLIP')
            self.assertGreater(r['motion_metrics']['path_to_net_ratio'],7)

    def test_short_capture_missing_aggregate_and_bad_full_window_rejected(self):
        for defect in ('missing','gap','short','bad_ref','bad_encoder','bad_gates','wrong_counts','short_rows'):
            t,s,m=five_evidence()
            if defect=='missing': m=None
            elif defect=='gap': m['max_gap_us']=21000
            elif defect=='short': m['last_us']=220000
            elif defect=='wrong_counts': m['forward']=0
            elif defect=='short_rows': t['rows']=t['rows'][:10]
            else: m[defect]=1
            r=report.evaluate(t,100,1,s,200,True,True,m)
            self.assertEqual(r['classification'],'INSUFFICIENT_DATA',defect)

    def test_pinned_images_abi_and_no_control_changes(self):
        self.assertEqual(len(batch.image()),228972)
        self.assertEqual(report.MOTION.size,76)
        for slot in 'ab':
            base=ROOT/f'foc2_app_{slot}/build'
            a=(base/'BreakawayCurrentDiagnostic/compile_commands.json')
            b=(base/'BreakawayFiveSecondDiagnostic/compile_commands.json')
            def preprocess(path):
                commands=json.loads(path.read_text())
                c=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
                import re
                return subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',c),cwd=path.parent,
                                      capture_output=True,text=True,check=True).stdout
            left,right=preprocess(a),preprocess(b)
            for name in FROZEN+('MotorControl_SetIq','ProtectedLoop_GuardIrqBody','FocOcConfirm_Push'):
                self.assertEqual(function(left,name),function(right,name),name)
            for obj in ('stm32g4xx_it.c.obj','foc_adc_timing_stm32.c.obj'):
                self.assertEqual(next((base/'BreakawayCurrentDiagnostic').rglob(obj)).read_bytes(),
                                 next((base/'BreakawayFiveSecondDiagnostic').rglob(obj)).read_bytes())

    def test_batch_default_is_offline_and_ten_five_second_steps(self):
        with patch.object(sys,'argv',['batch']),patch.object(batch,'debug') as debug,\
             patch.object(batch.old.prior,'open_port') as port,contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(batch.main(),0)
            p=json.loads(out.getvalue()); self.assertEqual(len(p['steps']),10)
            self.assertTrue(all(s['seconds']==5 for s in p['steps']))
            self.assertEqual([s['iq_mA'] for s in p['steps'][:5]],[100,120,150,180,200])
            self.assertEqual(len(p['blocked']),2); debug.assert_not_called(); port.assert_not_called()

    def test_batch_stops_on_any_failed_grade_and_does_not_retry(self):
        row={}; fake=Path('fake')
        with patch.object(batch,'batch_input',return_value=(fake,batch.baseline())),\
             patch.object(batch,'run_step',side_effect=RuntimeError('FAULT')) as step,\
             patch.object(batch.old.prior,'checkpoint'):
            with self.assertRaisesRegex(RuntimeError,'FAULT'): batch.run_batch(row,'test',fake,b'image')
            step.assert_called_once(); self.assertEqual(len(row['children']),1)

    def test_batch_complete_is_one_pass_not_claimed_minimum(self):
        row={}; results=[]
        def run(child,name,expected,before,data,sign,ma,first):
            child['pass_']=True
            t,s,m=five_evidence(sign,ma)
            r=report.evaluate(t,ma,sign,s,200,True,True,m)
            r.update(evidence_kind='breakaway_capture',capture_id=name)
            results.append((sign,ma,first)); return Path('fake'),b'flash',r
        with patch.object(batch,'batch_input',return_value=(Path('fake'),batch.baseline())),\
             patch.object(batch,'run_step',side_effect=run),patch.object(batch.old.prior,'checkpoint'):
            batch.run_batch(row,'test',Path('stage'),b'image')
        self.assertEqual(len(results),10); self.assertEqual(sum(x[2] for x in results),1)
        self.assertTrue(row['pass_']); self.assertIsNone(row['summary']['BREAKAWAY_IQ_POS'])
        self.assertIsNone(row['summary']['IQ_FRICTION_FF'])

    def test_batch_rejects_wrong_direction_fault_timing_and_bad_iq(self):
        t,s,m=five_evidence(); r=report.evaluate(t,100,1,s,200,True,True,m)
        self.assertTrue(batch.continue_ok(r))
        for label in ('FAULT','TIMING_FAIL','WRONG_DIRECTION','INSUFFICIENT_DATA','REFERENCE_MISMATCH'):
            bad=copy.deepcopy(r); bad['classification']=label; self.assertFalse(batch.continue_ok(bad))
        r['criteria']['iq_mae']=False; self.assertFalse(batch.continue_ok(r))

    def test_batch_command_is_single_attempt_even_without_ack(self):
        row=dict(commands=[],pulse_attempts=0); port=Mock()
        uart=batch.BatchConsole(port,row); uart.read_line=Mock(return_value=None)
        with patch.object(batch.old.prior,'checkpoint'):
            with self.assertRaises(TimeoutError): uart.breakaway('MOTOR TEST BREAKAWAY POS 100 CONFIRM',.001)
            with self.assertRaises(RuntimeError): uart.breakaway('MOTOR TEST BREAKAWAY POS 100 CONFIRM',.001)
            for cmd in ('START','MOTOR TEST BREAKAWAY POS 250 CONFIRM','MOTOR TEST TORQUE POS ZERO CONFIRM'):
                with self.assertRaises(ValueError): uart.breakaway(cmd)
        self.assertEqual(port.write.call_count,1)

    def test_summary_does_not_mix_lease_durations(self):
        with self.assertRaises(ValueError): report.summarize([
            dict(evidence_kind='breakaway_capture',five_second=True),dict(evidence_kind='breakaway_capture',five_second=False)])

    def test_matching_five_second_flash_ram_and_full_window_abi(self):
        elf=batch.ELF; table=report.symbols(elf)
        flash=bytearray(0x80000); image=elf.with_suffix('.bin').read_bytes()
        flash[0x8000:0x8000+len(image)]=image; ram=bytearray(0x20000)
        def put(name,data):
            address,size=table[name]; self.assertEqual(len(data),size)
            ram[address-0x20000000:address-0x20000000+size]=data
        import struct
        put('breakaway_capture_tag',struct.pack('<I',0x42574135))
        put('torque_diag',torque.META.pack(100,1,0,1,0,1,0,0,0,100))
        data=trace([i*.25 for i in range(25)])
        for i in range(25): struct.pack_into('<I',data,i*124,i*200000)
        struct.pack_into('<I',data,32*124,5001000); put('cl_startup',data)
        put('cl_session',struct.pack('<II4B',1000,0,3,1,0,1))
        put('cl_stop_us',struct.pack('<I',5001000))
        _,_,m=five_evidence(); put('breakaway_motion',report.MOTION.pack(*(m[k] for k in report.MOTION_NAMES)))
        timing=[0]*35; timing[2]=5100; put('foc_preempt_timing',struct.pack('<35I',*timing))
        probe=[0]*32; probe[0]=1; probe[5]=1700; put('foc_pwm_write_profile',struct.pack('<32I',*probe))
        with tempfile.TemporaryDirectory() as folder:
            rp=Path(folder)/'ram.bin'; fp=Path(folder)/'flash.bin'; rp.write_bytes(ram); fp.write_bytes(flash)
            r=report.capture_report(elf,rp,fp,0x08008000)
            self.assertEqual(r['classification'],'CONTINUOUS_ROTATION',r.get('reasons'))
            self.assertEqual(r['motion_sample_count'],5000)
            self.assertAlmostEqual(r['statistics']['total_absolute_travel_deg'],280*360/16384)
            put('breakaway_motion',bytes(report.MOTION.size)); rp.write_bytes(ram)
            self.assertEqual(report.capture_report(elf,rp,fp,0x08008000)['classification'],'INSUFFICIENT_DATA')

    def test_standstill_checks_position_and_fault_without_advancing(self):
        uart=Mock(); uart.query.return_value='OK STATUS MODE=IDLE BUSY=0 FLT=0 POS=1.00deg CTRL=0.0rpm DET=0.0rpm'
        clock=iter(i*.1 for i in range(100))
        with patch.object(batch,'off_state'):
            self.assertGreaterEqual(len(batch.standstill(uart,'3',clock=lambda:next(clock))),10)
        uart.query.return_value='OK STATUS MODE=IDLE BUSY=0 FLT=0 POS=1.00deg CTRL=2.0rpm DET=0.0rpm'
        clock=iter(i*.1 for i in range(1000))
        with patch.object(batch,'off_state'):
            with self.assertRaisesRegex(TimeoutError,'stable'): batch.standstill(uart,'3',clock=lambda:next(clock))
        uart.query.return_value='OK STATUS MODE=IDLE BUSY=0 FLT=1 POS=1.00deg CTRL=0.0rpm DET=0.0rpm'
        with patch.object(batch,'off_state'):
            with self.assertRaisesRegex(RuntimeError,'Standstill mode'): batch.standstill(uart,'3')

    def test_failed_preflight_or_unknown_ack_always_stops_captures_and_never_retries(self):
        for failure in ('preflight','ack'):
            row=dict(commands=[],steps=[],pulse_attempts=0); uart=Mock(); port=Mock()
            uart.breakaway.side_effect=TimeoutError('unknown ACK')
            with patch.object(batch.old.prior,'open_port',return_value=port),\
                 patch.object(batch,'BatchConsole',return_value=uart),patch.object(batch,'debug'),\
                 patch.object(batch.old.prior,'checkpoint'),patch.object(batch.old.prior,'wait_health_confirmation'),\
                 patch.object(batch,'preflight',side_effect=RuntimeError('not ready') if failure=='preflight' else None),\
                 patch.object(batch.old,'capture_stopped') as capture:
                with self.assertRaises((RuntimeError,TimeoutError)):
                    batch.run_step(row,'mock',Path('expected'),b'flash',b'img',1,100,True)
            capture.assert_called_once()
            self.assertEqual([c.args[0] for c in uart.query.call_args_list],['STOP','ANALOG SAFE'])
            self.assertEqual(uart.breakaway.call_count,0 if failure=='preflight' else 1)
            port.close.assert_called_once()

    def test_halted_stage_never_resets_or_resumes_and_programs_only_inactive_a(self):
        before=batch.baseline(); data=batch.image(); after=bytearray(before)
        end=(0x8000+len(data)+0x7ff)&~0x7ff
        after[0x8000:end]=data+b'\xff'*(end-0x8000-len(data))
        output='VTOR=0x08040000\nDHCSR=0x30003\nSD=0x0\nBDTR=0x0\nCCER=0x0\n'
        with tempfile.TemporaryDirectory(dir=batch.TMP) as folder:
            name=Path(folder).name+'/mock'; calls=[]
            def debug(row,commands):
                calls.extend(commands)
                for command in commands:
                    if command.startswith('dump_image') and command.endswith(' 0x08000000 0x80000'):
                        Path(command.split('{',1)[1].split('}',1)[0]).write_bytes(after)
                return output
            row={}
            with patch.object(batch,'HALTED_STAGE_VALIDATED',True),\
                 patch.object(batch,'debug',side_effect=debug),patch.object(batch.old.prior,'checkpoint'):
                batch.stage_halted(row,name,data)
            self.assertTrue(row['pass_']); self.assertFalse(row['physical_power_off'])
            self.assertFalse(row['reset_attempted']); self.assertFalse(row['application_resumed'])
            self.assertFalse(any('reset ' in c or c=='resume' for c in calls))
            writes=[c for c in calls if c.startswith('flash write_image')]
            self.assertEqual(len(writes),1); self.assertTrue(writes[0].endswith(' 0x08008000 bin'))
            self.assertTrue(any('PC6 is not push-pull output' in c for c in calls))
            self.assertTrue(any('PWM timer running' in c for c in calls))

    def test_halted_stage_failed_gate_never_programs(self):
        row={}
        with patch.object(batch,'HALTED_STAGE_VALIDATED',True),\
             patch.object(batch,'debug',side_effect=RuntimeError('GPIO/halt gate')) as debug,\
             patch.object(batch.old.prior,'checkpoint'):
            with self.assertRaisesRegex(RuntimeError,'GPIO/halt gate'):
                batch.stage_halted(row,'not-written',batch.image())
        debug.assert_called_once(); self.assertNotIn('programming_attempted',row)

    def test_real_no_reset_flash_failure_quarantines_route_before_devices(self):
        self.assertFalse(batch.HALTED_STAGE_VALIDATED)
        with patch.object(batch,'debug') as debug:
            with self.assertRaisesRegex(RuntimeError,'quarantined'): batch.stage_halted({},'no-run',b'')
            debug.assert_not_called()
        with patch.object(sys,'argv',['batch','--stage-halted-output-off']),\
             patch.object(batch,'image') as image,contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit): batch.main()
            image.assert_not_called()

    def test_drive_off_recovery_only_inactive_a_and_no_activation(self):
        before=batch.failed_baseline(); image=batch.image(); expected=bytearray(before)
        end=(0x8000+len(image)+0x7ff)&~0x7ff
        expected[0x8000:end]=image+b'\xff'*(end-0x8000-len(image))
        for reset_matches in (False,True):
            calls=[]; row=dict(physical_power_off=True)
            with tempfile.TemporaryDirectory(dir=batch.TMP) as folder:
                name=Path(folder).name+'/mock'
                def debug(row,commands):
                    calls.extend(commands)
                    for command in commands:
                        if command.startswith('dump_image'):
                            path=Path(command.split('{',1)[1].split('}',1)[0])
                            content=expected if path.name.endswith('-staged.bin') or reset_matches else before
                            path.write_bytes(content)
                    vtor='0x08040000' if not row.get('reset_attempted') else '0x0'
                    return f'VTOR={vtor}\nDHCSR=0x30003\nSD=0\nBDTR=0\nCCER=0\n'.replace('=0\n','=0x0\n')
                with patch.object(batch,'debug',side_effect=debug),patch.object(batch.old.prior,'checkpoint'):
                    batch.recover_stage_off(row,name,image)
                self.assertTrue(row['pass_']); self.assertFalse(row['activation'])
                self.assertEqual(row['image_correct_after_reset'],reset_matches)
                self.assertEqual(calls.count('reset halt'),1)
                self.assertFalse(any(c=='resume' or c=='reset run' or '0x2001FFC0' in c for c in calls))
                writes=[c for c in calls if c.startswith('flash write_image')]
                self.assertEqual(len(writes),0 if reset_matches else 1)
                self.assertTrue(all(c.endswith(' 0x08008000 bin') for c in writes))

    def test_recovery_requires_drive_off_and_failed_gate_never_programs(self):
        with patch.object(batch,'debug') as debug:
            with self.assertRaises(ValueError): batch.recover_stage_off({},'no',b'')
            debug.assert_not_called()
        row=dict(physical_power_off=True)
        with patch.object(batch,'debug',side_effect=RuntimeError('changed board')) as debug:
            with self.assertRaises(RuntimeError): batch.recover_stage_off(row,'no',batch.image())
            debug.assert_called_once(); self.assertNotIn('programming_attempted',row)

    def test_compute_verification_console_cannot_send_pulse(self):
        row=dict(commands=[],pulse_attempts=0); port=Mock()
        uart=batch.VerifyConsole(port,row)
        for sign in ('POS','NEG'):
            for ma in (100,120,150,180,200,250):
                with self.assertRaises(ValueError): uart.breakaway(f'MOTOR TEST BREAKAWAY {sign} {ma} CONFIRM')
        with self.assertRaises(ValueError): uart.query('START')
        port.write.assert_not_called()

    def test_compute_verification_only_reads_stops_and_saves(self):
        row=dict(commands=[],steps=[]); uart=Mock(); port=Mock()
        uart.breakaway.return_value='OK BREAKAWAY IQ_MA=0 USED=0 ACTIVE=0'
        timing=dict(wall_max_us=28,deadline_miss=0,actual_late_count=0,actual_margin_min_us=8)
        def capture(row,*args,**kwargs):
            row.update(final_cpu_halted=True,final_outputs_off=True,all_app_private_unchanged=True,
                       snapshot=dict(first_fault=dict(valid=0),timing=timing))
        with patch.object(batch,'staged_receipt',return_value=(Path('fake'),b'flash')),\
             patch.object(batch.old.prior,'open_port',return_value=port),\
             patch.object(batch,'VerifyConsole',return_value=uart),patch.object(batch,'debug'),\
             patch.object(batch.old.prior,'checkpoint'),patch.object(batch.old.prior,'wait_health_confirmation'),\
             patch.object(batch,'preflight'),patch.object(batch,'off_state',return_value=dict(USED='0',QUEUED='0')),\
             patch.object(batch.old,'capture_stopped',side_effect=capture):
            batch.verify_compute(row,'fake',Path('stage'),b'image')
        self.assertTrue(row['pass_']); self.assertEqual(row['motor_commands'],0)
        self.assertEqual([c.args[0] for c in uart.breakaway.call_args_list],[batch.STATUS])
        self.assertEqual([c.args[0] for c in uart.query.call_args_list],['STOP','ANALOG SAFE'])

    def test_verified_a_receipt_is_exact_input_without_replaying_b_to_a_trial(self):
        path=batch.TMP/'breakaway5-verify-1792388031737461800.json'
        expected,raw=batch.batch_input(path,batch.image())
        self.assertEqual(batch.old.zero.latest_meta(raw)[2:5],(1,0,0))
        with patch.object(batch,'batch_input',return_value=(expected,raw)),\
             patch.object(batch,'run_step',side_effect=RuntimeError('mock stop before motion')) as step,\
             patch.object(batch.old.prior,'checkpoint'):
            with self.assertRaises(RuntimeError): batch.run_batch({},'fake',path,batch.image())
        self.assertFalse(step.call_args.args[-1])

    def test_real_first_five_second_capture_preserves_rejected_boundary_evidence(self):
        prefix=batch.TMP/'breakaway5-batch-1792388286865682600-00'
        r=report.capture_report(batch.ELF,Path(str(prefix)+'-ram.bin'),
                                Path(str(prefix)+'-flash.bin'),0x08008000)
        self.assertEqual(r['classification'],'STICK_SLIP')
        self.assertEqual(r['actual_output_stop_us'],5000010)
        self.assertEqual(r['full_window_motion']['count'],5000)
        self.assertEqual(r['full_window_motion']['last_us'],5000003)
        self.assertEqual(r['full_window_motion']['net_counts'],49)
        self.assertEqual(r['metadata']['iq_mA'],100)

    def test_rolling_standstill_waits_out_small_initial_coast(self):
        uart=Mock(); values=iter([.68,.65,.76]+[.74]*100)
        def query(*args):
            return f'OK STATUS MODE=IDLE BUSY=0 FLT=0 POS={next(values):.2f}deg CTRL=0.1rpm DET=0.0rpm'
        uart.query.side_effect=query
        clock=iter(i*.1 for i in range(1000))
        with patch.object(batch,'off_state'):
            samples=batch.standstill(uart,'3',clock=lambda:next(clock))
        self.assertGreater(max(x[0] for x in samples)-min(x[0] for x in samples),.1)
        self.assertGreater(len(samples),10)

    def test_explicit_resume_skips_completed_grade_and_never_accepts_board_fault(self):
        path=batch.TMP/'breakaway5-batch-1792388286865682600-00.json'
        expected,raw,start,prior=batch.resume_coast_input(path,batch.image())
        self.assertEqual(start,1); self.assertEqual(prior['iq_mA'],100)
        with patch.object(batch,'resume_coast_input',return_value=(expected,raw,start,prior)),\
             patch.object(batch,'run_step',side_effect=RuntimeError('mock stop')) as step,\
             patch.object(batch.old.prior,'checkpoint'):
            with self.assertRaises(RuntimeError): batch.run_batch({},'fake',path,batch.image(),resume=True)
        self.assertEqual(step.call_args.args[-3:],(1,120,False))
        bad=json.loads(path.read_text()); bad['failure']='CURRENT_INVALID'
        with patch.object(batch.json,'loads',return_value=bad):
            with self.assertRaises(ValueError): batch.resume_coast_input(path,batch.image())

    def test_actual_stop_boundary_is_proven_not_clamped_or_arbitrary(self):
        t,s,m=five_evidence(); m['last_us']=5000003
        self.assertEqual(report.evaluate(t,100,1,s,200,True,True,m)['classification'],'INSUFFICIENT_DATA')
        self.assertEqual(report.evaluate(t,100,1,s,200,True,True,m,5000010)['classification'],'CONTINUOUS_ROTATION')
        self.assertEqual(report.evaluate(t,100,1,s,200,True,True,m,5000002)['classification'],'INSUFFICIENT_DATA')
        self.assertEqual(report.evaluate(t,100,1,s,200,True,True,m,5100000)['classification'],'INSUFFICIENT_DATA')


if __name__=='__main__': unittest.main()
