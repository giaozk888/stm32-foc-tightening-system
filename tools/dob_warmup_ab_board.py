"""Same-image supervised 5/3/5/3 tau normal240 trial. Files-only default.
Separate physical OFF stage, powered whole-four confirmation, OFF B restore.
No automatic retry or protection changes. Manual brake is not load ground truth.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import zlib
import dob_saturation_continue_board as prior

base=prior.base;normal=prior.normal;continuous=prior.previous;TMP=continuous.TMP
ROOT_RESTORE=TMP/'dob-trend-continuous-restore-1792823287394706500.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/DobWarmupAbCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='5d1dce6d397479a39ca80ab8b92d74f36199741f79926e53db20ba32d49614bf'
ELF_SHA='50f6c11d612f689468cb8c0fcc80926f0e74fd9a386fa2b9d340de8907a0e7cb'
SIZE=227316
SCHEDULE=(5,3,5,3)
CONFIG=dict(BW_MHZ='2000',DEFAULT_TAU='5',RAM_ONLY='1')

def image():
    data=IMAGE.read_bytes()
    if len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA:
        raise ValueError('Pinned warmup A/ELF identity mismatch')
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
    for flag in ('FOC_DOB_WARMUP_AB=1','FOC_DOB_SATURATION_CONTINUE=1','FOC_DOB_TREND_CONTINUOUS=1',
                 'FOC_NORMAL_RUN_TRIP500=1','FOC_DOB_NORMAL_CONTROL=1','FOC_DOB_CONTACT20_OBSERVE10=1',
                 'FOC_ONE_CYCLE_PWM_PIPELINE=1','FOC_DOB_ID_PRE_LPF_QUALITY=1','DOB_ADMIT_JUMP_A=.200f'):
        if '-D'+flag+' ' not in cmd:raise ValueError('Missing profile '+flag)
    for flag in ('FOC_DOB_GAIN_AB_DIAG','FOC_DOB_ID_TRACE','FOC_DOB_REAL_TRACE','FOC_MECHANICAL_HIGH_SPEED_DIAG'):
        if '-D'+flag+'=1 ' in cmd:raise ValueError('Conflicting profile '+flag)
    for name,n in dict(dob_warmup_tau=4,dob_saturation_audit=32,dob_trend_continuous=100,
                       dob_trend_continuous_arena=4,mechanical_capture=4712,dob_feedback=80,
                       mechanical_dob_monitor=856,dob_current_admission=204).items():
        if base.symbols(ELF).get(name,(0,0))[1]!=n:raise ValueError('ABI '+name)
    if base.hw.image_info(data)[0]!='A' or b'RUNDOWN240: RAM=240rpm TRIP=500rpm SAVE=OFF' not in data:
        raise ValueError('Candidate normal500 identity')
    return data

def configure(path):
    # Validate the exact latest saturation-continuity stopped-B receipt first.
    prior.configure(ROOT_RESTORE)
    for obj in (continuous,base):
        for k in ('IMAGE','ELF','SHA','ELF_SHA','SIZE'):setattr(obj,k,globals()[k])
    base.image=image;base.motion=motion;base.decode_cm=decode;base.staged=staged
    if Path(path).resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(Path(path))
    return image()

def staged(path,data):
    r=json.loads(path.read_text())
    if r.get('mode')=='stage':
        if r.get('schedule')!=list(SCHEDULE):raise ValueError('Exact four-run staged plan required')
        return normal.ORIGINAL_STAGED(path,data)
    capture=Path(r.get('final_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or capture.parent!=TMP.resolve() or r.get('mode')!='run' or
        r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
        any(r.get(k) is not True for k in ('pass_','final_outputs_off','final_cpu_halted','all_app_private_unchanged')) or
        r.get('dob_feedback_requested') is not True or r.get('start_attempts')!=1 or
        Path(r['baseline_restore_receipt']).resolve()!=base.BASE_RESTORE_RECEIPT or
        r.get('warmup_tau_requested') not in (3,5) or r.get('actual_tau_ram')!=r['warmup_tau_requested']):
        raise ValueError('Exact preceding safe warmup run required')
    content=capture.read_bytes();root=base.baseline();meta=base.old.zero.latest_meta(content)
    if (len(content)!=0x80000 or hashlib.sha256(content).hexdigest()!=r.get('final_sha256') or
        content[0x8000:0x8000+len(data)]!=data or content[:0x8000]!=root[:0x8000] or
        content[0x40000:0x7e800]!=root[0x40000:0x7e800] or content[0x7f800:]!=root[0x7f800:] or
        not base.restorable_state(meta) or meta[6:8]!=(len(data),zlib.crc32(data))):
        raise ValueError('Previous stopped Flash/B/config closure mismatch')
    return capture,content

def motion(board,row):
    tau=row['warmup_tau_requested']
    normal.check_values(board.command('MOTOR TEST MECH DOB FB CFG'),dict(normal.FB_CONFIG,ON='0'),'Boot feedback OFF')
    normal.check_values(board.command('MOTOR TEST MECH DOB WARM CFG'),dict(CONFIG,TAU='5'),'Boot default five')
    row['warmup_selection']=normal.check_values(board.command('MOTOR TEST MECH DOB WARM SET '+str(tau)),
        dict(CONFIG,TAU=str(tau)),'Idle-only warmup selection')
    row['warmup_readback']=normal.check_values(board.command('MOTOR TEST MECH DOB WARM CFG'),
        dict(CONFIG,TAU=str(tau)),'Warmup selection readback')
    try:prior.motion(board,row)
    finally:row['postflight']['MOTOR TEST MECH DOB WARM CFG']=board.command('MOTOR TEST MECH DOB WARM CFG')

def decode(row):
    continuous.decode(row)
    ram=Path(row['ram_capture']).read_bytes();symbols=base.symbols(ELF)
    a,n=symbols['dob_saturation_audit'];row['saturation_audit']=dict(zip(prior.AUDIT_KEYS,struct.unpack_from('<8I',ram,a-0x20000000)))
    a,n=symbols['dob_warmup_tau'];row['actual_tau_ram']=struct.unpack_from('<I',ram,a-0x20000000)[0]
    if row.get('start_attempts')==1 and row['actual_tau_ram']!=row['warmup_tau_requested']:
        raise ValueError('Captured warmup selection mismatch')
    audit=row['saturation_audit'];obs=row['trend_capture']['header']['observations']
    if audit['samples']!=obs or any(v>obs for k,v in audit.items() if k!='limited_valid'):
        raise ValueError('Audit/RUN count closure')

def record(mode,name,baseline,off,powered):
    row=prior.record(mode,name,baseline,off,powered)
    row.update(image_sha256=SHA,elf_sha256=ELF_SHA,schedule=list(SCHEDULE))
    return row

def run_four(stage,parent,data):
    current=stage
    for i,tau in enumerate(SCHEDULE,1):
        name='dob-warmup-ab-run-'+str(time.time_ns());row=record('run',name,parent['baseline_restore_receipt'],False,True)
        row.update(warmup_tau_requested=tau,trial_index=i)
        parent.setdefault('attempts',[]).append(row['receipt_path']);parent['last_run']=row['receipt_path']
        base.old.prior.checkpoint(row,'prepared');base.old.prior.checkpoint(parent,'run_intent')
        print('WARMUP %d/4: %dtau, 240rpm, same gain/cap/protections'%(i,tau),flush=True)
        try:
            try:normal.ORIGINAL_EXECUTE(row,name,current,data)
            except RuntimeError as error:
                expected='FSM terminal '+row.get('terminal_status',{}).get('OUTCOME','UNKNOWN')+'; no-load observation is not successful tightening; no retry'
                if str(error)!=expected:raise
            row['result']=normal.classify(row)
            c=row['trend_capture']['coverage']
            if not c['observer_counts_match'] or not c['full_observed_run']:raise RuntimeError('Whole-run evidence incomplete')
            row['pass_']=True
        except BaseException as error:
            row['failure']=str(error);raise
        finally:
            if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
                base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            base.old.prior.checkpoint(row,'complete' if row.get('pass_') else 'stopped_no_retry')
        current=Path(row['receipt_path']);parent.setdefault('runs',[]).append(row['receipt_path'])
        base.old.prior.checkpoint(parent,'run_saved')
        print('SAVED %d/4 tau%d warmup_frames=%d'%(i,tau,row['saturation_audit']['warmup_frames']),flush=True)
    parent.update(pass_=True,acquisition_complete=True,final_outputs_off=True,final_cpu_halted=True)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--stage-off',action='store_true');g.add_argument('--execute-four',type=Path)
    g.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-brake-released-fixed-guarded',action='store_true')
    p.add_argument('--operator-present-four-drive-on-no-alarm-05a',action='store_true')
    a=p.parse_args(argv)
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_brake_released_fixed_guarded:p.error('Physical12V OFF required')
    if a.execute_four and not a.operator_present_four_drive_on_no_alarm_05a:p.error('Fresh whole-four powered/no-alarm confirmation required')
    source=a.execute_four or a.restore_b_drive_off
    sr=json.loads(source.read_text()) if source else {}
    baseline=Path(sr['baseline_restore_receipt']) if source else ROOT_RESTORE
    data=configure(baseline)
    if not a.stage_off and not source:print('OFFLINE PASS: pinned 5/3/5/3 same-image; no devices');return 0
    mode='stage' if a.stage_off else 'batch' if a.execute_four else 'restore'
    name='dob-warmup-ab-'+mode+'-'+str(time.time_ns())
    parent=record(mode,name,baseline,a.drive_off_brake_released_fixed_guarded,a.operator_present_four_drive_on_no_alarm_05a)
    base.old.prior.checkpoint(parent,'prepared')
    try:
        if a.stage_off:base.stage(parent,name,data)
        elif a.restore_b_drive_off:base.restore(parent,name,source,data)
        else:
            staged(source,data) # Validate complete batch plan before any device call.
            if sr.get('mode')!='stage':raise ValueError('Fresh four-run stage receipt required')
            run_four(source,parent,data)
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
