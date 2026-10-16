"""One exact staged A trial, then at most one 20 rpm / 400 ms local motion.

No flash writes, forced confirmation, reset command, fault clear or retry.
The operator must prepare a fixed unloaded motor and powered limited drive.
"""
import argparse
import json
from pathlib import Path
import time

import protected_compact_closed_loop_stage as profile
import protected_closed_loop_acceptance as shared
from protected_irq_timing_acceptance import TimingConsole, adc_timing
from protected_irq_priority_fix_acceptance import validate_encoder
from protected_fast_math_acceptance import validate_cost
from protected_pair_fast_acceptance import validate_late
from powered_boot_probe import require_staged
from firmware_transfer_iap import fields
from zero_retest_deploy import compare_flash, require_confirmed

STAGE=profile.OUTPUT/'compact-closed-loop-stage-1792044494338511600.json'

class MotorConsole(TimingConsole):
    READ=TimingConsole.READ|frozenset(('MOTOR TEST PROFILE','MOTOR TEST RAM','MOTOR TEST COMPACT'))
    def query(self,text,timeout=2):
        if text not in self.READ and text not in ('FW END','MOTOR TEST SPEED','MOTOR TEST STOP','ANALOG SAFE'):
            raise ValueError('Only exact local short trial, read/stop; no reset/clear/setpoints')
        # Original console counts commits and starts BEFORE writing; timeout
        # can never cause a duplicate FW END or a duplicate motion command.
        return shared.Console.query(self,text,timeout)

def stage_evidence(path):
    path=Path(path).resolve()
    if path!=STAGE.resolve(): raise RuntimeError('Exact current inactive A receipt required')
    r=json.loads(path.read_text('utf-8'))
    if (r.get('pass_') is not True or r.get('mode')!='stage' or
        r.get('target_slot')!='A' or r.get('fallback_slot')!='B' or
        r.get('image_sha256')!=profile.SHA or r.get('activation') is not False or
        r.get('resets')!=0 or r.get('motor_commands')!=0 or
        r.get('all_bytes_outside_a_unchanged') is not True):
        raise RuntimeError('Successful exact inactive A stage required')
    paths=[Path(r.get(k+'_backup','')).resolve() for k in ('before','staged')]
    if any(p.parent!=(profile.OUTPUT/'private').resolve() for p in paths):
        raise RuntimeError('Private capture path mismatch')
    before,staged=(p.read_bytes() for p in paths)
    profile.verified_baseline(before,r.get('baseline_receipt'))
    data=profile.pinned_image()
    compare_flash(before,staged,data,'A',staged=True)
    if before[:0x8000]!=staged[:0x8000] or before[0x40000:]!=staged[0x40000:]:
        raise RuntimeError('Stage changed bytes outside A')
    return data,before,staged

def sample(uart):
    row=dict(host_time=time.monotonic())
    row['state']=fields(uart.query('MOTOR TEST STATUS'))
    encoder=uart.encoder_diag()
    for key in ('dma','snapshot','spi','dma_hw','irq'):
        row['encoder_'+key]=encoder.get(key)
    for key,cmd in (('timing','MOTOR TEST TIMING'),('adc','ADC TIMING'),
        ('protection','MOTOR TEST PROTECTION'),('buffer','ADC BUFFER'),
        ('fault','MOTOR TEST FAULT'),('cost','MOTOR TEST COST'),
        ('late_frame','MOTOR TEST LATE'),('zero','MOTOR TEST ZERO'),
        ('profile','MOTOR TEST PROFILE'),('ram','MOTOR TEST RAM'),('compact','MOTOR TEST COMPACT')):
        row[key]=fields(uart.query(cmd))
    row['status']=uart.query('STATUS')
    return row

