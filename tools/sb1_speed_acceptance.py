"""Exact zero-admission/SB1 A: offline default, OFF inspection, one 2s SPEED run.

No programming, fault clear, gain/threshold/lease edits, persistent SAVE, or
second START. The original tightening START path owns SPEED admission.
"""
import argparse
import json
import math
import os
import re
from pathlib import Path
import struct
import time
import zlib

import zero_valid_admission_board_test as zero
from firmware_transfer_iap import fields
from health_confirmation_wait import wait_health_confirmation
from latest_original_fsm_stage import full_compare_commands,off_commands,write_mailbox
from original_closed_loop_updated_stage import debug,check_off,off_report
from original_closed_loop_trial import emergency_off
from protected_irq_optimized_stage import open_port
from pipeline_closed_loop_trial import Console
from loaded_fsm_motion import RecordedBoard,check_profile,RECIPE_NAMES,check_recipe
from motor_motion_smoke import require_idle_ready,stop
from loaded_fsm_snapshot_report import decode

ROOT=zero.ROOT; TMP=zero.TMP
BASE=TMP/'sb1-speed-speed-1792310000692732600-flash.bin'
BASE_SHA='b8750adcf441b93a3ccd37fedc8550bc99688586b9320301620cd489cf4b0cb3'
BASE_META=(1,0,0,648)
ELF=zero.IMAGE.with_suffix('.elf')
ELF_SHA='ba3bcde75abfbdc73b6184368e6f860be91c7024877155f479a91597df28f889'
HOST_SECONDS=2.0


def checkpoint(row,phase):
    """Host evidence only. Atomic durable phase receipt BEFORE hazardous work.

    No claim that a host journal substitutes for the independent board lease.
    A START_ATTEMPT with no ACK is unknown, never an authorization to retry.
    """
    path=row.get('receipt_path')
    if path is None: return  # Pure motion-kernel mocks do not create files.
    row['phase']=phase
    row['checkpoint_host_ns']=time.time_ns()
    path=Path(path); temporary=path.with_suffix('.json.partial')
    with temporary.open('w',encoding='utf-8') as file:
        json.dump(row,file,indent=2); file.write('\n'); file.flush(); os.fsync(file.fileno())
    os.replace(temporary,path)


class JournalConsole(Console):
    def __init__(self,port,row):
        super().__init__(port); self.row=row; row['startup_uart']=self.lines

    def dispatch(self,line):
        super().dispatch(line)
        checkpoint(self.row,'startup_read')


def baseline():
    image=zero.image(); raw=BASE.read_bytes()
    if (zero.digest(raw)!=BASE_SHA or len(raw)!=0x80000 or
            zero.latest_meta(raw)[2:6]!=BASE_META or
            raw[0x8000:0x8000+len(image)]!=image or zero.digest(ELF.read_bytes())!=ELF_SHA):
        raise ValueError('Exact halted A648 and preserved B required')
    return image,raw


def inspect(row,name):
    baseline()
    row['hardware_attempted']=True
    output=debug(row,[*zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08008000} {error "Expected halted A"}',
        *full_compare_commands(TMP/(name+'-flash.bin'),BASE),*off_report(),'shutdown'])
    row.update(outputs=check_off(output,(0x08008000,)),baseline_sha256=BASE_SHA,
        image_sha256=zero.SHA,elf_sha256=ELF_SHA,no_reset=True,no_programming=True,pass_=True)


def load_inspection(path):
    r=json.loads(path.read_text('utf-8'))
    if (path.resolve().parent!=TMP.resolve() or r.get('mode')!='inspect' or
            r.get('pass_') is not True or r.get('baseline_sha256')!=BASE_SHA or
            r.get('image_sha256')!=zero.SHA or r.get('elf_sha256')!=ELF_SHA or
            not r.get('physical_power_off') or not r.get('motor_connected_fixed')):
        raise ValueError('Exact successful OFF inspection required')


