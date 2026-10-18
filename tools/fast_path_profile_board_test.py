"""Pinned hard-off FOC phase-profile board acceptance; offline by default.

Reuses inactive-A/page/full-Flash/bootloader checks, never sends motor START.
Historical runners and their pinned identities remain unchanged on disk.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

import cur_confirm_cycles_board_test as confirm

old, prior, tx = confirm.old, confirm.prior, confirm.tx
ROOT, OUTPUT, PRIVATE = confirm.ROOT, confirm.OUTPUT, confirm.PRIVATE
IMAGE = ROOT/'foc2_app_a/build/FastPathTiming/foc2.bin'
ELF = IMAGE.with_suffix('.elf')
SHA = '69f98bc70f9216ed33d9e16af9cc3b9e06b65ac363a0cbc84d57727e5ef610e7'
ELF_SHA = '3e12f18329d567ea688e5d3577ced86a93fa1917bd8d168b69bec98fe147b774'
SIZE = 229220
PREFIX = 'fast-path-profile-'
BASE_RECEIPT = OUTPUT/'cur-confirm-restore-1792202223657456700.json'
BASE_SHA = '012311c63addd8cc2b5bdb9a6d0f87e31f3e86a5c3e324e6bc2f89e035088d85'
BASE_META = (1112493908,3,2,0,0,592,227492,507841119,210916,453748590,0,621775197)


def image():
    data = IMAGE.read_bytes()
    if (len(data)!=SIZE or tx.digest(data)!=SHA or tx.digest(ELF.read_bytes())!=ELF_SHA or
            prior.image_info(data)[0]!='A'):
        raise ValueError('Exact offline-tested hard-off FastPathTiming BIN/ELF required')
    for marker in (b'NAME=FAST_CURRENT_REJECT HARD_OFF=1',b'METHOD=TWO_SAMPLE',
                   b'FILTER=NONE OC=RAW_CONFIRM_4',b'FAULT SNAPSHOT TIMEOUT_SUBREASON='):
        if marker not in data: raise ValueError('Missing hard-off/control/protection identity')
    return data


def configure():
    # Process-local binding only. Reuse EVERY existing full capture/erase-page,
    # metadata, fallback and halted/output-off gate without relaxing one.
    values=dict(IMAGE=IMAGE,ELF=ELF,SHA=SHA,ELF_SHA=ELF_SHA,SIZE=SIZE,PREFIX=PREFIX,
                BASE_RECEIPT=BASE_RECEIPT,BASE_SHA=BASE_SHA,BASE_META=BASE_META)
    for module in (confirm,confirm.base,old,prior,tx):
        for key,value in values.items(): setattr(module,key,value)
        module.image=image


def verify_symbols():
    image()
    confirm.layout()
    for name,size in (('foc_path_profile',168),('foc_pwm_write_profile',128),
            ('foc_pwm_duty_profile',128),('foc_profile_irq_max',16),
            ('foc_profile_irq_calls',16),('cl_current_cycles',36)):
        address,actual=confirm.ram_symbol(name)
        if actual!=size or not 0x20000000<=address<=0x20020000-size:
            raise ValueError('Unexpected pinned profile RAM schema: '+name)
    confirm.base.symbols()


def decode(row,data):
    if not row.get('ram_backup'): return
    confirm.base.decode_trial_snapshot(row,data)
    if row.get('snapshot_not_decoded'): return
    ram=tx.prior.private_path(row['ram_backup']).read_bytes()
    row['cur_confirm']=confirm.decode_confirmation(ram)
    row['foc_profile_ram']=confirm.decode_cycles(ram)
    output=subprocess.run(['python',str(ROOT/'tools/foc_path_profile_report.py'),
        '--elf',str(ELF),'--ram',row['ram_backup'],'--flash',row['final_backup'],
        '--vtor',hex(row['snapshot_vtor'])],capture_output=True,text=True,check=True,timeout=20)
    row['fast_path_profile']=json.loads(output.stdout)
    p=row['fast_path_profile']
    row['phase_profile_observed']=p['phases']['frames']>0
    row['physical_pwm_preload_deadline_verified']=False
    if not row['phase_profile_observed'] or p['phases']['invalid']:
        raise ValueError('Missing/invalid coherent normal-path profiling evidence')
    if p['actual_ccr']['actual_ccr_writes']:
        raise ValueError('Unexpected runtime CCR publication in hard-off computation')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--stage-inactive-a',action='store_true')
    mode.add_argument('--trial-from-stage',type=Path)
    mode.add_argument('--restore-from-trial',type=Path)
    parser.add_argument('--drive-12v-off-motor-disconnected',action='store_true')
    parser.add_argument('--drive-12v-on-motor-disconnected',action='store_true')
    args=parser.parse_args()
    configure(); data=image(); verify_symbols()
    operation=('stage' if args.stage_inactive_a else 'trial' if args.trial_from_stage
               else 'restore' if args.restore_from_trial else None)
    if operation is None:
        print('OFFLINE PASS: pinned FastPathTiming, confirmation/profile schemas; no devices')
        return 0
    if operation=='trial':
        if not args.drive_12v_on_motor_disconnected: parser.error('Powered drive, motor disconnected required')
    elif not args.drive_12v_off_motor_disconnected:
        parser.error('Drive 12 V off, motor disconnected required')
    run=PREFIX+operation+'-'+str(time.time_ns())
    row=dict(pass_=False,mode=operation,image_sha256=SHA,elf_sha256=ELF_SHA,image_bytes=SIZE,
        steps=[],samples=[],hardware_attempted=False,programming_attempted=False,
        motor_commands=0,host_motor_commands=0,trial_requests=0,force_confirmation=False,
        direct_metadata_write=False,automatic_retry=False,activation=False,
        physical_pwm_preload_deadline_verified=False,motor_closed_loop_verified=False)
    try:
        tx.baseline()
        if operation=='stage': tx.stage(row,run,data)
        elif operation=='trial': old.trial(row,run,data,args.trial_from_stage)
        else: tx.restore(row,run,data,args.restore_from_trial)
    except BaseException as error:
        row.update(pass_=False,failure=str(error))
        print('FAILED: '+str(error),flush=True)
        if ((row.get('programming_attempted') or row.get('restore_attempted')) and
                not row.get('final_cpu_halted')):
            try: prior.emergency_off(row,PRIVATE/(run+'-cleanup.bin'))
            except BaseException as cleanup: row['cleanup_failure']=str(cleanup)
    finally:
        try: decode(row,data)
        except BaseException as error: row.update(pass_=False,decode_failure=str(error))
        path=OUTPUT/(run+'.json')
        path.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(path),flush=True)
        if row.get('fast_path_profile'): print(json.dumps(row['fast_path_profile'],indent=2),flush=True)
        if not row['pass_']:
            for step in row['steps']: print(step['output'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__': raise SystemExit(main())