def validate(row,ready=False):
    def line(key): return 'OK '+' '.join(f'{k}={v}' for k,v in row[key].items())
    shared.protected_state(line('state'),ready=ready)
    shared.timing(line('timing')); shared.protection(line('protection'))
    adc_timing(line('adc')); validate_encoder(row); validate_cost(row); validate_late(row)
    expected=dict(NAME='COMPACT_CLOSED_LOOP',HARD_OFF='0',ADAPT='0',ZERO='BOUNDED',
                  LOCAL='1',RPM='20',LEASE_US='400000',QUALIFIED='0')
    if any(row['profile'].get(k)!=v for k,v in expected.items()):
        raise RuntimeError('Exact protected compact motor profile absent')
    if any(row['ram'].get(k)!=v for k,v in (('ENABLED','1'),('HARD_OFF','0'),('DEADLINE_US','50'))):
        raise RuntimeError('Protected RAM identity absent')
    if any(row['compact'].get(k)!=v for k,v in
        (('ENABLED','1'),('HARD_OFF','0'),('FIXED_OPS','1'),('GUARD_US','25'),('DEADLINE_US','50'))):
        raise RuntimeError('Protected compact/guardian identity absent')
    if any(row['zero'].get(k)!=v for k,v in (('STATE','3'),('REASON','0'),('N','4000'))):
        raise RuntimeError('Normal bounded zero calibration not ready')
    b=row['buffer']
    if b.get('STK_VALID')!='1' or int(b.get('FREE_B','0'))<256 or int(b.get('DONE','0'))<1:
        raise RuntimeError('Background worker/stack evidence absent')
    if row['fault'].get('VALID')!='0' or fields(row['status']).get('FLT')!='0':
        raise RuntimeError('Motor or feedback fault; no retry')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',type=Path,required=True)
    p.add_argument('--allow-trial-and-single-short-speed',action='store_true')
    p.add_argument('--drive-12v-on-no-alarm-motor-fixed',action='store_true')
    args=p.parse_args()
    if not(args.allow_trial_and_single_short_speed and args.drive_12v_on_no_alarm_motor_fixed):
        p.error('Single short trial and actual powered/fixed motor state required')
    data,before,staged=stage_evidence(args.stage)
    run=str(time.time_ns()); out=profile.OUTPUT/f'compact-motor-trial-{run}.json'
    row=dict(pass_=False,image_sha256=profile.SHA,stage=str(args.stage.resolve()),
        target_slot='A',fallback_slot='B',steps=[],samples=[],force_confirmation=False,
        automatic_host_retry=False,fault_clearing=False,industrial_speed_qualified=False,
        torque_accuracy_verified=False,speed_accuracy_verified=False)
    board=profile.Board(row,run); uart=port=None; activated=False
    try:
        if board.capture('before_trial')!=staged: raise RuntimeError('Flash changed since exact staging')
        row['before_outputs']=board.outputs('B',False)
        port=profile.open_port(); uart=MotorConsole(port)
        fw=uart.query('FW STATUS')
        require_staged(fw,'0 OK SAFE SOURCE=SWD SD=0 MOE=0 CEN=0',data)
        if fields(fw).get('GEN')!=str(profile.GENERATION): raise RuntimeError('Not exact B533 requester')
        activated=True
        try: row['commit_ack']=uart.query('FW END',5)
        except TimeoutError: row['commit_ack_uncertain']=True
        end=time.monotonic()+90; saw_a=False
        while time.monotonic()<end:
            try: fw=uart.query('FW STATUS',.5)
            except TimeoutError: continue  # Normal boot/confirmation reset only.
            f=fields(fw)
            if f.get('CURRENT')=='A':
                saw_a=True
                try: state=fields(uart.query('MOTOR TEST STATUS',.5))
                except TimeoutError: continue
                if state.get('STATE')=='4':
                    row['startup_sample']=sample(uart)
                    raise RuntimeError('Startup fault; no motor command or automatic retry')
            if saw_a and f.get('CURRENT')=='B' and f.get('PENDING')=='-':
                raise RuntimeError('Automatic rollback; no motor command')
            if (f.get('CURRENT')=='A' and f.get('CONFIRMED')=='A' and
                f.get('PENDING')=='-' and f.get('ACTIVE')=='0'):
                row['confirmed']=require_confirmed(fw,'A'); break
            uart.poll(.05)
        else: raise TimeoutError('Normal A health confirmation absent; no forced confirmation')
        row['protected_regions']=compare_flash(before,board.capture('confirmed'),data,'A')
        row['before_start_outputs']=board.outputs('A',True)
        row['before_start']=sample(uart); validate(row['before_start'],ready=True)
        print('READY PASS: exact confirmed A, zero/encoder/50us gates; ONE 20 rpm / 400 ms command',flush=True)
        row['start_ack']=uart.query('MOTOR TEST SPEED')
        if 'QUEUED=1 RPM=20 MAX_US=400000' not in row['start_ack']:
            raise RuntimeError('No bounded local motion admission')
        end=time.monotonic()+1.0
        while time.monotonic()<end:
            state=fields(uart.query('MOTOR TEST STATUS'))
            row['samples'].append(dict(host_time=time.monotonic(),state=state,status=uart.query('STATUS')))
            if state.get('STATE') in ('3','4'): break
            uart.poll(.01)
        row['observed_terminal_state']=state
        # Explicit STOP before potentially slower multi-line diagnostics.
        row['stop_ack']=uart.query('MOTOR TEST STOP')
        row['after_stop']=sample(uart); validate(row['after_stop'])
        s=row['after_stop']['state']
        if (state.get('STATE')!='3' or state.get('USED')!='1' or state.get('QUEUED')!='0' or
            not 400000<=int(state.get('US','0'))<=400100 or
            s.get('STATE')!='3' or s.get('USED')!='1' or s.get('QUEUED')!='0' or
            not 400000<=int(s.get('US','0'))<=400100):
            raise RuntimeError('Automatic bounded lease completion not proved')
        row['bounded_trial_completed_without_fault']=True
        row['pass_']=True
    except BaseException as error:
        row['failure']=str(error); raise
    finally:
        if uart and activated:
            try:
                row['final_fw']=f=fields(uart.query('FW STATUS'))
                if f.get('CURRENT')=='A':
                    row['final_stop_ack']=uart.query('MOTOR TEST STOP')
                    row['final_state']=fields(uart.query('MOTOR TEST STATUS'))
                    row['final_fault']=fields(uart.query('MOTOR TEST FAULT'))
                row['maintenance_off']=uart.query('ANALOG SAFE')
                row['final_safe']=s=fields(uart.query('ANALOG SAFE STATUS'))
                if any(s.get(k)!=v for k,v in (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
                    raise RuntimeError('Final maintenance output lock absent')
                slot=f.get('CURRENT')
                if slot not in ('A','B'): raise RuntimeError('Unknown final slot')
                row['final_outputs']=board.outputs(slot,False)
                raw=board.capture('final')
                if row.get('confirmed'): compare_flash(before,raw,data,'A')
                else:
                    if raw[:0x8000]!=staged[:0x8000] or raw[0x40000:0x7E800]!=staged[0x40000:0x7E800] or raw[0x7F800:]!=staged[0x7F800:]:
                        raise RuntimeError('Fallback/private data changed')
                row['final_outputs_off']=True
            except BaseException as error:
                row['pass_']=False; row['cleanup_failure']=str(error)
                print('STOP/READBACK NOT PROVED: switch off drive 12 V now; no retries',flush=True)
        if uart:
            row['uart']=uart.lines; row['host_trial_commits']=uart.ends; row['host_motor_commands']=uart.starts
        if port: port.close()
        out.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(('SHORT TRIAL PASS' if row['pass_'] else 'SHORT TRIAL FAIL')+': no industrial speed/torque claim',flush=True)
        print('Evidence: '+str(out),flush=True)

if __name__=='__main__': main()
