"""Pinned manual RS50 only: OFF stage, supervised ON single 400ms, OFF restore.

Default files-only. Never START, advance current/stage, clear a fault or retry.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib
import friction_fsm_board as base
import motor_identification_report as analysis

TMP=base.TMP
RESTORE=TMP/'friction-fsm-restore-1792494698352284100.json'
BASE_SHA='0688e4b2e7eea4d0a4ea12684df974416eb7924230f7cafb7ab615a0eb26fd02'
IMAGE=base.old.ROOT/'foc2_app_a/build/MotorParameterIdentificationDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='15511c9bd4c3bb579773928bb70a2ffc5e08250b6ddf899bbfda6c10a3d81e4d'
ELF_SHA='1e4cf495f8da3ba7dec4c7c211d23ee2c623b7c852a915dd1aa4216cd8909d9f'
ORIGINAL_CONFIGURE=base.configure_baseline
COMMAND='MOTOR TEST IDENT RS 50 LOCKED CONFIRM'
RS_MA=50
IDENT_SIZE=1596
EXTRA_READOUT=None
EXTRA_DECODE=None


def image():
    data=IMAGE.read_bytes()
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
        if c['file'].endswith('/Core/Src/main.c'))
    base.support.support.require_baud(cmd)
    if (len(data)!=212732 or base.old.zero.digest(data)!=SHA or
        base.old.zero.digest(ELF.read_bytes())!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        base.symbols(ELF).get('motor_ident',(0,0))[1]!=1596 or
        any(k not in cmd for k in ('-DFOC_MOTOR_IDENTIFICATION_DIAG=1',
            '-DFOC_PWM_PIPELINE_CLOSED_LOOP=1','-DSPEED_FRICTION_I_A=0.105f')) or
        any(k in cmd for k in ('-DFOC_FRICTION_CALIBRATION_DIAG','-DFOC_TORQUE_CHAIN_DIAG')) or
        b'MOTOR_IDENT_DIAGNOSTIC: LOCK ROTOR; manual one-shot; no START' not in data or
        b'TRIP_MA=4000' not in data):
        raise ValueError('Exact offline-tested identification A BIN/ELF/ABI required')
    return data


def configure(path=RESTORE):
    path=path.resolve()
    if path!=RESTORE.resolve():raise ValueError('Exact halted B804 baseline required')
    ORIGINAL_CONFIGURE(base.ROOT_RESTORE);root=base.baseline()
    r=json.loads(path.read_text('utf-8'));capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or r.get('motor_commands')!=0 or
        any(r.get(k) is not True for k in ('pass_','all_app_private_unchanged',
            'b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Preserved output-OFF B804 receipt required')
    raw=capture.read_bytes();meta=base.old.zero.latest_meta(raw);off=r.get('outputs',{})
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=BASE_SHA or r.get('final_sha256')!=BASE_SHA or
        list(meta)!=r.get('metadata') or meta[2:10]!=(2,0,0,804,217420,126775320,227964,627317606) or
        base.old.zero.digest(raw[0x8000:0x8000+217420])!='3adf71acf9579d455f9e0f27e27d121a863c570cde9f0baabb65b9f587ef2899' or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or off.get('VTOR')!=0x08040000 or
        not off.get('DHCSR',0)&0x20000 or off.get('SD',0x40)&0x40 or
        off.get('BDTR',0xC000)&0xC000 or off.get('CCER',1)):
        raise ValueError('B804 identity/B/boot/private/output mismatch')
    base.BASE=capture;base.BASE_SHA=BASE_SHA;base.EXPECT_META=meta;base.BASE_RESTORE_RECEIPT=path


def install():
    base.IMAGE,base.ELF,base.SHA,base.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    base.image=image;base.FRICTION_A=.105


def ready_ident(reply):
    v=base.hw.fields(reply)
    if any(v.get(k)!=x for k,x in dict(MODE='0',STATUS='0',REASON='0',N='0',USED='0',
        IMAX_MA='200',VMAX_MV='200').items()):raise RuntimeError('Fresh unused IDLE identification required')
    return v


def motion(board,row,*,ident_mode='RS',voltage_step=False):
    """Exactly one pinned Rs point; independent firmware stop is 400ms."""
    expected=('MOTOR TEST IDENT %sV 50MV LOCKED CONFIRM'%ident_mode if voltage_step else
              'MOTOR TEST IDENT RS %d LOCKED CONFIRM'%RS_MA if ident_mode=='RS' else
              'MOTOR TEST IDENT %s RS_VALIDATED LOCKED CONFIRM'%ident_mode)
    if ident_mode not in ('RS','LD','LQ') or (voltage_step and ident_mode=='RS') or COMMAND!=expected:
        raise ValueError('Pinned command/mode mismatch; no excitation')
    try:
        base.require_idle_ready(board,'A')
        row['ident_before']=ready_ident(board.command('MOTOR TEST IDENT STATUS'))
        row['profile_before']=base.profile(board.command('MOTOR TEST PROFILE'))
        row['filter_before']=base.filter_profile(board.command('MOTOR TEST FILTER'))
        ready=base.hw.fields(board.command('MOTOR TEST STATUS'))
        if any(ready.get(k)!=v for k,v in dict(STATE='1',USED='0',ZERO='3',FAULT='0',
            FLAGS='0',SD='0',MOE='0',CCER='0').items()):raise RuntimeError('Protected readiness failed; no excitation')
        row['motor_stack_preflight']=base.motor_stack(board)
        if row['motor_stack_preflight'].get('VALID')!='1' or int(row['motor_stack_preflight'].get('FREE_B',0))<256:
            raise RuntimeError('Motor task stack gate failed')
        adc=base.hw.fields(board.command('ADC TIMING'));row['adc_preflight']=adc
        if any(adc.get(k)!=v for k,v in dict(MISS='0',PF='0',DWT='1').items()):raise RuntimeError('ADC planning failed')
        if row.get('excitation_attempts',0):raise RuntimeError('No second excitation')
        row['excitation_attempts']=1;base.old.prior.checkpoint(row,'RS%d_ATTEMPT'%RS_MA)
        row['excitation_ack']=board.command(COMMAND,.3)
        if ' OK IDENT QUEUED ONE_SHOT=1 LOCKED_ACK=1' not in row['excitation_ack']:
            raise RuntimeError('Explicit RS%d admission not proven'%RS_MA)
        until=time.monotonic()+.65
        while time.monotonic()<until:
            line=board.command('MOTOR TEST IDENT STATUS',.2)
            v=base.hw.fields(line);row.setdefault('ident_statuses',[]).append(line)
            if v.get('STATUS') in ('3','4'):
                row['terminal_ident']=v;break
        if not row.get('terminal_ident'):raise RuntimeError('400ms endpoint absent; STOP, no retry')
    finally:
        # Safety closure precedes any multi-row logging/analysis.
        row['stop_ack']=board.command('MOTOR TEST STOP',.5)
        row['off_ack']=board.command('ANALOG SAFE',.8)
        safe=base.hw.fields(board.command('ANALOG SAFE STATUS',.8));row['safe']=safe
        if any(safe.get(k)!=v for k,v in dict(LATCHED='1',SD='0',MOE='0',FOC='0').items()):
            raise RuntimeError('Output-OFF latch unproven')
        status=board.command('MOTOR TEST IDENT STATUS');values=base.hw.fields(status)
        row['final_ident_status']=values
        row['ident_replies']=[status,board.command('MOTOR TEST IDENT GEOMETRY')]
        n=int(values.get('N','-1'))
        if values.get('STATUS') not in ('3','4') or not 0<=n<=32:
            raise RuntimeError('Trace not terminal/bounded')
        for k in range(n):row['ident_replies'].append(board.command('MOTOR TEST IDENT ROW '+str(k)))
        if EXTRA_READOUT:EXTRA_READOUT(board,row)
        for cmd in ('MOTOR TEST FAULT','MOTOR TEST TIMING','STATUS','ADC TIMING'):
            row['postflight'][cmd]=board.command(cmd)


def decode_capture(row,*,ident_mode='RS',voltage_step=False):
    if ident_mode not in ('RS','LD','LQ'):raise ValueError('Explicit identification mode required')
    flash=Path(row['final_capture']).read_bytes();ram=Path(row['ram_capture']).read_bytes()
    if base.old.zero.digest(flash)!=row['final_sha256'] or flash[0x8000:0x8000+len(image())]!=image():
        raise ValueError('Same-session image mismatch')
    syms=base.symbols(ELF);addr,size=syms['motor_ident']
    if size!=IDENT_SIZE or len(ram)!=0x20000:raise ValueError('Identification ABI/RAM mismatch')
    offset=addr-0x20000000
    meta=struct.unpack_from('<11I2f8B',ram,offset+32*48)
    names=('count start_us last_us last_seq encoder_before pending_before arr ccr4 cr1 rcr jsqr '
        'initial_angle current_a mode status reason used prepared admitting confirmed_locked reserved').split()
    s=dict(zip(names,meta));row['ident_ram']=s
    if s['mode']!={'RS':1,'LD':2,'LQ':3}[ident_mode]:
        raise ValueError('Frozen identification mode mismatch')
    keys='us seq pending_before id_ref iq_ref id iq vd vq angle speed mode status reason reserved'.split()
    if voltage_step:
        keys='us seq pending_before raw_u raw_v tail_cnt tail_flags id iq vd vq angle speed mode status reason reserved'.split()
        rows=[dict(zip(keys,struct.unpack_from('<3I4H6f4B',ram,offset+k*48))) for k in range(min(s['count'],32))]
        for r in rows:r.update(id_ref=0.,iq_ref=0.)
    else:
        rows=[dict(zip(keys,struct.unpack_from('<3I8f4B',ram,offset+k*48))) for k in range(min(s['count'],32))]
    guard={}
    for key in ('cl_flags','cl_fault_valid','adc_fault','foc_fault','encoder_valid'):
        at,n=syms[key];guard[key]=int.from_bytes(ram[at-0x20000000:at-0x20000000+n],'little')
    row['live_guard']=guard
    timing=row['snapshot']['timing']
    clean=(not any(guard[k] for k in ('cl_flags','cl_fault_valid','adc_fault','foc_fault')) and
        guard['encoder_valid']==1 and not row['snapshot']['first_fault']['valid'] and
        timing['deadline_miss']==0 and timing['actual_late_count']==0)
    row['ident_run']=dict(mode=ident_mode,status=s['status'],fault=s['reason'],rows=rows,
        geometry={k:s[k] for k in ('arr','ccr4','cr1','rcr','jsqr')},
        latch_evidence=dict(verified=False),
        raw_voltage_frame=voltage_step,
        protection_evidence=dict(verified=clean,source=row['receipt_path'],
            fault=0 if clean else 1,deadline_miss=timing['deadline_miss'],ccr_late=timing['actual_late_count']))
    row['ram_sha256']=base.old.zero.digest(ram)
    if rows and ident_mode=='RS':
        import statistics as st
        i=st.mean(r['id'] for r in rows);v=st.mean(r['vd'] for r in rows)
        row['single_point_observation']=dict(mean_id_a=i,mean_iq_a=st.mean(r['iq'] for r in rows),
            mean_vd_v=v,ratio_ohm=v/i if i else None,
            qualification='One point only, not a fitted/qualified Rs; never updates PI')
    row['acquisition_pass']=bool(clean and s['status']==3 and s['reason']==0 and s['count']==32)
    if EXTRA_DECODE:EXTRA_DECODE(row,ram,offset)


def execute(row,name,path,data):
    if not row.get('powered_no_alarm') or not row.get('locked_fixture'):
        raise ValueError('Powered/no-alarm/operator/locked fixture confirmation required')
    source,before=base.staged(path,data)
    port=base.support.support.open_port();uart=base.TokenConsole(port,row)
    try:
        row['hardware_attempted']=True;base.old.prior.checkpoint(row,'trial_no_START')
        base.hw.debug(row,[*base.old.zero.off_gate(),
            *base.hw.full_compare_commands(TMP/(name+'-before.bin'),source),
            'reset halt',*base.hw.off_commands(),
            *base.hw.write_mailbox(base.mailbox(2,2,1,len(data),zlib.crc32(data))),'reset run','shutdown'])
        base.old.prior.wait_health_confirmation(uart,row,base.hw.fields)
        if not any('MOTOR_IDENT_DIAGNOSTIC: LOCK ROTOR' in x for x in uart.lines):
            raise RuntimeError('Diagnostic marker absent; no excitation')
        row['zero']=base.old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        row['profile']=base.profile(uart.query('MOTOR TEST PROFILE'))
        row['filter']=base.filter_profile(uart.query('MOTOR TEST FILTER'))
        base.old.prior.wait_timing(uart,row);row['preflight_pass']=True
        port.close();board=base.TokenRecordedBoard('COM5',row)
        try:motion(board,row)
        finally:board.close()
    finally:
        if port.is_open:
            try:row['safe_ack']=uart.query('ANALOG SAFE',.6)
            except Exception as e:row['stop_error']=str(e)
            port.close()
        if row.get('hardware_attempted'):
            base.old.capture_stopped(row,name,before,elf=ELF)
            if row.get('outputs',{}).get('VTOR')==0x08008000:decode_capture(row)
    if not row.get('acquisition_pass'):raise RuntimeError('Identification aborted/insufficient; no retry, no next stage')
    row['pass_']=True


def main():
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--stage-off',action='store_true');m.add_argument('--execute-powered',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-locked-fixture',action='store_true')
    p.add_argument('--operator-present-locked-drive-on-no-alarm-05a',action='store_true')
    a=p.parse_args()
    if RS_MA not in (50,75,100) or COMMAND!='MOTOR TEST IDENT RS %d LOCKED CONFIRM'%RS_MA:
        raise ValueError('Exactly one pinned supported manual Rs current required')
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_locked_fixture:p.error('Fresh drive OFF/locked fixture required')
    if a.execute_powered and not a.operator_present_locked_drive_on_no_alarm_05a:p.error('Fresh powered locked supervised conditions required')
    configure();install();data=image();base.baseline()
    if not (a.stage_off or a.execute_powered or a.restore_b_drive_off):
        print('OFFLINE PASS: exact RS%d-only A and B%d, no devices'%(RS_MA,base.EXPECT_META[5]));return 0
    kind='stage' if a.stage_off else 'run' if a.execute_powered else 'restore'
    name='motor-ident-rs%d-'%RS_MA+kind+'-'+str(time.time_ns())
    row=dict(mode=kind,pass_=False,receipt_path=str(TMP/(name+'.json')),
        image_sha256=SHA,elf_sha256=ELF_SHA,baseline_restore_receipt=str(RESTORE),
        steps=[],commands=[],uart=[],samples=[],postflight={},start_attempts=0,excitation_attempts=0,
        automatic_retry=False,automatic_next_stage=False,friction_enabled=True,
        physical_power_off=a.drive_off_locked_fixture,locked_fixture=True,
        powered_no_alarm=a.operator_present_locked_drive_on_no_alarm_05a,
        test=dict(mode='RS',id_ref_a=RS_MA/1000,iq_ref_a=0,max_us=400000))
    base.old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.execute_powered:execute(row,name,a.execute_powered,data)
        else:base.restore(row,name,a.restore_b_drive_off,data)
    except BaseException as e:
        row.update(pass_=False,failure=str(e))
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as cleanup:row['cleanup_error']=str(cleanup)
    base.old.prior.checkpoint(row,'complete' if row['pass_'] else 'aborted')
    print(('PASS: ' if row['pass_'] else 'STOPPED/FAIL: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
