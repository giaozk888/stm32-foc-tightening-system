"""Exact manual continuation of known host-interrupted gain batch; no retries.

Only nine completed actual runs may be reused. The tenth original attempt
must have sent NO START, with independent emergency-OFF/halt evidence. Any
motor protection, START attempt, different batch or missing proof forbids this
path. Restore/stage with physical12V OFF; execute requires separate fresh ON.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib
import dob_gain_ab_twenty_board as b

ORIGINAL=b.TMP/'dob-gain-ab-batch-1792761485941598100.json'
INTERRUPTED=b.TMP/'dob-gain-ab-run-1792761887740001700.json'
SAFE=b.TMP/'dob-gain-ab-interrupted-safe-1792762003887427100.bin'


def verified_original():
    parent=json.loads(ORIGINAL.read_text());x=json.loads(INTERRUPTED.read_text())
    expected='Host turn interrupted before completion; no automatic retry'
    if (parent.get('pass_') or parent.get('failure')!=expected or parent.get('last_run')!=str(INTERRUPTED) or
        len(parent.get('runs',[]))!=9 or len(parent.get('attempts',[]))!=10 or
        parent['attempts']!=parent['runs']+[str(INTERRUPTED)] or
        x.get('failure')!=expected or x.get('start_attempts')!=0 or
        x.get('final_backup')!=str(SAFE) or x.get('final_outputs_off') is not True or x.get('final_cpu_halted') is not True):
        raise ValueError('Only exact no-START host interruption may continue')
    root=json.loads(b.ROOT_RESTORE.read_text());baseline=Path(root['final_capture']).read_bytes()
    if b.raw.digest(root['final_capture'])!=root['final_sha256']:raise ValueError('Root snapshot hash')
    safe=SAFE.read_bytes();meta=b.base.old.zero.latest_meta(safe);image=b.image()
    if (len(safe)!=0x80000 or safe[0x8000:0x8000+len(image)]!=image or
        safe[:0x8000]!=baseline[:0x8000] or safe[0x40000:0x7e800]!=baseline[0x40000:0x7e800] or
        safe[0x7f800:]!=baseline[0x7f800:] or not b.base.restorable_state(meta) or
        meta[6:8]!=(len(image),zlib.crc32(image))):raise ValueError('Interrupted safe Flash closure')
    rows=[];pins=[]
    for i,path in enumerate(parent['runs']):
        r=json.loads(Path(path).read_text());b.normal.classify(r)
        if (r.get('image_sha256')!=b.SHA or r.get('elf_sha256')!=b.ELF_SHA or r.get('pass_') is not True or
            r.get('trial_index')!=i+1 or r.get('dob_gain_requested')!=b.SCHEDULE[i] or r.get('actual_gain_ram')!=b.SCHEDULE[i]):
            raise ValueError('Completed prefix identity/gain')
        flash=Path(r['final_capture']).read_bytes();ram=Path(r['ram_capture']).read_bytes()
        address,size=b.base.symbols(b.ELF)['dob_gain_ab']
        if (b.raw.digest(r['final_capture'])!=r['final_sha256'] or b.raw.digest(r['ram_capture'])!=r['raw_capture']['ram_sha256'] or
            size!=4 or struct.unpack_from('<f',ram,address-0x20000000)[0]!=b.SCHEDULE[i] or
            flash[0x8000:0x8000+len(image)]!=image or flash[:0x8000]!=baseline[:0x8000] or
            flash[0x40000:0x7e800]!=baseline[0x40000:0x7e800] or flash[0x7f800:]!=baseline[0x7f800:]):
            raise ValueError('Completed prefix Flash/RAM preservation')
        if b.raw.digest(r['raw_capture']['csv'])!=r['raw_capture']['csv_sha256']:raise ValueError('Prefix raw CSV hash')
        rows.append(r);pins.append(dict(receipt=path,sha256=b.raw.digest(path)))
    return rows,pins,x,safe


def prepare_off():
    rows,pins,x,safe=verified_original();data=b.configure(b.ROOT_RESTORE)
    name='dob-gain-ab-interrupted-closure-'+str(time.time_ns())
    closure=b.record('run',name,b.ROOT_RESTORE,True,False)
    closure.update(pass_=False,safety_closure_only=True,start_attempts=0,
        final_capture=str(SAFE),final_sha256=b.raw.digest(SAFE),all_app_private_unchanged=True,
        final_outputs_off=True,final_cpu_halted=True,source_interrupted_receipt=str(INTERRUPTED),
        source_interrupted_receipt_sha256=b.raw.digest(INTERRUPTED),source_completed_runs=pins)
    b.base.old.prior.checkpoint(closure,'derived_file_proof_not_a_motor_run')
    name='dob-gain-ab-resume-restore-'+str(time.time_ns())
    restore=b.record('restore',name,b.ROOT_RESTORE,True,False)
    b.base.old.prior.checkpoint(restore,'prepared')
    try:b.base.restore(restore,name,Path(closure['receipt_path']),data)
    except BaseException as error:
        restore['failure']=str(error)
        if restore.get('hardware_attempted') and not restore.get('final_cpu_halted'):
            b.base.hw.emergency_off(restore,b.TMP/(name+'-failed.bin'))
        b.base.old.prior.checkpoint(restore,'stopped_no_retry');raise
    b.base.old.prior.checkpoint(restore,'complete')
    print('RESTORE PASS: '+restore['receipt_path'],flush=True)
    b.base.configure_baseline(Path(restore['receipt_path']))
    name='dob-gain-ab-remaining-stage-'+str(time.time_ns())
    stage=b.record('stage',name,restore['receipt_path'],True,False)
    stage.update(schedule=list(b.SCHEDULE),resume_original_batch=str(ORIGINAL),
        original_batch_sha256=b.raw.digest(ORIGINAL),reused_run_hashes=pins,
        resumed_after_host_interruption=True,reuse_count=9,remaining_count=11,
        interrupted_attempt=str(INTERRUPTED),interrupted_attempt_sha256=b.raw.digest(INTERRUPTED))
    b.base.old.prior.checkpoint(stage,'prepared')
    try:b.base.stage(stage,name,data)
    except BaseException as error:
        stage['failure']=str(error)
        if stage.get('hardware_attempted') and not stage.get('final_cpu_halted'):
            b.base.hw.emergency_off(stage,b.TMP/(name+'-failed.bin'))
        b.base.old.prior.checkpoint(stage,'stopped_no_retry');raise
    b.base.old.prior.checkpoint(stage,'complete')
    print('STAGE PASS: '+stage['receipt_path'],flush=True)
    return stage


def execute_remaining(path,powered):
    if not powered:raise ValueError('Fresh powered/operator/no-alarm whole11 confirmation required')
    stage=json.loads(path.read_text());rows,pins,x,safe=verified_original()
    if (stage.get('pass_') is not True or stage.get('mode')!='stage' or stage.get('resume_original_batch')!=str(ORIGINAL) or
        stage.get('original_batch_sha256')!=b.raw.digest(ORIGINAL) or stage.get('reused_run_hashes')!=pins or
        stage.get('interrupted_attempt_sha256')!=b.raw.digest(INTERRUPTED) or stage.get('schedule')!=list(b.SCHEDULE) or
        stage.get('reuse_count')!=9 or stage.get('remaining_count')!=11):raise ValueError('Exact safe remaining-stage plan required')
    baseline=Path(stage['baseline_restore_receipt']);b.configure(baseline)
    name='dob-gain-ab-remaining-batch-'+str(time.time_ns())
    parent=b.record('batch',name,baseline,False,True)
    parent.update(schedule=list(b.SCHEDULE),manual_resume_authorized=True,resume_original_batch=str(ORIGINAL),
        original_batch_sha256=b.raw.digest(ORIGINAL),reused_run_hashes=pins,
        interrupted_no_start_receipt=str(INTERRUPTED),reused_runs=9,new_runs_planned=11,
        pairing_pause_after_trial=9,interrupted_attempt_not_counted_as_completed=True)
    b.base.old.prior.checkpoint(parent,'prepared')
    try:b.execute_twenty(path,parent,verified_prefix=rows)
    except BaseException as error:parent['failure']=str(error)
    b.base.old.prior.checkpoint(parent,'complete' if parent['pass_'] else 'stopped_no_retry')
    print(('PASS: ' if parent['pass_'] else 'STOPPED: ')+parent['receipt_path'],flush=True)
    if parent.get('failure'):print(parent['failure'],flush=True)
    return parent


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--prepare-off',action='store_true');g.add_argument('--execute-eleven',type=Path)
    p.add_argument('--drive-off-unloaded-fixed-guarded',action='store_true')
    p.add_argument('--operator-present-eleven-drive-on-no-alarm-05a',action='store_true')
    a=p.parse_args(argv)
    if a.prepare_off and not a.drive_off_unloaded_fixed_guarded:p.error('Fresh physical12V OFF required')
    if a.execute_eleven and not a.operator_present_eleven_drive_on_no_alarm_05a:p.error('Fresh powered whole11 confirmation required')
    if a.prepare_off:prepare_off();return 0
    if a.execute_eleven:return 0 if execute_remaining(a.execute_eleven,True)['pass_'] else 1
    rows,pins,x,safe=verified_original();print('OFFLINE PASS:9 exact completed runs + no-START interruption;11 remaining, no device access');return 0


if __name__=='__main__':raise SystemExit(main())
