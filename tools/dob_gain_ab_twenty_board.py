"""Supervised normal240rpm same-image gain.25/.5 x10. Files-only default.

Separate physical OFF staging, fresh powered whole-batch confirmation, and
physical OFF B restoration. Never retry a failed/protected motor trial.
"""
import argparse
import json
import math
from pathlib import Path
import statistics
import struct
import time
import zlib
import dob_real_capture_board as raw
from dob_feedback_repeat5 import metrics as prior_metrics

base=raw.base;normal=raw.normal;TMP=base.TMP
ROOT_RESTORE=TMP/'dob-real-restore-1792755294485030100.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/DobGainAbCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='b63e5bfb9662ee808f2424f75512de3ef4135ad0f9fd2365722f2c6f28357535'
ELF_SHA='996078b0b396450e5c0b79984309eec59506b3f7831bffac79aec416b5f71f84'
SIZE=224228
SCHEDULE=(.25,.5)*10
ORIGINAL_RAW_DECODE=raw.decode


def image():
    data=IMAGE.read_bytes()
    if len(data)!=SIZE or raw.digest(IMAGE)!=SHA or raw.digest(ELF)!=ELF_SHA:
        raise ValueError('Exact pinned gain A/B image required')
    cmd=next(x['command'] for x in json.loads((IMAGE.parent/'compile_commands.json').read_text()) if x['file'].endswith('/Core/Src/main.c'))
    for flag in ['FOC_DOB_GAIN_AB_DIAG=1','FOC_DOB_REAL_TRACE=1','FOC_DOB_NORMAL_CONTROL=1',
                 'FOC_DOB_CONTACT20_OBSERVE10=1','DOB_ADMIT_JUMP_A=.200f','FOC_ONE_CYCLE_PWM_PIPELINE=1']:
        if '-D'+flag+' ' not in cmd:raise ValueError('Required profile '+flag)
    syms=base.symbols(ELF)
    if syms.get('dob_gain_ab',(0,0))[1]!=4:raise ValueError('Gain selection ABI')
    for key,n in [('dob_real_trace',84),('dob_real_points',4),('dob_feedback',80),('mechanical_capture',4712)]:
        if syms.get(key,(0,0))[1]!=n:raise ValueError('Original ABI '+key)
    if base.hw.image_info(data)[0]!='A':raise ValueError('Candidate A only')
    return data


def configure(path):
    raw.configure(ROOT_RESTORE) # Previous raw image / original B identity first.
    for obj in (raw,base):
        for k in ['IMAGE','ELF','SHA','ELF_SHA','SIZE']:setattr(obj,k,globals()[k])
        obj.image=image
    base.motion=motion;base.decode_cm=decode;base.staged=staged
    if path.resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(path)
    return image()


