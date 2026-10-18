"""Restore only the preserved B after this exact stopped candidate trial.

Drive 12 V OFF required. Existing bootloader mailbox only; stop before any
B application instructions. No program, direct metadata edit or motor command.
"""
import argparse
import json
import struct
import time
import zlib

import pipeline_closed_loop_board_test as candidate
from latest_original_fsm_stage import full_compare_commands,write_mailbox,off_commands
from original_closed_loop_updated_stage import debug,off_report,check_off
from original_closed_loop_trial import emergency_off
from tighten_synthetic_swd_recovery import latest_meta

TRIAL = candidate.OUTPUT/'protected-pipeline-trial-1792228438430412700.json'


def stopped_trial(row):
    if (row.get('mode') != 'trial' or row.get('image_sha256') != candidate.SHA or
            row.get('elf_sha256') != candidate.ELF_SHA or row.get('snapshot_vtor') != 0x08008000 or
            row.get('trial_requests') != 1 or row.get('original_start_runner_invocations') != 1 or
            row.get('activation_submitted') is not True or
            any(row.get(k) is not True for k in ('final_cpu_halted','final_outputs_off',
                                               'all_app_and_private_bytes_unchanged'))):
        raise ValueError('Exact stopped candidate A trial required')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore-preserved-b',action='store_true')
    parser.add_argument('--drive-12v-off',action='store_true')
    args=parser.parse_args()
    if args.restore_preserved_b and not args.drive_12v_off:
        parser.error('Actual drive 12 V OFF required')
    data=candidate.image()
    if not args.restore_preserved_b:
        print('OFFLINE PASS: no devices/private access')
        return 0
    candidate.configure_transaction()
    previous=json.loads(TRIAL.read_text(encoding='utf-8'))
    stopped_trial(previous)
    expected=candidate.tx.prior.private_path(previous['final_backup'])
    before=expected.read_bytes()
    _,baseline=candidate.tx.baseline()
    meta=latest_meta(before)
    if (candidate.digest(before) != previous['final_sha256'] or meta[2:6] != (1,0,0,618) or
            before[0x8000:0x8000+len(data)] != data or
            before[0x40000:0x40000+meta[8]] != baseline[0x40000:0x40000+meta[8]] or
            meta[8:10] != candidate.BASE_META[8:10]):
        raise ValueError('Captured candidate/fallback/metadata mismatch')
    entry=struct.unpack_from('<I',baseline,0x40004)[0]&~1
    if not 0x08040000 <= entry < 0x08040000+meta[8]:
        raise ValueError('B entry outside preserved image')
    body=struct.pack('<7I',0x584f424d,1,3,1,2,0,0)
    mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
    run=candidate.PREFIX+'restore-'+str(time.time_ns())
    row=dict(pass_=False,mode='restore',trial=str(TRIAL),image_sha256=candidate.SHA,
        steps=[],hardware_attempted=False,motor_commands=0,flash_programming=False,
        force_confirmation=False,direct_metadata_write=False,automatic_retry=False)
    recovered=candidate.PRIVATE/(run+'-recovered.bin')
    try:
        row['hardware_attempted']=True
        output=debug(row,[*candidate.tx.prior.off_gate(0x08008000),
            *full_compare_commands(candidate.PRIVATE/(run+'-before.bin'),expected),
            'reset halt',f'bp {entry:#x} 2 hw',*write_mailbox(mailbox),
            'reset run','wait_halt 25000',f'rbp {entry:#x}',
            f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not halted at B entry"}}',
            *off_commands(),*off_report(),
            'if {[mrw 0x40012C00] & 1} {error "Timer not stopped"}',
            f'dump_image {{{recovered.as_posix()}}} 0x08000000 0x80000','halt','shutdown'])
        row['outputs']=check_off(output,(0x08040000,))
        actual=recovered.read_bytes()
        current=latest_meta(actual)
        if (len(actual) != 0x80000 or actual[:0x7e800] != before[:0x7e800] or
                actual[0x7f800:] != before[0x7f800:] or current[2:5] != (2,0,0) or
                current[5] <= meta[5] or current[6:10] != meta[6:10]):
            raise RuntimeError('Normal B selection or unchanged app/private proof failed')
        row.update(pass_=True,final_metadata=list(current),recovered_backup=str(recovered),
            final_sha256=candidate.digest(actual),all_app_and_private_bytes_unchanged=True,
            final_cpu_halted=True,final_outputs_off=True)
    except BaseException as error:
        row.update(pass_=False,failure=str(error))
        if row['hardware_attempted']:
            try:
                emergency_off(row,candidate.PRIVATE/(run+'-cleanup.bin'))
            except BaseException as cleanup:
                row['cleanup_failure']=str(cleanup)
    finally:
        path=candidate.OUTPUT/(run+'.json')
        path.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(('RESTORE PASS' if row['pass_'] else 'RESTORE FAILED')+': '+str(path),flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':
    raise SystemExit(main())
