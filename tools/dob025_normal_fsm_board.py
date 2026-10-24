"""One supervised normal START/brake-load FSM trial. Files-only default.

No brake actuator API, forced CONTACT, parameter changes or automatic retry.
Separate fresh drive-OFF stage, powered confirmation and drive-OFF B restore.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import struct
import time
import dob_feedback_gain015_board as prior
import friction_fsm_board as base
from motor_motion_smoke import require_idle_ready,stop
from loaded_fsm_motion import RECIPE_NAMES,check_recipe

TMP=base.TMP
ROOT_RESTORE=TMP/'mechanical-ident-restore-1792739878657774600.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/TighteningDob025/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='0a2fe20161d8fb77a494fe7cd1dcec23126f52e3f8534fbcd7ae6ac5d6afc3a5'
ELF_SHA='53642f7a942df34ecb6df41efac7324f22f9534b360c3c0a59df2c500a0adaa7'
SIZE=223880
ORIGINAL_STAGED=base.staged
ORIGINAL_DECODE=base.decode_cm
ORIGINAL_EXECUTE=base.execute
NORMAL_BOARD=base.TokenRecordedBoard
NORMAL_CONSOLE=base.TokenConsole
FB_CONFIG=dict(prior.FB_CONFIG,ON='1',GAIN_PPM='250000')
check_values=prior.fb.shadow.check_values

def status_fields(line):
    values=base.hw.fields(line)
    # Legacy fields() intentionally accepts uppercase protocol keys only.
    # Keep the actual mixed-case IqRef field without changing old parsers.
    match=re.search(r'\bIqRef=([-+]?\d+)mA\b',line)
    if match:values['IqRef']=match.group(1)+'mA'
    return values

def image():
    data=IMAGE.read_bytes()
    command=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text())
                 if c['file'].endswith('/Core/Src/main.c'))
    required=('FOC_DOB_NORMAL_CONTROL=1','FOC_DOB_FEEDBACK_CANDIDATE=1','DOB_FB_GAIN=0.25f',
        'FOC_MECHANICAL_DOB_SHADOW=1','FOC_DOB_ID_PRE_LPF_QUALITY=1','DOB_ADMIT_JUMP_A=.200f',
        'FOC_OUTER_OBSERVE_AFTER_ACK=1','FOC_READY_TIMESTAMP_SNAPSHOT=1',
        'FOC_ENCODER_CONTROL_ADMISSION_FIX=1','FOC_INTENT_FSM_CANDIDATE=1',
        'FOC_PROTECTED_CLOSED_LOOP=1','FOC_ONE_CYCLE_PWM_PIPELINE=1','FOC_PWM_PIPELINE_CLOSED_LOOP=1',
        'FOC_BEMF_ENABLED_DEFAULT=1','FOC_BEMF_PSI_WB=0.00034866f',
        'FOC_CURRENT_PI_IDENTIFIED_ENABLE=1','FOC_SPEED_PI_ANTI_WINDUP=1',
        'FOC_FRICTION_ENABLED_DEFAULT=1','SPEED_FRICTION_I_A=0.105f',
        'SPEED_ACCEL_FF_KA_A_PER_RPM_S=0.000046875f','AS5047P_DMA_FOC_FIRST=1')
    forbidden=('FOC_MECHANICAL_MOTION_DIAG','FOC_MECHANICAL_HIGH_SPEED_DIAG',
        'FOC_FRICTION_CALIBRATION_DIAG','FOC_DOB_ID_TRACE','FOC_CURRENT_STEP_AB_DIAG',
        'FOC_TORQUE_CHAIN_DIAG','FOC_FAST_REJECT_COMPUTE_ONLY','FOC_DQ_DECOUPLING_CANDIDATE')
    if (len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or
        hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        any('-D'+f+' ' not in command for f in required) or any('-D'+f+'=' in command for f in forbidden)):
        raise ValueError('Exact normal START DOB0.25 image/ELF/flags required')
    for marker in (b'INTENT_FSM_CANDIDATE; manual START only',b'RPM=240 LEASE_US=12000000',
        b'TRIP_MA=4000',b'METHOD=TWO_SAMPLE',b'RUNDOWN240: RAM=240rpm TRIP=300rpm SAVE=OFF',
        b'TRAVEL=20000deg RAM only',b'OK DOBFB ON=%lu GAIN_PPM=%lu',b'FSM_STATE='):
        if marker not in data:raise ValueError('Normal FSM/protection marker absent')
    syms=base.symbols(ELF)
    for name,size in dict(dob_feedback=80,mechanical_dob_monitor=856,dob_current_admission=204,
                          outer_completion_trace=644).items():
        if syms.get(name,(0,0))[1]!=size:raise ValueError('Normal DOB ABI '+name)
    base.support.support.require_baud(command)
    return data

def configure(path):
    # Verify actual gain0.15/B1103 receipt with its original immutable identity.
    prior.setup(ROOT_RESTORE);base.baseline()
    base.IMAGE,base.ELF,base.SHA,base.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    base.image=image;base.FRICTION_A=.105;base.staged=ORIGINAL_STAGED
    base.decode_cm=decode;base.motion=motion
    base.TokenRecordedBoard=NORMAL_BOARD;base.TokenConsole=NORMAL_CONSOLE
    if path.resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(path)
    return image()

def model_checks(board,row):
    row['dob_feedback_initial']=check_values(board.command('MOTOR TEST MECH DOB FB CFG'),FB_CONFIG,'Normal DOB gain/default')
    requested=row.get('dob_feedback_requested',True);flag=str(int(requested))
    if not requested:
        row['dob_feedback_switch']=check_values(board.command('MOTOR TEST MECH DOB FB OFF'),
            dict(FB_CONFIG,ON='0'),'Guarded idle DOB OFF')
    row['dob_feedback_config']=check_values(board.command('MOTOR TEST MECH DOB FB CFG'),
        dict(FB_CONFIG,ON=flag),'Selected DOB feedback mode')
    row['ff_before_start']=check_values(board.command('MOTOR TEST FF STATUS'),
        dict(ON='1',KA_NA_PER_RPM_S='46875',ACCEL_MAX_RPM_S='200',FF_PEAK_UA='9375',TOKENIZED='1'),'Fixed Ka')
    row['fric_before_start']=check_values(board.command('MOTOR TEST FRIC STATUS'),
        dict(ON='1',I_UA='105000',DB_MRPM='2000',FF_ON='1',KA_NA_PER_RPM_S='46875',TOKENIZED='1'),'Fixed friction')
    row['bemf_before_start']=check_values(board.command('MOTOR TEST BEMF STATUS'),
        dict(ON='1',CONFIGURED='1',PSI_NWB='348660',DQ_CROSS='0'),'Fixed BEMF')
    row['dob_model']=check_values(board.command('MOTOR TEST MECH DOB MODEL'),
        dict(prior.fb.shadow.MODEL,FEEDBACK=flag),'Unchanged normalized model')
    row['dob_rest']=check_values(board.command('MOTOR TEST MECH DOB'),
        dict(FEEDBACK=flag,LIVE='0',VALID='0'),'No pre-start estimate')
    row['dob_rest_feedback']=check_values(board.command('MOTOR TEST MECH DOB FB STATUS'),
        dict(ON=flag,COMP_UA='0'),'No pre-start compensation')
    row['admission_config']=check_values(board.command('MOTOR TEST MECH DOB ADMIT CFG'),
        dict(V='5',MODE='PREFILTER',JUMP_UA='200000',CONFIRM='3',ID_MAX_UA='60000',
             ID_US='20000',GAP_US='10000',LATCH='0',FEEDBACK=flag),'Original DOB quality')

def motion(board,row):
    if not row.get('guarded_brake_confirmed') or not row.get('powered_no_alarm'):
        raise ValueError('Fresh guarded independently operated brake and powered confirmation required')
    started=False
    try:
        require_idle_ready(board,'A')
        row['profile_before_start']=base.profile(board.command('MOTOR TEST PROFILE'))
        row['filter_before_start']=base.filter_profile(board.command('MOTOR TEST FILTER'))
        model_checks(board,row)
        row['ready_before_start']=check_values(board.command('MOTOR TEST STATUS'),
            dict(STATE='1',USED='0',ZERO='3',FAULT='0',FLAGS='0',SD='0',MOE='0',CCER='0'),'Unused ready')
        row['adc_preflight']=check_values(board.command('ADC TIMING'),dict(MISS='0',PF='0',DWT='1'),'ADC preflight')
        stack=base.motor_stack(board);row['motor_stack_preflight']=stack
        if stack.get('VALID')!='1' or int(stack.get('FREE_B','0'))<256:
            raise RuntimeError('Insufficient motor-task stack; no START')
        recipe={key:int(base.hw.fields(board.command('GET '+key))[key]) for key in RECIPE_NAMES}
        check_recipe(recipe);row['effective_ram_recipe']=recipe
        if recipe['RUNDOWN_RPM']!=240 or recipe['MAX_TRAVEL_DEG']!=20000 or recipe['RUNDOWN_TIMEOUT_MS']!=8000:
            raise RuntimeError('Original normal recipe/limits required')
        require_idle_ready(board,'A')
        if row.get('start_attempts'):raise RuntimeError('No second START')
        row['preflight_pass']=True;started=True;row['start_attempts']=1
        base.old.prior.checkpoint(row,'START_ATTEMPT')
        request=board.send('START');start=time.monotonic();end=start+base.HOST_MAX_SECONDS
        row['start_request_id']=request;row['start_host_monotonic']=start
        base.old.prior.checkpoint(row,'START_SENT')
        next_status=start+.05;next_dob=start+.15;pending=None;sent=0;ack=False;probe=0
        queries=('MOTOR TEST MECH DOB','MOTOR TEST MECH DOB FB STATUS','MOTOR TEST MECH DOB FB SUM',
                 'MOTOR TEST MECH DOB FB STATS')
        while time.monotonic()<end:
            now=time.monotonic()
            if pending is None:
                # STATUS and ONE DOB query interleave; never block the stop loop
                # waiting for a multi-command burst. Source timestamps retained.
                command=None
                if now>=next_status:command='STATUS';next_status=now+.05
                elif now>=next_dob:command=queries[probe%len(queries)];probe+=1;next_dob=now+.08
                if command:pending=(board.send(command),command);sent=now
            if pending is not None and now-sent>.3:raise TimeoutError('Feedback absent300ms; no retry')
            line=board.read_line(min(.01,max(0,end-time.monotonic())))
            if line is None:continue
            if line.startswith(str(request)+' '):
                if not line.startswith(str(request)+' OK '):raise RuntimeError('START refused')
                ack=True;row['start_ack']=line;print(line,flush=True)
            elif pending is not None and line.startswith(str(pending[0])+' '):
                req,command=pending;pending=None
                if ' OK ' not in line:raise RuntimeError('Invalid runtime reply')
                values=status_fields(line);elapsed=time.monotonic()-start
                if command=='STATUS':
                    if ' OK STATUS ' not in line:raise RuntimeError('Invalid motion status')
                    row['samples'].append(dict(elapsed_s=elapsed,request_id=req,status=values,raw_reply=line))
                    print('T=%.3f %s'%(elapsed,line),flush=True)
                    if values.get('FLT')!='0':raise RuntimeError('Protection fault; no retry')
                    if values.get('CONTACT')=='1':row['contact_observed']=True
                    if elapsed>.2 and values.get('BUSY')=='0':
                        row['terminal_status']=values;row['terminal_status_request']=str(req)
                        row['fsm_terminal_seen']=True;break
                else:
                    flag=str(int(row.get('dob_feedback_requested',True)))
                    if command=='MOTOR TEST MECH DOB':
                        if values.get('FEEDBACK')!=flag:raise RuntimeError('Observer feedback mode changed; no retry')
                    elif values.get('ON')!=flag:
                        raise RuntimeError('Runtime DOB mode changed; no retry')
                    if flag=='0' and command=='MOTOR TEST MECH DOB FB STATUS' and values.get('COMP_UA')!='0':
                        raise RuntimeError('OFF compensation nonzero; no retry')
                    row.setdefault('dob_samples',[]).append(dict(elapsed_s=elapsed,command=command,reply=line,values=values))
                base.old.prior.checkpoint(row,'motion_feedback')
            if not ack and time.monotonic()-start>.3:raise TimeoutError('Unknown START result; no retry')
        stop(board);row['host_stop_elapsed_s']=time.monotonic()-start
        if not ack or not row.get('fsm_terminal_seen'):raise TimeoutError('No natural FSM terminal before bounded STOP')
        row['fsm_observation_complete']=True
    finally:
        if started:
            try:stop(board)
            except Exception as error:row['stop_error']=str(error)
        row['off_ack']=board.command('ANALOG SAFE',.8)
        row['safe']=check_values(board.command('ANALOG SAFE STATUS',.8),
            dict(LATCHED='1',SD='0',MOE='0',FOC='0'),'Output-off latch')
        for command in ('MOTOR TEST FAULT','MOTOR TEST TIMING','STATUS','MOTOR TEST MECH DOB FB STATS',
                        'MOTOR TEST MECH DOB FB STATUS'):
            row['postflight'][command]=board.command(command)
        # Drain supplemental FSM lines from the final STATUS before RAM capture.
        until=time.monotonic()+.12
        while time.monotonic()<until:board.read_line(.01)

def decode(row):
    ORIGINAL_DECODE(row)
    ram=Path(row['ram_capture']).read_bytes();syms=base.symbols(ELF)
    row['ram_sha256']=hashlib.sha256(ram).hexdigest()
    address,size=syms['dob_feedback'];offset=address-0x20000000
    if size!=80 or not 0<=offset<=len(ram)-size:raise ValueError('Feedback RAM bounds')
    row['feedback_capture']=prior.fb.decode_feedback(ram[offset:offset+size])
    row['capture_semantics']='Sparse timestamped normal STATUS/DOB replies, not synchronized full-rate load-step telemetry'

def classify(row):
    snap=row.get('snapshot',{});timing=snap.get('timing',{});fault=snap.get('first_fault',{})
    terminal=row.get('terminal_status',{});off=row.get('outputs',{})
    independent=base.hw.fields(row.get('postflight',{}).get('MOTOR TEST FAULT',''))
    requested=row.get('dob_feedback_requested',True)
    feedback=row.get('feedback_capture',{})
    if (feedback.get('enabled')!=int(requested) or
        (not requested and (feedback.get('peak_a')!=0 or feedback.get('iq_comp_a')!=0))):
        raise RuntimeError('Saved DOB selection/zero-OFF evidence failed')
    expected_process=(fault.get('domain')==3 and fault.get('protection_flags')==0 and terminal.get('OUTCOME')!='OK')
    if (not row.get('preflight_pass') or row.get('start_attempts')!=1 or
        not row.get('fsm_observation_complete') or not row.get('final_cpu_halted') or
        not row.get('final_outputs_off') or not row.get('all_app_private_unchanged') or
        off.get('VTOR')!=0x08008000 or off.get('SD',64)&64 or off.get('BDTR',0xc000)&0xc000 or off.get('CCER',1) or
        terminal.get('FLT')!='0' or independent.get('VALID')!='0' or independent.get('FLAGS')!='0' or
        (fault.get('valid') and not expected_process) or snap.get('cur_confirm',{}).get('fault') or
        timing.get('deadline_miss')!=0 or timing.get('actual_late_count')!=0 or
        not 0<timing.get('wall_max_us',0)<50 or timing.get('actual_margin_min_us',0)<=1 or
        any(row.get(k) for k in ('stop_error','token_decode_errors'))):
        raise RuntimeError('Protection/timing/closure/FSM observation failed; no retry')
    result=dict(acquisition_complete=True,outcome=terminal.get('OUTCOME'),
        tightening_ok=False,torque_accuracy_verified=False,load_rejection_verified=False,
        automatic_retry=False,feedback_peak_a=row['feedback_capture']['peak_a'])
    if terminal.get('OUTCOME')=='OK':
        req=str(row['start_request_id'])
        lines=[r.get('line','') for r in row.get('uart',[])]
        starts=[i for i,line in enumerate(lines) if line.startswith('EVT REQ='+req+' STARTED ')]
        ends=[i for i,line in enumerate(lines) if line=='EVT REQ='+req+' COMPLETE RESULT=OK']
        if len(starts)!=1 or len(ends)!=1 or starts[0]>=ends[0]:raise RuntimeError('Current START ordered OK evidence absent')
        # The compiled FSM itself requires armed/contact/tightening/no-fault.
        # Retain request-associated state events as corroboration, not fake
        # intermediate states that sparse UART may legitimately miss.
        result['tightening_ok']=True
    result['dob_feedback_requested']=requested
    result['note']='One brake-loaded normal FSM; no synchronized brake torque/timestamps; earlier ON/OFF is an uncontrolled historical comparison.'
    return result

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);group=parser.add_mutually_exclusive_group()
    group.add_argument('--stage-off',action='store_true');group.add_argument('--execute-powered',type=Path)
    group.add_argument('--restore-b-drive-off',type=Path)
    parser.add_argument('--baseline-restore',type=Path)
    parser.add_argument('--dob-off',action='store_true',help='Same firmware; guarded idle-only RAM feedback OFF')
    parser.add_argument('--drive-off-brake-released-fixed-guarded',action='store_true')
    parser.add_argument('--operator-present-drive-on-no-alarm-05a',action='store_true')
    parser.add_argument('--guarded-independent-light-brake',action='store_true');args=parser.parse_args(argv)
    if (args.stage_off or args.restore_b_drive_off) and not args.drive_off_brake_released_fixed_guarded:
        parser.error('Fresh physical drive OFF required')
    if args.execute_powered and not (args.operator_present_drive_on_no_alarm_05a and args.guarded_independent_light_brake):
        parser.error('Fresh powered/operator/no-alarm and safe external brake confirmation required')
    source=args.execute_powered or args.restore_b_drive_off
    source_row=json.loads(source.read_text()) if source else {}
    selected=args.baseline_restore or (Path(source_row['baseline_restore_receipt']) if source else ROOT_RESTORE)
    requested=not args.dob_off
    if args.execute_powered and source_row.get('dob_feedback_requested',True)!=requested:
        parser.error('Requested DOB ON/OFF differs from the independently verified stage plan')
    if args.restore_b_drive_off:requested=source_row.get('dob_feedback_requested',True)
    data=configure(selected)
    if not (args.stage_off or source):print('OFFLINE PASS: normal DOB0.25 START image; no devices');return 0
    mode='stage' if args.stage_off else 'restore' if args.restore_b_drive_off else 'run'
    name='dob025-normal-'+mode+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],postflight={},
        start_attempts=0,automatic_retry=False,automatic_parameter_write=False,friction_enabled=True,
        image_sha256=SHA,elf_sha256=ELF_SHA,baseline_restore_receipt=str(selected.resolve()),
        physical_power_off=args.drive_off_brake_released_fixed_guarded,
        powered_no_alarm=args.operator_present_drive_on_no_alarm_05a,
        guarded_brake_confirmed=args.guarded_independent_light_brake,
        speed_target_rpm=240,dob_gain=.25,iq_limit_a=.5,dob_cap_a=.025,
        dob_feedback_requested=requested,
        host_max_seconds=base.HOST_MAX_SECONDS)
    base.old.prior.checkpoint(row,'prepared')
    try:
        if args.stage_off:base.stage(row,name,data)
        elif args.restore_b_drive_off:base.restore(row,name,source,data)
        else:
            try:ORIGINAL_EXECUTE(row,name,source,data)
            except RuntimeError as error:
                expected='FSM terminal '+row.get('terminal_status',{}).get('OUTCOME','UNKNOWN')+'; no-load observation is not successful tightening; no retry'
                if str(error)!=expected:raise
            row['result']=classify(row);row['pass_']=True
    except BaseException as error:
        row['failure']=str(error)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    base.old.prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1

if __name__=='__main__':raise SystemExit(main())
