"""One no-START output-OFF preflight of synchronized A. FILES ONLY by default."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import zlib
import ka_identification_board as previous
import ka_sync_report as report

base=previous.base
gain=previous.gain
TMP=base.TMP
ROOT_RESTORE=TMP/'ka-repeat-restore-1792653378243224400.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/KaSynchronizedDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='5428b7993a5bc8f8f7ce22772d29efb800c1244699df546231d33ec825c0c136'
ELF_SHA='f00c940b6f868f4c1f4c88c028db23742dd7c33412ddac3a516256da17b68ed3'
SIZE=219100


def image():
    data=IMAGE.read_bytes()
    command=next(x['command'] for x in json.loads((IMAGE.parent/'compile_commands.json').read_text())
        if x['file'].endswith('/Core/Src/main.c'))
    required=('FOC_KA_SYNC_DIAG=1','KA_SYNC_START_US=600000U',
        'FOC_PROTECTED_CLOSED_LOOP=1','FOC_BEMF_CANDIDATE=1','FOC_BEMF_ENABLED_DEFAULT=0',
        'FOC_CURRENT_PI_IDENTIFIED_ENABLE=1','FOC_ONE_CYCLE_PWM_PIPELINE=1',
        'FOC_PWM_PIPELINE_CLOSED_LOOP=1','FOC_INTENT_FSM_CANDIDATE=1','FOC_FRICTION_ENABLED_DEFAULT=1',
        'AS5047P_DMA_FOC_FIRST=1','FOC_SPEED_PI_ANTI_WINDUP=1','FOC_ACCEL_FF_ENABLED_DEFAULT=1',
        'SPEED_FRICTION_I_A=0.105f','SPEED_ACCEL_FF_KA_A_PER_RPM_S=0.0000000f')
    if (len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or
        hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        any('-D'+d+' ' not in command for d in required) or
        any('-D'+d in command for d in ('FOC_KA_IDENT_DIAG','FOC_ACCEL_FF_AUDIT','FOC_STARTUP_TIMESTAMPS_DIAG',
            'FOC_PSI_IDENT','FOC_CURRENT_STEP_AB_DIAG','FOC_FAST_REJECT_COMPUTE_ONLY','FOC_DQ_DECOUPLING_CANDIDATE'))):
        raise ValueError('Exact offline-tested sync A image/ELF/defines required')
    symbols=base.symbols(ELF)
    if symbols.get('ka_sync_diagnostic',(0,0))[1]!=1212 or symbols.get('ka_sync_current',(0,0))[1]!=20:
        raise ValueError('Sync ABI mismatch')
    for marker in (b'TRIP_MA=4000',b'METHOD=TWO_SAMPLE',b'TRAVEL=20000deg RAM only',
        b'RUNDOWN240: RAM=240rpm TRIP=300rpm SAVE=OFF'):
        if marker not in data:raise ValueError('Protection marker missing')
    base.support.support.require_baud(command)
    return data


def no_motion(*args):
    raise RuntimeError('No START authorized in this preflight wrapper')


def decode(row):
    gain.ORIGINAL_DECODE(row)
    gain.prior.checkpoint(row,'captured_before_sync_decode')
    row['sync_saved']=report.decode(Path(row['receipt_path']),ELF)
    ram=Path(row['ram_capture']).read_bytes();address,size=base.symbols(ELF)['ka_sync_current']
    if size!=20:raise ValueError('Wrong current publication ABI')
    row['sync_current_saved']=dict(zip(('version','source_seq','source_us','published_us','iq'),
        struct.unpack_from('<4If',ram,address-0x20000000)))


def setup(path):
    # Prove B975 and installed OLD KAI A using OLD identity before swapping.
    previous.setup(ROOT_RESTORE);base.baseline()
    fitted=gain.fitted
    fitted.IMAGE,fitted.ELF,fitted.SHA,fitted.ELF_SHA,fitted.SIZE=IMAGE,ELF,SHA,ELF_SHA,SIZE
    fitted.image=image;fitted.motion=no_motion;fitted.decode=decode
    base.IMAGE,base.ELF,base.SHA,base.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    base.image=image;base.motion=no_motion;base.decode_cm=decode
    gain.current_gain=0
    if path.resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(path)
    return image()


def accept(row):
    timing=row.get('snapshot',{}).get('timing',{});fault=row.get('snapshot',{}).get('first_fault',{})
    current=row.get('sync_current_saved',{});sync=row.get('sync_saved',{})
    status=base.hw.fields(row.get('postflight',{}).get('MOTOR TEST STATUS',''))
    output=row.get('outputs',{})
    if (row.get('start_attempts')!=0 or row.get('preflight_pass') is not True or
        any(c.get('command','').split()[:1]==['START'] for c in row.get('commands',[])) or
        row.get('motor_stack_preflight',{}).get('VALID')!='1' or
        int(row.get('motor_stack_preflight',{}).get('FREE_B','0'))<256 or
        not row.get('all_app_private_unchanged') or not row.get('final_cpu_halted') or not row.get('final_outputs_off') or
        output.get('VTOR')!=0x08008000 or output.get('SD',64)&64 or output.get('BDTR',0xc000)&0xc000 or output.get('CCER',1) or
        fault.get('valid')!=0 or not 0<timing.get('wall_max_us',0)<50 or
        timing.get('deadline_miss')!=0 or timing.get('actual_late_count')!=0 or timing.get('actual_margin_min_us',0)<=1 or
        row['snapshot'].get('cur_confirm',{}).get('fault')!=0 or sync.get('meta',{}).get('count')!=0 or
        not current.get('version') or current['version']&1 or not current.get('source_seq') or
        not sync.get('publisher_max_cycles') or row.get('stop_error') or row.get('token_decode_errors') or
        any(status.get(k)!=v for k,v in dict(STATE='1',USED='0',FAULT='0',FLAGS='0',SD='0',MOE='0',CCER='0').items())):
        raise RuntimeError('Output-OFF sync preflight/timing/stack/current publication failed; no retry')
    row['result']=dict(preflight_only=True,no_start=True,foc_max_us=timing['wall_max_us'],
        deadline_miss=timing['deadline_miss'],ccr_late=timing['actual_late_count'],
        actual_margin_min_us=timing['actual_margin_min_us'],publisher_max_us=sync['publisher_max_us'],
        short_window_points=0,mechanical_alignment_not_tested=True)


def execute_preflight(row,name,path,data):
    if not row.get('powered_no_alarm'):raise ValueError('Fresh powered/no-alarm/operator confirmation required')
    source,before=base.staged(path,data)
    port=base.support.support.open_port();uart=base.TokenConsole(port,row)
    try:
        row['hardware_attempted']=True;gain.prior.checkpoint(row,'preflight_trial_no_START')
        base.hw.debug(row,[*base.old.zero.off_gate(),
            *base.hw.full_compare_commands(TMP/(name+'-before.bin'),source),
            'reset halt',*base.hw.off_commands(),
            *base.hw.write_mailbox(base.mailbox(2,2,1,len(data),zlib.crc32(data))),
            'reset run','shutdown'])
        base.old.prior.wait_health_confirmation(uart,row,base.hw.fields)
        row['zero']=base.old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        row['profile']=base.profile(uart.query('MOTOR TEST PROFILE'))
        row['filter']=base.filter_profile(uart.query('MOTOR TEST FILTER'))
        base.old.prior.wait_timing(uart,row)
        port.close()
        reader=base.TokenRecordedBoard('COM5',row)
        try:
            row['motor_stack_preflight']=base.motor_stack(reader)
            for cmd in ('MOTOR TEST STATUS','MOTOR TEST FAULT','STATUS','FW STATUS'):
                row['postflight'][cmd]=reader.command(cmd)
            row['stop_ack']=reader.command('STOP');row['safe_ack']=reader.command('ANALOG SAFE')
        finally:reader.close()
        row['preflight_pass']=True
    finally:
        if port.is_open:
            try:row['stop_ack']=uart.query('STOP',.6);row['safe_ack']=uart.query('ANALOG SAFE',.8)
            except Exception as error:row['stop_error']=str(error)
            port.close()
        if row.get('hardware_attempted'):
            base.old.capture_stopped(row,name,before,elf=ELF)
            if row.get('outputs',{}).get('VTOR')==0x08008000:decode(row)
    accept(row);row['pass_']=True


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--stage-off',action='store_true');m.add_argument('--preflight-powered',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path);p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-drive-on-no-alarm-05a',action='store_true');a=p.parse_args(argv)
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:p.error('Fresh OFF required')
    if a.preflight_powered and not a.operator_present_drive_on_no_alarm_05a:p.error('Fresh supervised powered confirmation required')
    source=a.preflight_powered or a.restore_b_drive_off
    selected=a.baseline_restore or (Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE)
    data=setup(selected)
    if not (a.stage_off or source):print('OFFLINE PASS: sync output-OFF preflight only, no START, no devices');return 0
    mode='stage' if a.stage_off else 'restore' if a.restore_b_drive_off else 'run'
    name='ka-sync-'+mode+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],postflight={},
        image_sha256=SHA,elf_sha256=ELF_SHA,baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),
        start_attempts=0,motor_commands=0,automatic_retry=False,automatic_parameter_write=False,
        physical_power_off=a.drive_off_unlocked_no_load_fixed,powered_no_alarm=a.operator_present_drive_on_no_alarm_05a,
        friction_enabled=True,bemf_enabled=False,gain_percent=0)
    gain.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.restore_b_drive_off:base.restore(row,name,source,data)
        else:execute_preflight(row,name,source,data)
    except BaseException as error:
        row['failure']=str(error)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    gain.prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