def staged(path,data):
    r=json.loads(path.read_text())
    if r.get('mode')=='stage':return normal.ORIGINAL_STAGED(path,data)
    capture=Path(r.get('final_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or capture.parent!=TMP.resolve() or r.get('mode')!='run' or
        r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
        any(r.get(k) is not True for k in ['pass_','final_outputs_off','final_cpu_halted','all_app_private_unchanged']) or
        r.get('dob_feedback_requested') is not True or r.get('start_attempts')!=1 or
        Path(r['baseline_restore_receipt']).resolve()!=base.BASE_RESTORE_RECEIPT or
        r.get('dob_gain_requested') not in (.25,.5) or r.get('actual_gain_ram')!=r['dob_gain_requested']):
        raise ValueError('Exact preceding safe gain A/B run required')
    content=capture.read_bytes();root=base.baseline();meta=base.old.zero.latest_meta(content)
    if (len(content)!=0x80000 or raw.digest(capture)!=r.get('final_sha256') or
        content[0x8000:0x8000+len(data)]!=data or content[:0x8000]!=root[:0x8000] or
        content[0x40000:0x7e800]!=root[0x40000:0x7e800] or content[0x7f800:]!=root[0x7f800:] or
        not base.restorable_state(meta) or meta[6:8]!=(len(data),zlib.crc32(data))):
        raise ValueError('Previous Flash/B/config/metadata closure mismatch')
    return capture,content


def motion(board,row):
    gain=row['dob_gain_requested'];ppm=str(round(gain*1e6))
    normal.check_values(board.command('MOTOR TEST MECH DOB FB CFG'),
                        dict(normal.FB_CONFIG,ON='0',GAIN_PPM='250000'),'Boot default OFF gain0.25')
    row['gain_selection']=normal.check_values(board.command('MOTOR TEST MECH DOB FB GAIN '+ppm),
        dict(GAIN_PPM=ppm,ON='0',RAM_ONLY='1'),'Guarded gain selection')
    normal.FB_CONFIG=dict(normal.FB_CONFIG,ON='1',GAIN_PPM=ppm)
    row['dob_on']=normal.check_values(board.command('MOTOR TEST MECH DOB FB ON'),normal.FB_CONFIG,'Guarded DOB ON')
    try:
        raw.motion(board,row) # Same original preflight/START/8s FSM and protection path.
    finally:
        for command in ['MOTOR TEST MECH DOB STATS','MOTOR TEST MECH DOB ADMIT GAPS']:
            row['postflight'][command]=board.command(command)


def decode(row):
    ORIGINAL_RAW_DECODE(row)
    memory=Path(row['ram_capture']).read_bytes();address,n=base.symbols(ELF)['dob_gain_ab']
    if n!=4:raise ValueError('Gain RAM ABI')
    row['actual_gain_ram']=struct.unpack_from('<f',memory,address-0x20000000)[0]
    if row.get('start_attempts')==1 and row['actual_gain_ram']!=row['dob_gain_requested']:
        raise ValueError('Actual saved gain differs from requested gain')


def metrics(row):
    m=prior_metrics(row)
    stats=base.hw.fields(row.get('postflight',{}).get('MOTOR TEST MECH DOB STATS',''))
    if int(stats.get('N','0'))>0:
        m['dob_valid_fraction']=int(stats['GOOD'])/int(stats['N'])
    p=row.get('raw_capture',{}).get('csv')
    if p:
        import csv
        with open(p,newline='',encoding='utf-8') as f:points=list(csv.DictReader(f))
        values=[float(x['mechanical_rpm']) for x in points]
        m['fixed_window_speed_mae_rpm']=statistics.mean(abs(240-x) for x in values)
        m['fixed_window_speed_mean_rpm']=statistics.mean(values)
        m['fixed_window_dob_valid_fraction']=sum(x['dob_valid']=='True' for x in points)/len(points)
    else:m.update(fixed_window_speed_mae_rpm=None,fixed_window_speed_mean_rpm=None,fixed_window_dob_valid_fraction=None)
    return m


def summarize(rows):
    groups={};pairs=[]
    for gain in (.25,.5):
        rr=[metrics(r) for r in rows if r['dob_gain_requested']==gain];stats={}
        for key in metrics({}):
            values=[m[key] for m in rr if m[key] is not None and math.isfinite(m[key])]
            stats[key]=dict(n=len(values),mean=statistics.mean(values) if values else None,
                sd=statistics.stdev(values) if len(values)>1 else None)
        groups[str(gain)]=dict(runs=len(rr),metrics=stats)
    for i in range(0,len(rows)-1,2):
        a,b=rows[i:i+2]
        if (a['dob_gain_requested'],b['dob_gain_requested'])!=(.25,.5):raise ValueError('Pair schedule')
        ma,mb=metrics(a),metrics(b)
        pairs.append(dict(pair=i//2+1,gain025=a['receipt_path'],gain050=b['receipt_path'],
            gain050_minus_gain025={k:mb[k]-ma[k] if ma[k] is not None and mb[k] is not None else None for k in ma}))
    return dict(groups=groups,pairs=pairs,primary='acceleration MAE and cruise MAE, not stable-confirmation delay',
        load_ground_truth_available=False,note='Same-image unloaded paired comparison, not calibrated load rejection or tightening validation')


def execute_twenty(stage,parent,verified_prefix=None):
    current=stage;rows=list(verified_prefix or [])
    if rows:
        if not parent.get('manual_resume_authorized') or len(rows)!=9 or [r['dob_gain_requested'] for r in rows]!=list(SCHEDULE[:9]):
            raise ValueError('Exact manually authorized nine-run prefix required')
        parent['runs']=[r['receipt_path'] for r in rows]
        parent['attempts']=list(parent['runs'])
    for i in range(len(rows)+1,len(SCHEDULE)+1):
        gain=SCHEDULE[i-1]
        name='dob-gain-ab-run-'+str(time.time_ns());row=record('run',name,parent['baseline_restore_receipt'],False,True)
        row.update(dob_gain_requested=gain,trial_index=i)
        parent.setdefault('attempts',[]).append(row['receipt_path']);parent['last_run']=row['receipt_path']
        base.old.prior.checkpoint(row,'prepared');base.old.prior.checkpoint(parent,'run_intent')
        print('GAIN %d/20 %.2f 240rpm; cap25mA totalIq500mA'%(i,gain),flush=True)
        try:
            raw.run_one(row,name,current,image())
            if not row.get('pass_') or row.get('actual_gain_ram')!=gain:raise ValueError('Run/gain evidence failed')
        except BaseException as error:
            row['pass_']=False;row['failure']=str(error);raise
        finally:
            if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
                base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            base.old.prior.checkpoint(row,'complete' if row.get('pass_') else 'stopped_no_retry')
        rows.append(row);current=Path(row['receipt_path']);parent['runs']=[r['receipt_path'] for r in rows]
        parent['comparison']=summarize(rows);base.old.prior.checkpoint(parent,'run_saved')
        print('SAVED %d/20 gain%.2f accelMAE=%s'%(i,gain,metrics(row)['accel_mae_rpm']),flush=True)
    parent.update(pass_=True,acquisition_complete=True,comparison=summarize(rows),
                  final_outputs_off=True,final_cpu_halted=True)


def record(mode,name,baseline,off,powered):
    return dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],postflight={},
        image_sha256=SHA,elf_sha256=ELF_SHA,baseline_restore_receipt=str(Path(baseline).resolve()),
        start_attempts=0,automatic_retry=False,automatic_parameter_write=False,friction_enabled=True,
        physical_power_off=off,powered_no_alarm=powered,dob_feedback_requested=True,
        speed_target_rpm=240,iq_limit_a=.5,dob_cap_a=.025,host_max_seconds=base.HOST_MAX_SECONDS)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--stage-off',action='store_true');g.add_argument('--execute-twenty',type=Path);g.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-unloaded-fixed-guarded',action='store_true')
    p.add_argument('--operator-present-twenty-drive-on-no-alarm-05a',action='store_true')
    args=p.parse_args(argv)
    if (args.stage_off or args.restore_b_drive_off) and not args.drive_off_unloaded_fixed_guarded:p.error('Fresh physical12V OFF required')
    if args.execute_twenty and not args.operator_present_twenty_drive_on_no_alarm_05a:p.error('Fresh powered whole20 confirmation required')
    source=args.execute_twenty or args.restore_b_drive_off
    sr=json.loads(source.read_text()) if source else {}
    baseline=Path(sr['baseline_restore_receipt']) if source else ROOT_RESTORE
    data=configure(baseline)
    if not args.stage_off and not source:print('OFFLINE PASS: pinned same-image .25/.5 x10; no devices');return 0
    mode='stage' if args.stage_off else 'batch' if args.execute_twenty else 'restore'
    name='dob-gain-ab-'+mode+'-'+str(time.time_ns());parent=record(mode,name,baseline,args.drive_off_unloaded_fixed_guarded,args.operator_present_twenty_drive_on_no_alarm_05a)
    parent['schedule']=list(SCHEDULE);base.old.prior.checkpoint(parent,'prepared')
    try:
        if args.stage_off:base.stage(parent,name,data)
        elif args.restore_b_drive_off:base.restore(parent,name,source,data)
        else:
            if sr.get('mode')!='stage' or sr.get('schedule')!=list(SCHEDULE):raise ValueError('Exact whole20 stage plan required')
            execute_twenty(source,parent)
    except BaseException as error:
        parent['failure']=str(error)
        if parent.get('hardware_attempted') and not parent.get('final_cpu_halted'):
            try:base.hw.emergency_off(parent,TMP/(name+'-failed.bin'))
            except Exception as off:parent['cleanup_error']=str(off)
    base.old.prior.checkpoint(parent,'complete' if parent['pass_'] else 'stopped')
    print(('PASS: ' if parent['pass_'] else 'STOPPED: ')+parent['receipt_path'],flush=True)
    if parent.get('failure'):print(parent['failure'],flush=True)
    return 0 if parent['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