def speed_summary(samples):
    def rpm(row):
        value=float(row['status']['CTRL'].removesuffix('rpm'))
        if not math.isfinite(value): raise ValueError('Nonfinite speed telemetry')
        return value
    values=[rpm(s) for s in samples]
    tail=[rpm(s) for s in samples if s['elapsed_s']>=1.5]
    if len(values)<15 or len(tail)<5:
        raise ValueError('Insufficient full-duration speed feedback')
    peak=max(values); error=max(abs(v-20.0) for v in tail)
    return dict(target_rpm=20,peak_filtered_rpm=peak,minimum_filtered_rpm=min(values),
        overshoot_percent=max(0.0,(peak-20)/20*100),tail_mean_filtered_rpm=sum(tail)/len(tail),
        tail_max_error_rpm=error,tracking_pass=error<=5.0,
        provisional_error_band_rpm=5.0,independent_tachometer_verified=False)


def wait_timing(uart,row,timeout=8.0):
    """MonitorTask emits every FIVE seconds, not every poll/ADC sample.

    All four mandatory counters must appear in this boot's UART capture. Do
    not substitute an earlier image's timing, zero-filled RAM or a guess.
    """
    deadline=time.monotonic()+timeout
    next_status=time.monotonic()
    keys=('wall_max_us','deadline_miss','actual_late_commit_count','actual_margin_min_us')
    while True:
        now=time.monotonic()
        if now>=deadline: raise TimeoutError('Mandatory 5s MonitorTask timing absent within 8s; no START')
        uart.poll(min(.05,deadline-now))
        if time.monotonic()>=next_status:
            state=fields(uart.query('MOTOR TEST STATUS',.6))
            if any(state.get(k)!=v for k,v in dict(STATE='1',USED='0',FAULT='0',FLAGS='0',SD='0',MOE='0',CCER='0').items()):
                raise RuntimeError('READY/output-off state lost while waiting for timing; no START')
            next_status=time.monotonic()+.5
        text='\n'.join(uart.lines)
        found={key:re.findall(r'\b'+key+r'=([+-]?[0-9.]+)',text) for key in keys}
        if not all(found.values()): continue
        values={key:float(found[key][-1]) for key in keys}
        row['preflight_timing']=values
        if (not all(math.isfinite(v) for v in values.values()) or
                not 0<values['wall_max_us']<50 or values['deadline_miss'] or
                values['actual_late_commit_count'] or values['actual_margin_min_us']<=1):
            raise RuntimeError('Timing preflight failed; no START')
        return values


