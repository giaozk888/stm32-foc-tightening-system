"""Pinned CUR_CONFIRM ComputeOnly verification. Default: offline, no devices.

Never sends START, changes a threshold, or force-confirms an application.
Recovery selects the already-confirmed B through the existing bootloader.
Full Flash/SRAM captures stay in the existing private evidence directory.
"""
import argparse
import json
import struct
import subprocess
import time
from pathlib import Path

import timeout_diagnostics_board_test as base

old, prior, tx = base.old, base.prior, base.tx
ROOT, OUTPUT, PRIVATE = base.ROOT, base.OUTPUT, base.PRIVATE
IMAGE = ROOT/'foc2_app_a/build/FastCurrentRejectComputeOnly/foc2.bin'
ELF = IMAGE.with_suffix('.elf')
SHA = '1cbe43061f7879e5550d0db9301c739c2e00ca213e1ec1a3acb12e3fff5a0bdf'
ELF_SHA = '386a5dea822b590e50d2b75ab1f2c72148883b219223dc11360650470c706fc7'
SIZE = 227492
PREFIX = 'cur-confirm-'
PRIOR_TRIAL = OUTPUT/'timeout-diag-trial-1792199446456485400.json'
PRIOR_FULL_SHA = 'f06c1e6a6e9cce862dde1e3b4206b32c0eed6bfffc19b91902d52fe145626832'
OLD_SHA, OLD_SIZE = base.SHA, base.SIZE
OFFLINE = ROOT/'tests/foc_adaptive_build/cur_confirm_cycles_evidence/receipt.json'
LAYOUT_FILE = ROOT/'tests/foc_adaptive_build/cur_confirm_layout.bin'
ARM_LAYOUT = (300,116,117,119,124,128,132,136,140)
STAT_NAMES = ('cur_confirm_enter_count','cur_confirm_clear_count','cur_confirm_fault_count',
              'cur_confirm_max_cycles','cur_confirm_max_elapsed_us')


def image():
    data=IMAGE.read_bytes()
    receipt=json.loads(OFFLINE.read_text('utf-8'))
    if (len(data)!=SIZE or tx.digest(data)!=SHA or tx.digest(ELF.read_bytes())!=ELF_SHA or
            prior.image_info(data)[0]!='A' or receipt.get('hardware_test_performed') is not False or
            len(receipt.get('tests',[]))!=7 or
            not all(test.get('passed') is True for test in receipt['tests']) or
            not any(b.get('sha256')==SHA and b.get('flash_bytes')==SIZE for b in receipt['builds'])):
        raise ValueError('Exact offline-tested CUR_CONFIRM ComputeOnly BIN/ELF required')
    for marker in (b'NAME=FAST_CURRENT_REJECT HARD_OFF=1', b'METHOD=TWO_SAMPLE',
                   b'FILTER=NONE OC=RAW_CONFIRM_4',b'FAULT SNAPSHOT TIMEOUT_SUBREASON='):
        if marker not in data: raise ValueError('Missing hard-off/current/snapshot identity')
    return data


def configure(receipt):
    """Rebind this process only; retain all full-Flash/metadata/page checks."""
    path=Path(receipt).resolve()
    if path.parent!=OUTPUT.resolve() or not path.name.startswith(PREFIX+'restore-'):
        raise ValueError('This acceptance run requires its verified B restoration receipt')
    row=json.loads(path.read_text('utf-8'))
    meta=tuple(row.get('final_metadata',()))
    if (not row.get('pass_') or meta[2:5]!=(2,0,0) or meta[8:10]!=(210916,453748590) or
            row.get('host_motor_commands')!=0):
        raise ValueError('Restored unchanged confirmed B required')
    values=dict(IMAGE=IMAGE,ELF=ELF,SHA=SHA,ELF_SHA=ELF_SHA,SIZE=SIZE,PREFIX=PREFIX,
                BASE_RECEIPT=path,BASE_SHA=row['final_sha256'],BASE_META=meta)
    for module in (base,old,prior,tx):
        for key,value in values.items(): setattr(module,key,value)
        module.image=image
    tx.baseline()  # Verifies full capture, receipt, metadata and preserved B SHA.


def ram_symbol(name):
    image()
    result=subprocess.run([str(ROOT.parent/'software/arm/bin/arm-none-eabi-nm.exe'),'-S',str(ELF)],
                          capture_output=True,text=True,check=True,timeout=15)
    for line in result.stdout.splitlines():
        words=line.split()
        if len(words)==4 and words[3]==name: return int(words[0],16),int(words[1],16)
    raise ValueError('Missing current protection RAM symbol: '+name)


def symbols():
    return ram_symbol('cl_safety')


def decode_cycles(ram):
    if len(ram)!=0x20000: raise ValueError('Complete SRAM capture required')
    address,size=ram_symbol('cl_current_cycles')
    if size!=36 or not 0x20000000<=address<=0x20020000-size:
        raise ValueError('Unexpected pinned FocCurrentCycleStats schema')
    names=('last_cycles','max_cycles','normal_last_cycles','normal_max_cycles',
           'suspect_last_cycles','suspect_max_cycles','unresolved_last_cycles',
           'unresolved_max_cycles','deadline_miss_count')
    result=dict(zip(names,struct.unpack_from('<9I',ram,address-0x20000000)))
    result.update(address=hex(address),elf_sha256=ELF_SHA,
                  max_us=result['max_cycles']/170.0)
    return result


