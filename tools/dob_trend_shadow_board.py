"""One supervised240rpm shadow trend/brake observation, files-only by default.

No brake actuator API and no absolute physical load timestamp. A-only recorder,
unchanged normal DOB0.25/control/protections. Separate OFF stage/ON run/OFF B restore.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import struct
import time
import dob_gain_ab_twenty_board as prior

base=prior.base;normal=prior.normal;TMP=base.TMP
ROOT_RESTORE=TMP/'dob-gain-ab-restore-1792763799510887400.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/DobTrendShadowCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='010392ff9c8b97c7f3de47ecf1d5ce20d1bb2a5b6c3dd72fcbf717a10f8ee567'
ELF_SHA='d1f57741b9b66195fc9c2ec6ef7d165b539a50ada56ec41f6ced88fb8062fc86'
SIZE=225752
CFG=dict(ABI='1',SHADOW='1',TAU_US='100000',DWELL_US='80000',SPAN_US='100000',
         GAP_US='20000',RECORD_US='8000',POINTS='144',PROXY_UA='10000')
HEADER=('abi flags observations start_us last_record_us arm_qual_us arm_us baseline_a peak_a '
        'proxy_rise_us proxy_fall_us trigger_head head pre_count post_count trend_rise_us '
        'trend_fall_us level_high_us feature_updates dt_min_us dt_max_us max_cycles record_count').split()
# ARM gcc/native ABI: classifier1012B then144 x24B records, total4468B.
CLASSIFIER_SIZE=1012

def image():
    data=IMAGE.read_bytes()
    if len(data)!=SIZE or prior.raw.digest(IMAGE)!=SHA or prior.raw.digest(ELF)!=ELF_SHA:
        raise ValueError('Exact reviewed trend image/ELF required')
    command=next(x['command'] for x in json.loads((IMAGE.parent/'compile_commands.json').read_text()) if x['file'].endswith('/Core/Src/main.c'))
    for flag in ('FOC_DOB_TREND_SHADOW=1','FOC_DOB_NORMAL_CONTROL=1','FOC_DOB_CONTACT20_OBSERVE10=1',
                 'FOC_ONE_CYCLE_PWM_PIPELINE=1','FOC_OUTER_OBSERVE_AFTER_ACK=1','DOB_ADMIT_JUMP_A=.200f'):
        if '-D'+flag+' ' not in command:raise ValueError('Required build '+flag)
    for flag in ('FOC_DOB_REAL_TRACE','FOC_DOB_ID_TRACE','FOC_DOB_GAIN_AB_DIAG'):
        if '-D'+flag+'=1 ' in command:raise ValueError('Conflicting diagnostic '+flag)
    syms=base.symbols(ELF)
    for name,n in dict(dob_trend_shadow=92,dob_trend_arena=4,mechanical_capture=4712,dob_feedback=80).items():
        if syms.get(name,(0,0))[1]!=n:raise ValueError('Trend ABI '+name)
    if base.hw.image_info(data)[0]!='A':raise ValueError('Candidate A only')
    return data

def configure(path):
    prior.configure(ROOT_RESTORE) # Validate old frozen identity before selecting a new image.
    for key in ('IMAGE','ELF','SHA','ELF_SHA'):setattr(base,key,globals()[key])
    base.image=image;base.staged=normal.ORIGINAL_STAGED;base.decode_cm=decode;base.motion=motion
    normal.FB_CONFIG=dict(normal.FB_CONFIG,ON='1',GAIN_PPM='250000')
    if Path(path).resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(Path(path))
    return image()

def motion(board,row):
    # Power OFF / idle guards are enforced by the existing FB ON command.
    normal.check_values(board.command('MOTOR TEST MECH DOB FB CFG'),
                        dict(normal.FB_CONFIG,ON='0'),'Boot default DOB OFF')
    row['dob_guarded_on']=normal.check_values(board.command('MOTOR TEST MECH DOB FB ON'),
        normal.FB_CONFIG,'Existing normal gain0.25')
    row['trend_config']=normal.check_values(board.command('MOTOR TEST MECH DOB TREND CFG'),CFG,'Shadow-only trend configuration')
    row['speeds']=normal.check_values(board.command('MOTOR TEST MECH DOB SPEEDS'),
        dict(CONTACT_RPM='20',OBS_MIN_MRPM='10000',FB_MIN_MRPM='20000'),'Existing normal speed admission')
    try:normal.motion(board,row) # Original bounded single START; includes timing/stack/readiness/model checks.
    finally:
        for command in ('MOTOR TEST MECH DOB TREND','MOTOR TEST MECH DOB STATS','MOTOR TEST MECH DOB ADMIT GAPS'):
            row['postflight'][command]=board.command(command)

def decode_capture(ram,syms):
    def block(name):
        address,n=syms[name];offset=address-0x20000000
        if not 0<=offset<=len(ram)-n:raise ValueError('RAM bounds '+name)
        return ram[offset:offset+n]
    h=dict(zip(HEADER,struct.unpack('<7I2f14I',block('dob_trend_shadow'))))
    pointer=struct.unpack('<I',block('dob_trend_arena'))[0]
    if not h['abi'] and not h['observations'] and not pointer:return h,[]
    if h['abi']!=1 or pointer!=syms['mechanical_capture'][0] or h['flags']&16:
        raise ValueError('Trend arena/header identity')
    if h['head']>=144 or h['trigger_head']>=144 or h['pre_count']>32 or h['post_count']>112:
        raise ValueError('Trend ring bounds')
    if h['flags']&2:
        count=h['pre_count']+h['post_count'];first=(h['trigger_head']-h['pre_count'])%144
    else:count=min(h['record_count'],144);first=(h['head']-count)%144
    raw=block('mechanical_capture');rows=[]
    for k in range(count):
        enc,load,trend,rpm,iq,flags,level,state=struct.unpack_from('<I4fH2B',raw,CLASSIFIER_SIZE+((first+k)%144)*24)
        if not all(math.isfinite(x) for x in (load,trend,rpm,iq)) or level>4 or state>3:
            raise ValueError('Nonfinite or invalid label in trend record')
        if rows and not 0<(enc-rows[-1]['timestamp_us'])&0xffffffff<100000:
            raise ValueError('Trend sample chronology')
        rows.append(dict(sample_index=k,timestamp_us=enc,time_from_run_start_s=((enc-h['start_us'])&0xffffffff)*1e-6,
            disturbance_a=load,trend_a_s=trend,speed_meas_rpm=rpm,iq_a=iq,
            flags=flags,dob_status=flags&2047,dob_valid=bool(flags&2048),lpf_updated=bool(flags&4096),
            class_valid=bool(flags&8192),trend_valid=bool(flags&16384),triggered=bool(flags&32768),
            level=level,trend=state))
    return h,rows

def relative_delays(h):
    result=dict(physical_brake_timestamp_available=False,absolute_brake_delay_ms=None,
        reference='100ms directional DOB mean rises10mA above armed baseline; internally filtered proxy, not physical load truth',
        triggered=bool(h['flags']&2),armed=bool(h['flags']&1))
    for name,a,b,preactive in [('rise','proxy_rise_us','trend_rise_us',32),('fall','proxy_fall_us','trend_fall_us',64)]:
        reason='measured' if h[a] and h[b] else 'missing_proxy_or_confirmation'
        if h['flags']&preactive:reason='trend_already_active_at_proxy'
        dt=(h[b]-h[a])&0xffffffff
        if reason=='measured' and dt>=0x80000000:reason='confirmation_precedes_proxy'
        result[name+'_relative_delay_ms']=dt*.001 if reason=='measured' else None
        result[name+'_reason']=reason
    return result

def decode(row):
    normal.ORIGINAL_DECODE(row) # Original Flash/ELF and FF/friction aggregate decoding.
    ram=Path(row['ram_capture']).read_bytes();syms=base.symbols(ELF)
    address,n=syms['dob_feedback']
    row['feedback_capture']=normal.prior.fb.decode_feedback(ram[address-0x20000000:address-0x20000000+n])
    h,rows=decode_capture(ram,syms)
    csv_path=Path(row['receipt_path']).with_suffix('.trend.csv')
    if rows:
        with csv_path.open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
    row['trend_capture']=dict(header=h,rows=len(rows),csv=str(csv_path) if rows else None,
        csv_sha256=prior.raw.digest(csv_path) if rows else None,ram_sha256=prior.raw.digest(row['ram_capture']),
        relative=relative_delays(h),irq_inclusive_wall_max_us=h['max_cycles']/170,
        semantics='Read-only labels. Original DOB/control unchanged; independent physical brake time/torque unavailable.')

def record(mode,name,baseline,off,powered):
    return dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],postflight={},
        image_sha256=SHA,elf_sha256=ELF_SHA,baseline_restore_receipt=str(Path(baseline).resolve()),
        start_attempts=0,automatic_retry=False,automatic_parameter_write=False,friction_enabled=True,
        physical_power_off=off,powered_no_alarm=powered,dob_feedback_requested=True,
        guarded_brake_confirmed=powered,brake_dynamic_rated=True,brake_force_control_available=False,
        physical_brake_timestamp_available=False,trend_feedback=False,
        speed_target_rpm=240,iq_limit_a=.5,dob_gain=.25,dob_cap_a=.025,host_max_seconds=base.HOST_MAX_SECONDS)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--stage-off',action='store_true');g.add_argument('--execute-powered',type=Path)
    g.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-brake-released-fixed-guarded',action='store_true')
    p.add_argument('--operator-present-drive-on-no-alarm-05a',action='store_true')
    p.add_argument('--dynamic-brake-immediately-releasable',action='store_true');a=p.parse_args(argv)
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_brake_released_fixed_guarded:
        p.error('Fresh physical12V OFF confirmation required')
    if a.execute_powered and not (a.operator_present_drive_on_no_alarm_05a and a.dynamic_brake_immediately_releasable):
        p.error('Fresh powered/operator/no-alarm and independently releasable dynamic brake required')
    source=a.execute_powered or a.restore_b_drive_off
    baseline=Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE
    data=configure(baseline)
    if not a.stage_off and not source:print('OFFLINE PASS: pinned shadow A; no devices');return 0
    mode='stage' if a.stage_off else 'restore' if a.restore_b_drive_off else 'run'
    name='dob-trend-'+mode+'-'+str(time.time_ns());row=record(mode,name,baseline,
        a.drive_off_brake_released_fixed_guarded,a.operator_present_drive_on_no_alarm_05a)
    base.old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.restore_b_drive_off:base.restore(row,name,source,data)
        else:
            try:normal.ORIGINAL_EXECUTE(row,name,source,data)
            except RuntimeError as error:
                expected='FSM terminal '+row.get('terminal_status',{}).get('OUTCOME','UNKNOWN')+'; no-load observation is not successful tightening; no retry'
                if str(error)!=expected:raise
            row['result']=normal.classify(row);row['pass_']=True
            row['result']['note']='Single dynamic brake shadow classification observation; no calibrated torque or physical-onset truth.'
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