def motion(board,record,expected_speed_ctrl='SB1'):
    original_rpm=None; changed=started=False
    try:
        require_idle_ready(board,'A')
        check_profile(fields(board.command('MOTOR TEST PROFILE')),expected_speed_ctrl)
        s=fields(board.command('MOTOR TEST STATUS'))
        wanted=dict(STATE='1',USED='0',ZERO='3',FAULT='0',FLAGS='0',SD='0',MOE='0',CCER='0')
        if any(s.get(k)!=v for k,v in wanted.items()):
            raise RuntimeError('Exact unused/calibrated/output-off readiness required')
        recipe={key:int(fields(board.command('GET '+key))[key]) for key in RECIPE_NAMES}
        check_recipe(recipe)
        if recipe['RUNDOWN_TIMEOUT_MS']<2500 or recipe['MAX_TRAVEL_DEG']<300:
            raise RuntimeError('Existing recipe cannot contain this 2s test; not widening it')
        record['original_recipe']=recipe
        original_rpm=recipe['RUNDOWN_RPM']; changed=True
        board.command('SET RUNDOWN_RPM 20')
        if fields(board.command('GET RUNDOWN_RPM')).get('RUNDOWN_RPM')!='20':
            raise RuntimeError('20 rpm readback failed')
        require_idle_ready(board,'A')
        started=True; record['start_attempts']=1
        checkpoint(record,'START_ATTEMPT')  # Durable before a possibly ambiguous write.
        start_id=board.send('START'); start=time.monotonic(); end=start+HOST_SECONDS
        record['start_request_id']=start_id
        checkpoint(record,'START_SENT')
        next_status=start+.05; pending=None; sent=0; ack=False
        while time.monotonic()<end:
            now=time.monotonic()
            if pending is None and now>=next_status:
                pending=board.send('STATUS'); sent=now; next_status=now+.05
            if pending is not None and now-sent>.3:
                raise TimeoutError('Motion feedback absent for 300ms')
            line=board.read_line(min(.01,max(0,end-time.monotonic())))
            if line is None: continue
            if line.startswith(str(start_id)+' '):
                if not line.startswith(str(start_id)+' OK '): raise RuntimeError('START refused')
                ack=True; record['start_ack']=line
                checkpoint(record,'START_ACK'); print(line,flush=True)
            elif pending is not None and line.startswith(str(pending)+' '):
                pending=None; s=fields(line); elapsed=time.monotonic()-start
                record['samples'].append(dict(elapsed_s=elapsed,status=s))
                checkpoint(record,'motion_feedback')
                print('T=%.3f %s'%(elapsed,line),flush=True)
                if s.get('FLT')!='0': raise RuntimeError('Protection fault during speed test; no retry')
                if s.get('BUSY')!='1' or s.get('STAGE')!='1' or s.get('MODE')!='SPD':
                    raise RuntimeError('Left no-load SPEED rundown; no full-cycle assertion')
            if not ack and time.monotonic()-start>.3:
                raise TimeoutError('START ACK absent; no retry')
        checkpoint(record,'STOP_ATTEMPT')
        stop(board); record['host_stop_elapsed_s']=time.monotonic()-start
        checkpoint(record,'STOP_ACK')
        if not ack: raise RuntimeError('No START acknowledgement')
        # Observe STOP briefly before latching. No new motor command is issued.
        stop_end=time.monotonic()+.5; stopped=False
        while time.monotonic()<stop_end:
            s=fields(board.command('STATUS',.3))
            record.setdefault('stop_samples',[]).append(s)
            if s.get('FLT')!='0': raise RuntimeError('Fault during STOP')
            if (s.get('MODE')=='IDLE' and s.get('BUSY')=='0' and
                    abs(float(s['CTRL'].removesuffix('rpm')))<2):
                stopped=True; break
        record['stop_feedback_pass']=stopped
        record['speed_summary']=speed_summary(record['samples'])
        if not stopped: raise RuntimeError('STOP did not reach encoder-reported <2rpm within 0.5s')
        if not record['speed_summary']['tracking_pass']:
            raise RuntimeError('Last 0.5s not within provisional 20 +/-5rpm band')
        record['motion_pass']=True
    finally:
        if started:
            try: stop(board)
            except Exception as error: record['stop_error']=str(error)
        record['off_ack']=board.command('ANALOG SAFE',.8)
        record['safe']=fields(board.command('ANALOG SAFE STATUS',.8))
        checkpoint(record,'output_off_readback')
        if any(record['safe'].get(k)!=v for k,v in dict(LATCHED='1',SD='0',MOE='0',FOC='0').items()):
            raise RuntimeError('Software output-off latch not verified')
        if changed:
            board.command('SET RUNDOWN_RPM '+str(original_rpm))
            if fields(board.command('GET RUNDOWN_RPM')).get('RUNDOWN_RPM')!=str(original_rpm):
                raise RuntimeError('Temporary recipe rpm restore failed')
            record['recipe_restored']=True
        for cmd in ('MOTOR TEST FAULT','MOTOR TEST TIMING','STATUS'):
            record['postflight'][cmd]=board.command(cmd)