def layout():
    data=LAYOUT_FILE.read_bytes()
    if len(data)!=36: raise ValueError('ARM-compiled confirmation layout missing')
    values=struct.unpack('<9I',data)
    address,size=symbols()
    if values!=ARM_LAYOUT or values[0]!=size or not 0x20000000<=address<0x20020000-size:
        raise ValueError('ARM layout does not match pinned ELF RAM')
    return address,values


def decode_confirmation(ram):
    if len(ram)!=0x20000: raise ValueError('Complete SRAM capture required')
    address,offsets=layout()
    start=address-0x20000000
    result={name:struct.unpack_from('<I',ram,start+offset)[0]
            for name,offset in zip(STAT_NAMES,offsets[4:])}
    result.update(pending=ram[start+offsets[1]],good_samples=ram[start+offsets[2]],
                  confirm_cycles=ram[start+offsets[3]],clear_good_samples=2,max_cycles_limit=4,
                  address=hex(address),elf_sha256=ELF_SHA)
    if result['cur_confirm_max_cycles']>4 or result['confirm_cycles']>4:
        raise ValueError('Confirmation cycle count outside configured budget')
    result['confirmation_exercised']=result['cur_confirm_enter_count']>0
    return result


def recover_prior(row,run):
    previous=json.loads(PRIOR_TRIAL.read_text('utf-8'))
    if previous.get('final_sha256')!=PRIOR_FULL_SHA or previous.get('image_sha256')!=OLD_SHA:
        raise ValueError('Exact prior stopped timeout trial required')
    raw=tx.prior.private_path(previous['final_backup']).read_bytes()
    data=raw[0x8000:0x8000+OLD_SIZE]
    if tx.digest(raw)!=PRIOR_FULL_SHA or tx.digest(data)!=OLD_SHA:
        raise ValueError('Prior capture/image changed')
    row.update(image_sha256=OLD_SHA,image_bytes=OLD_SIZE,source_trial=str(PRIOR_TRIAL))
    # Existing restore checks actual Flash before reset and only requests the
    # already-confirmed B; it stops at B entry before any app instruction.
    tx.restore(row,run,data,PRIOR_TRIAL)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--recover-prior-trial',action='store_true')
    mode.add_argument('--stage-inactive-a',action='store_true')
    mode.add_argument('--trial-from-stage',type=Path)
    mode.add_argument('--restore-from-trial',type=Path)
    parser.add_argument('--baseline-receipt',type=Path)
    parser.add_argument('--drive-12v-off-motor-disconnected',action='store_true')
    parser.add_argument('--drive-12v-on-motor-disconnected',action='store_true')
    args=parser.parse_args()
    data=image(); layout()
    operation=('restore-prior' if args.recover_prior_trial else 'stage' if args.stage_inactive_a
               else 'trial' if args.trial_from_stage else 'restore' if args.restore_from_trial else None)
    if operation is None:
        print('OFFLINE PASS: pinned CUR_CONFIRM ComputeOnly, ARM layout, no hardware')
        return 0
    if operation=='trial':
        if not args.drive_12v_on_motor_disconnected: parser.error('Powered drive, motor disconnected required')
    elif not args.drive_12v_off_motor_disconnected:
        parser.error('Physical drive 12 V off, motor disconnected required')
    if operation!='restore-prior':
        if not args.baseline_receipt: parser.error('Verified B baseline receipt required')
        configure(args.baseline_receipt)
    run=PREFIX+operation+'-'+str(time.time_ns())
    row=dict(pass_=False,mode='restore' if operation=='restore-prior' else operation,
             image_sha256=SHA,elf_sha256=ELF_SHA,image_bytes=SIZE,steps=[],samples=[],
             hardware_attempted=False,programming_attempted=False,motor_commands=0,host_motor_commands=0,
             trial_requests=0,force_confirmation=False,direct_metadata_write=False,
             automatic_retry=False,activation=False)
    try:
        if operation=='restore-prior': recover_prior(row,run)
        elif operation=='stage': prior.stage(row,run,data)
        elif operation=='trial': old.trial(row,run,data,args.trial_from_stage)
        else: tx.restore(row,run,data,args.restore_from_trial)
    except BaseException as error:
        row.update(pass_=False,failure=str(error))
        print('FAILED: '+str(error),flush=True)
        if (row.get('programming_attempted') or row.get('restore_attempted')) and not row.get('final_cpu_halted'):
            try: prior.emergency_off(row,PRIVATE/(run+'-cleanup.bin'))
            except BaseException as cleanup: row['cleanup_failure']=str(cleanup)
    finally:
        if row.get('ram_backup'):
            try:
                base.decode_trial_snapshot(row,data)
                if not row.get('snapshot_not_decoded'):
                    ram=tx.prior.private_path(row['ram_backup']).read_bytes()
                    row['cur_confirm']=decode_confirmation(ram)
                    row['foc_profile_ram']=decode_cycles(ram)
            except BaseException as error: row.update(pass_=False,decode_failure=str(error))
        path=OUTPUT/(run+'.json')
        path.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(path),flush=True)
        if not row['pass_']:
            for step in row['steps']: print(step['output'],flush=True)
        if row.get('cur_confirm'): print(json.dumps(row['cur_confirm'],indent=2),flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':
    raise SystemExit(main())
