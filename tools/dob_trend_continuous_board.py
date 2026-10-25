"""One normal500/240rpm supervised continuous trend retest; files-only default.
Original bounded START, protections, separate OFF-stage/ON-run/OFF-B-restore.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import struct
import time
import dob_trend500_board as prior

base=prior.base;normal=prior.normal;TMP=prior.old.TMP
ROOT_RESTORE=TMP/'dob-trend-restore-1792819766618349800.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/DobTrendContinuousTrip500Candidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='f0a28f2904b49fd59de68aeb9dfd8f7b15dfd1c0e9843e1e5861e6fe099d7668'
ELF_SHA='072aeac30baf0296e7bcbd80686d20ab07e87e83b508f2071a033f2ab19573db'
SIZE=226332
CFG=dict(ABI='2',SHADOW='1',TAU_US='100000',DWELL_US='80000',RECORD_US='60000',
         POINTS='138',EVENTS='32',CONTINUOUS='1')
HEADER=('abi flags observations start_us last_record_us arm_qual_us arm_us baseline_a peak_a '
        'proxy_rise_us proxy_fall_us record_overflow head event_count event_dropped trend_rise_us '
        'trend_fall_us level_high_us feature_updates dt_min_us dt_max_us max_cycles record_count proxy_above event_head').split()
EVENT_NAMES={1:'armed',2:'mean_threshold_up',3:'mean_threshold_down',4:'level_changed',
             5:'trend_changed',6:'quality_reset',7:'stopped'}

def image():
    data=IMAGE.read_bytes()
    if len(data)!=SIZE or prior.old.prior.raw.digest(IMAGE)!=SHA or prior.old.prior.raw.digest(ELF)!=ELF_SHA:
        raise ValueError('Exact reviewed continuous A/ELF identity required')
    command=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
    for flag in ('FOC_DOB_TREND_CONTINUOUS=1','FOC_DOB_TREND_SHADOW=1','FOC_NORMAL_RUN_TRIP500=1',
                 'FOC_DOB_NORMAL_CONTROL=1','FOC_DOB_CONTACT20_OBSERVE10=1','FOC_OUTER_OBSERVE_AFTER_ACK=1',
                 'FOC_ONE_CYCLE_PWM_PIPELINE=1','DOB_ADMIT_JUMP_A=.200f'):
        if '-D'+flag+' ' not in command:raise ValueError('Required build flag '+flag)
    for flag in ('FOC_DOB_REAL_TRACE','FOC_DOB_ID_TRACE','FOC_DOB_GAIN_AB_DIAG','FOC_MECHANICAL_HIGH_SPEED_DIAG'):
        if '-D'+flag+'=1 ' in command:raise ValueError('Conflicting diagnostic '+flag)
    syms=base.symbols(ELF)
    for name,n in dict(dob_trend_continuous=100,dob_trend_continuous_arena=4,mechanical_capture=4712,dob_feedback=80).items():
        if syms.get(name,(0,0))[1]!=n:raise ValueError('Continuous ABI '+name)
    if 'dob_trend_shadow' in syms or 'dob_trend_arena' in syms:raise ValueError('Unexpected second recorder allocation')
    if base.hw.image_info(data)[0]!='A':raise ValueError('Candidate A only')
    return data

def configure(path):
    prior.configure(ROOT_RESTORE) # Verify current stopped B1209 with previous exact500 image first.
    for key in ('IMAGE','ELF','SHA','ELF_SHA'):setattr(base,key,globals()[key])
    base.image=image;base.motion=motion;base.decode_cm=decode;base.staged=normal.ORIGINAL_STAGED
    normal.FB_CONFIG=dict(normal.FB_CONFIG,ON='1',GAIN_PPM='250000')
    if Path(path).resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(Path(path))
    return image()

def motion(board,row):
    row['normal_limits_before_start']=normal.check_values(board.command('MOTOR TEST MECH DOB LIMITS'),prior.LIMITS,'Unchanged normal500 limits')
    normal.check_values(board.command('MOTOR TEST MECH DOB FB CFG'),dict(normal.FB_CONFIG,ON='0'),'Boot defaultOFF')
    row['dob_guarded_on']=normal.check_values(board.command('MOTOR TEST MECH DOB FB ON'),normal.FB_CONFIG,'Original normal0.25')
    row['trend_config']=normal.check_values(board.command('MOTOR TEST MECH DOB TREND CFG'),CFG,'Continuous classifier ABI2')
    row['speeds']=normal.check_values(board.command('MOTOR TEST MECH DOB SPEEDS'),
        dict(CONTACT_RPM='20',OBS_MIN_MRPM='10000',FB_MIN_MRPM='20000'),'Original speed admission')
    try:normal.motion(board,row)
    finally:
        for command in ('MOTOR TEST MECH DOB TREND','MOTOR TEST MECH DOB STATS','MOTOR TEST MECH DOB ADMIT GAPS'):
            row['postflight'][command]=board.command(command)

def decode_capture(ram,syms):
    def block(name):
        address,n=syms[name];offset=address-0x20000000
        if not 0<=offset<=len(ram)-n:raise ValueError('RAM bounds '+name)
        return ram[offset:offset+n]
    h=dict(zip(HEADER,struct.unpack('<7I2f16I',block('dob_trend_continuous'))))
    pointer=struct.unpack('<I',block('dob_trend_continuous_arena'))[0]
    if not h['abi'] and not h['observations'] and not pointer:return h,[],[],{}
    if h['abi']!=2 or pointer!=syms['mechanical_capture'][0] or h['flags']&16:raise ValueError('Continuous arena identity')
    if (h['head']!=h['record_count']%138 or h['event_head']!=h['event_count']%32 or
        h['record_overflow']!=max(0,h['record_count']-138) or h['event_dropped']!=max(0,h['event_count']-32)):
        raise ValueError('Continuous ring counts/head closure')
    raw=block('mechanical_capture');rows=[];events=[]
    count=min(h['record_count'],138);first=(h['head']-count)%138
    for k in range(count):
        enc,load,mean,trend,rpm,iq,flags,level,state=struct.unpack_from('<I3f2hH2B',raw,1012+((first+k)%138)*24)
        if not all(math.isfinite(v) for v in (load,mean,trend)) or level>4 or state>3:raise ValueError('Invalid continuous record')
        if rows and not 60000<=(enc-rows[-1]['timestamp_us'])&0xffffffff<100000:raise ValueError('Record cadence')
        rows.append(dict(sample_index=k,timestamp_us=enc,time_from_run_start_s=((enc-h['start_us'])&0xffffffff)*1e-6,
            disturbance_a=load,directional_mean_a=mean,trend_a_s=trend,speed_meas_rpm=rpm*.1,iq_a=iq*.001,
            flags=flags,dob_status=flags&2047,dob_valid=bool(flags&2048),lpf_updated=bool(flags&4096),
            class_valid=bool(flags&8192),trend_valid=bool(flags&16384),level=level,trend=state))
    count=min(h['event_count'],32);first=(h['event_head']-count)%32
    for k in range(count):
        enc,kind,level,trend=struct.unpack_from('<IH2B',raw,4324+((first+k)%32)*8)
        if (kind&255) not in EVENT_NAMES or level>4 or trend>3:raise ValueError('Invalid continuous event')
        if events and (enc-events[-1]['timestamp_us'])&0xffffffff>=0x80000000:raise ValueError('Event chronology')
        events.append(dict(event_index=k,timestamp_us=enc,time_from_run_start_s=((enc-h['start_us'])&0xffffffff)*1e-6,
            event=EVENT_NAMES[kind&255],type=kind&255,class_valid=bool(kind&256),trend_valid=bool(kind&512),level=level,trend=trend))
    classifier_names='head count state proposal accepted rejected resets level_changes have_call trend_state trend_proposal trend_changes'.split()
    classifier=dict(zip(classifier_names,struct.unpack_from('<12I',raw,900)))
    last_call=struct.unpack_from('<I',raw,960)[0]
    coverage=dict(classifier_last_us=last_call,classifier_span_s=((last_call-h['start_us'])&0xffffffff)*1e-6,
        record_start_s=rows[0]['time_from_run_start_s'] if rows else None,
        record_end_s=rows[-1]['time_from_run_start_s'] if rows else None,
        full_observed_run=bool(rows and not h['record_overflow'] and rows[0]['timestamp_us']==h['start_us'] and
            ((last_call-rows[-1]['timestamp_us'])&0xffffffff)<62000),event_timeline_complete=h['event_dropped']==0,
        classifier=classifier)
    return h,rows,events,coverage

def qualify_relative_delays(h,events):
    result=prior.old.relative_delays(h)
    # A later recovered LIGHT/mean0 must not masquerade as a timed unload of
    # the load episode that was interrupted by an observer-quality reset.
    for name,begin,end in (('rise','proxy_rise_us','trend_rise_us'),('fall','proxy_rise_us','trend_fall_us')):
        if result[name+'_relative_delay_ms'] is None:continue
        reason=None
        if h['event_dropped']:reason='event_history_incomplete'
        elif any(e['event']=='quality_reset' and
                 0<((e['timestamp_us']-h[begin])&0xffffffff)<=((h[end]-h[begin])&0xffffffff)
                 for e in events):reason='quality_reset_interrupts_episode'
        if reason:
            result[name+'_unqualified_proxy_difference_ms']=result[name+'_relative_delay_ms']
            result[name+'_relative_delay_ms']=None;result[name+'_reason']=reason
    return result

def decode(row):
    normal.ORIGINAL_DECODE(row)
    ram=Path(row['ram_capture']).read_bytes();syms=base.symbols(ELF)
    address,n=syms['dob_feedback']
    row['feedback_capture']=normal.prior.fb.decode_feedback(ram[address-0x20000000:address-0x20000000+n])
    h,rows,events,coverage=decode_capture(ram,syms)
    paths={}
    for name,data in (('trend',rows),('events',events)):
        path=Path(row['receipt_path']).with_suffix('.'+name+'.csv')
        if data:
            with path.open('w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=data[0]);writer.writeheader();writer.writerows(data)
            paths[name]=dict(csv=str(path),sha256=prior.old.prior.raw.digest(path),rows=len(data))
    coverage['observer_counts_match']=h['observations']==row['feedback_capture']['updates']
    row['trend_capture']=dict(header=h,files=paths,coverage=coverage,
        relative_first_proxy=qualify_relative_delays(h,events),
        ram_sha256=prior.old.prior.raw.digest(row['ram_capture']),irq_inclusive_wall_max_us=h['max_cycles']/170,
        semantics='Same1kHz classifier throughout RUN.60ms records,0.1rpm/1mA quantization in log only; events at actual task timestamps. No physical brake/load ground truth.')

def record(mode,name,baseline,off,powered):
    row=prior.OLD_RECORD(mode,name,baseline,off,powered)
    row.update(image_sha256=SHA,elf_sha256=ELF_SHA,overspeed_trip_rpm=500,continuous_trend=True,
               normal_run_configuration=True,all_other_limits_preserved=True)
    return row

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--stage-off',action='store_true');g.add_argument('--execute-powered',type=Path)
    g.add_argument('--restore-b-drive-off',type=Path);p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--drive-off-brake-released-fixed-guarded',action='store_true')
    p.add_argument('--operator-present-drive-on-no-alarm-05a',action='store_true')
    p.add_argument('--dynamic-brake-immediately-releasable',action='store_true');a=p.parse_args(argv)
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_brake_released_fixed_guarded:p.error('Physical12V OFF required')
    if a.execute_powered and not (a.operator_present_drive_on_no_alarm_05a and a.dynamic_brake_immediately_releasable):p.error('Fresh powered/operator/no-alarm/dynamic brake confirmation required')
    source=a.execute_powered or a.restore_b_drive_off
    baseline=a.baseline_restore or (Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE)
    data=configure(baseline)
    if not a.stage_off and not source:print('OFFLINE PASS: continuous ABI2, no devices');return 0
    mode='stage' if a.stage_off else 'restore' if a.restore_b_drive_off else 'run'
    name='dob-trend-continuous-'+mode+'-'+str(time.time_ns());row=record(mode,name,baseline,a.drive_off_brake_released_fixed_guarded,a.operator_present_drive_on_no_alarm_05a)
    base.old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.restore_b_drive_off:base.restore(row,name,source,data)
        else:
            try:normal.ORIGINAL_EXECUTE(row,name,source,data)
            except RuntimeError as error:
                expected='FSM terminal '+row.get('terminal_status',{}).get('OUTCOME','UNKNOWN')+'; no-load observation is not successful tightening; no retry'
                if str(error)!=expected:raise
            row['result']=normal.classify(row)
            coverage=row['trend_capture']['coverage']
            if not coverage['observer_counts_match'] or not coverage['full_observed_run']:
                raise RuntimeError('Continuous classifier/whole-RUN record evidence incomplete; no retry')
            row['pass_']=True
            row['result']['note']='Whole-RUN shadow classification observation, no calibrated brake onset or load torque.'
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