def execute(row,name,path):
    load_inspection(path); data,before=baseline()
    port=open_port(); uart=JournalConsole(port,row)
    try:
        row['hardware_attempted']=True
        checkpoint(row,'trial_request_intent')
        body=struct.pack('<7I',0x584f424d,1,2,2,1,len(data),zlib.crc32(data))
        mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
        # This exact A648 already passed normal bootloader health confirmation.
        # Reset that confirmed A only; no new trial or boot-selection mutation.
        request=write_mailbox(mailbox) if BASE_META[0]==2 else []
        debug(row,[*zero.off_gate(),*full_compare_commands(TMP/(name+'-before.bin'),BASE),
            'reset halt',*off_commands(),*request,'reset run','shutdown'])
        row['trial_requests']=int(bool(request)); row['reset_attempts']=1
        checkpoint(row,'trial_request_submitted')
        wait_health_confirmation(uart,row,fields)
        checkpoint(row,'health_confirmed')
        row['preflight_zero']=zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        check_profile(fields(uart.query('MOTOR TEST PROFILE')),'SB1')
        wait_timing(uart,row)
        checkpoint(row,'preflight_pass')
        row['startup_uart']=uart.lines; port.close()
        board=RecordedBoard('COM5',row)
        try: motion(board,row)
        finally: board.close()
    finally:
        if port.is_open: port.close()
        row.setdefault('startup_uart',uart.lines)
        if row.get('hardware_attempted'):
            flash=TMP/(name+'-flash.bin'); ram=TMP/(name+'-ram.bin')
            emergency_off(row,flash)
            checkpoint(row,'halted_outputs_off')
            output=debug(row,['init','halt',*zero.off_gate()[1:],*off_report(),
                f'dump_image {{{ram.as_posix()}}} 0x20000000 0x20000','shutdown'])
            row['outputs']=check_off(output,(0x08008000,))
            actual=flash.read_bytes()
            if actual[:0x7e800]!=before[:0x7e800] or actual[0x7f800:]!=before[0x7f800:]:
                raise RuntimeError('Application/private region changed')
            row.update(final_capture=str(flash),final_sha256=zero.digest(actual),
                final_metadata=list(zero.latest_meta(actual)),ram_capture=str(ram),
                all_app_private_unchanged=True,snapshot=decode(ram.read_bytes(),ELF))
            checkpoint(row,'snapshot_saved')
    if (row['snapshot']['first_fault']['valid'] or row['snapshot']['timing']['deadline_miss'] or
            row['snapshot']['timing']['actual_late_count']):
        raise RuntimeError('Postflight protection/timing failure')
    row['pass_']=bool(row.get('motion_pass'))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    m=p.add_mutually_exclusive_group()
    m.add_argument('--inspect-off',action='store_true')
    m.add_argument('--execute-powered',type=Path)
    p.add_argument('--drive-off-motor-connected-fixed',action='store_true')
    p.add_argument('--drive-on-no-alarm-fixed-05a-emergency-off-ready',action='store_true')
    a=p.parse_args()
    if a.inspect_off and not a.drive_off_motor_connected_fixed: p.error('Actual drive OFF; connected fixed no-load motor required')
    if a.execute_powered and not a.drive_on_no_alarm_fixed_05a_emergency_off_ready: p.error('Actual powered/no-alarm fixed no-load motor and 0.5A limit required')
    if not(a.inspect_off or a.execute_powered):
        zero.image(); print('OFFLINE PASS: no devices or motion'); return 0
    mode='inspect' if a.inspect_off else 'speed'
    name='sb1-speed-'+mode+'-'+str(time.time_ns())
    path=TMP/(name+'.json')
    row=dict(mode=mode,pass_=False,image_sha256=zero.SHA,elf_sha256=ELF_SHA,steps=[],
        commands=[],uart=[],samples=[],postflight={},automatic_retry=False,
        start_attempts=0,flash_programming=False,protection_edits=False,
        motor_connected_fixed=True,physical_power_off=bool(a.inspect_off),
        torque_accuracy_verified=False,host_limit_seconds=HOST_SECONDS,
        receipt_path=str(path))
    checkpoint(row,'prepared_no_start')
    try:
        if a.inspect_off: inspect(row,name)
        else: execute(row,name,a.execute_powered)
    except Exception as error:
        row.update(pass_=False,failure=str(error))
        checkpoint(row,'failed')
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try: emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as cleanup: row['cleanup_error']=str(cleanup)
    checkpoint(row,'complete' if row['pass_'] else 'failed_halted' if row.get('final_cpu_halted') else 'failed')
    print(('PASS: ' if row['pass_'] else 'FAIL: ')+str(path),flush=True)
    if row.get('failure'): print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__': raise SystemExit(main())
