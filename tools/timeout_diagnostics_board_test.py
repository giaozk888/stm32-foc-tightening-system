"""Pinned timeout diagnostics acceptance. Offline by default; no motor START.

Reuse the existing inactive-A/full-Flash comparison transaction. Only the
ComputeOnly image is admitted. Historical runners and receipts stay intact.
"""
import argparse
import json
import struct
import subprocess
import time

import current_impulse_board_test as old

prior, tx = old.prior, old.tx
ROOT, OUTPUT, PRIVATE = old.ROOT, old.OUTPUT, old.PRIVATE
IMAGE = ROOT / 'foc2_app_a/build/FastCurrentRejectComputeOnly/foc2.bin'
ELF = IMAGE.with_suffix('.elf')
SHA = '97820d106378bdb4479b58dbded7324fc670fbf3b141a1db35932801e9d62210'
ELF_SHA = '65579dee7dfee9cfba0b3a04e00905bc2da9e4e2a53059afd2287f7ec25c3790'
SIZE = 227476
BASE_RECEIPT = OUTPUT / 'current-impulse-restore-1792152242078681300.json'
BASE_SHA = '26fce0f814b96fa6ff95550a0b15abdc9d5cf785e05e8d1bae479e38ec0fc799'
BASE_META = (1112493908,3,2,0,0,585,225068,1769659043,210916,453748590,0,2021169684)
PREFIX = 'timeout-diag-'


def image():
    data = IMAGE.read_bytes()
    if (len(data) != SIZE or tx.digest(data) != SHA or
            tx.digest(ELF.read_bytes()) != ELF_SHA or prior.image_info(data)[0] != 'A'):
        raise ValueError('Exact offline-tested timeout ComputeOnly A BIN/ELF required')
    for marker in (b'NAME=FAST_CURRENT_REJECT HARD_OFF=1',
                   b'FAST_REJECT=1 REPAIR=0', b'METHOD=TWO_SAMPLE',
                   b'FILTER=NONE OC=RAW_2_OF_3',
                   b'FAULT SNAPSHOT TIMEOUT_SUBREASON=', b'END CPU_HZ='):
        if marker not in data:
            raise ValueError('Missing hard-off/discriminator/snapshot marker')
    return data


# The reused transaction resolves these globals at call time. No bypass of its
# page bounds, full before/after comparison, metadata or fallback validation.
for module in (old, prior, tx):
    for key in ('IMAGE','SHA','SIZE','BASE_RECEIPT','BASE_SHA','BASE_META','PREFIX'):
        setattr(module, key, globals()[key])
    module.image = image


# Capture the actual running image's VTOR in the SAME stopped debug session as
# SRAM. A staged A image alone does not mean that A owns the live RAM layout.
_debug = prior.debug


def debug_with_ram_owner(row, commands):
    capture_ram = any(command.startswith('dump_image ') and
                      command.endswith(' 0x20000000 0x20000') for command in commands)
    if capture_ram:
        commands = list(commands)
        commands.insert(-1,'echo SNAPSHOT_VTOR=[mrw 0xE000ED08]')
    output = _debug(row,commands)
    if capture_ram:
        import re
        match = re.search(r'(?m)^SNAPSHOT_VTOR=(0x[0-9a-fA-F]+)\s*$',output)
        if not match:
            raise ValueError('Missing atomic RAM owner evidence')
        row['snapshot_vtor'] = int(match[1],16)
    return output


prior.debug = debug_with_ram_owner


def decode_trial_snapshot(row, data):
    if not row.get('activation_submitted') or row.get('snapshot_vtor') != 0x08008000:
        row['snapshot_not_decoded'] = 'New A was not submitted/current; its ELF cannot decode other-image RAM'
        return
    raw = tx.prior.private_path(row['final_backup']).read_bytes()
    if raw[0x8000:0x8000+SIZE] != data:
        raise ValueError('RAM evidence image does not match new ELF')
    decoded = snapshot(tx.prior.private_path(row['ram_backup']).read_bytes())
    if decoded['valid'] not in (0,1):
        raise ValueError('Invalid first-fault publication flag')
    if decoded['valid']:
        row['fault_snapshot'] = decoded
    else:
        row['fault_snapshot'] = {'valid':0,'meaning':'No published first-fault snapshot',
                                 'address':decoded['address'],'elf_sha256':ELF_SHA}


def symbols():
    image()
    result = subprocess.run([str(ROOT.parent/'software/arm/bin/arm-none-eabi-nm.exe'),
        '-S', str(ELF)], capture_output=True, text=True, check=True, timeout=15)
    found = {}
    for line in result.stdout.splitlines():
        words = line.split()
        if len(words) == 4 and words[3] in ('foc_fault_snapshot',
                'fault_snapshot_print_index','current_hold_total','current_hold_window'):
            found[words[3]] = (int(words[0],16),int(words[1],16))
    if set(found) != {'foc_fault_snapshot','fault_snapshot_print_index',
                     'current_hold_total','current_hold_window'}:
        raise ValueError('Missing ELF diagnostics symbols')
    if found['foc_fault_snapshot'][1] != 204:
        raise ValueError('Unexpected snapshot schema size')
    return found


def snapshot(ram):
    if len(ram) != 0x20000:
        raise ValueError('Complete private SRAM capture required')
    syms = symbols()
    addr, size = syms['foc_fault_snapshot']
    offset = addr-0x20000000
    if offset < 0 or offset+size > len(ram):
        raise ValueError('ELF snapshot outside captured RAM')
    # Explicit schema tied to the exact ELF above, not a historical RAM offset.
    head = ('valid timestamp_ms domain fault_reason timeout_reason motor_mode '
            'tightening_state state_elapsed_ms').split()
    floats = ('position_deg position_target_deg position_error_deg speed_raw_rpm '
              'speed_filtered_rpm speed_command_rpm iq_ref_A iq_measured_A '
              'id_measured_A stall_elapsed_s').split()
    tail = ('contact_candidate_ms encoder_valid encoder_errors current_validator_state '
            'current_suspect_total current_confirmed_spike current_confirmed_transition '
            'current_unresolved_total current_unresolved_consecutive '
            'current_unresolved_max_consecutive foc_cycles_max foc_normal_cycles_max '
            'foc_suspect_cycles_max foc_unresolved_cycles_max foc_deadline_miss_count '
            'adc_sample_count foc_exec_count current_hold_total hold_window_count '
            'hold_window_max hold_rate_per_mille hold_window_ms evidence_present '
            'protection_flags').split()
    evidence = ('reason now_us reference_us elapsed_us limit_us last_sample_us '
                'pending_since_us pending misses').split()
    values = struct.unpack_from('<8I10f33I',ram,offset)
    names = head+floats+tail+['evidence_'+name for name in evidence]
    if len(names) != len(values):
        raise ValueError('Snapshot schema mismatch')
    result = dict(zip(names,values))
    for name in ('fault_snapshot_print_index','current_hold_total'):
        address, n = syms[name]
        if n != 4 or not 0x20000000 <= address <= 0x2001fffc:
            raise ValueError('Invalid diagnostics word symbol')
        result['live_'+name] = struct.unpack_from('<I',ram,address-0x20000000)[0]
    result['elf_sha256'] = ELF_SHA
    result['address'] = hex(addr)
    return result


def prepare_commands(expected, live, after):
    return ['init',
        'if {[mrw 0xE000ED08] != 0x08040000 && [mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Expected B or stopped bootloader"}',
        'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20]} {error "Outputs not off before prepare"}',
        *prior.full_compare_commands(live,expected),'halt',
        *prior.off_commands(),'reset halt',
        'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted bootloader"}',
        # Invalidate any stale RAM request; no Flash metadata write/commit.
        'mww 0x2001FFC0 0',*prior.off_commands(),*prior.off_report(),
        'if {[mrw 0x40012C00] & 1} {error "Timer not stopped"}',
        f'dump_image {{{after.as_posix()}}} 0x08000000 0x80000','halt','shutdown']


def prepare(row, run, data, receipt):
    expected, before = tx.load_stage(receipt,data)
    live, after = PRIVATE/(run+'-before.bin'),PRIVATE/(run+'-prepared.bin')
    row['hardware_attempted'] = True
    output = prior.debug(row,prepare_commands(expected,live,after))
    row['prepared_outputs'] = prior.transaction.check_off(output,(0,0x08000000))
    actual = after.read_bytes()
    if actual != before:
        raise ValueError('Preparing bootloader changed Flash; stop without activation')
    row.update(pass_=True,prepared_backup=str(after),final_sha256=tx.digest(actual),
        final_metadata=list(prior.latest_meta(actual)),all_flash_unchanged=True,
        final_cpu_halted=True,final_outputs_off=True,activation=False,
        mailbox_invalidated=True,trial_requests=0)
    print('PREPARE PASS: exact staged image; bootloader halted; no activation/programming',flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--stage-inactive-a',action='store_true')
    mode.add_argument('--trial-from-stage',type=tx.Path)
    mode.add_argument('--restore-from-trial',type=tx.Path)
    mode.add_argument('--prepare-from-stage',type=tx.Path)
    parser.add_argument('--drive-12v-off-motor-disconnected',action='store_true')
    parser.add_argument('--drive-12v-on-motor-disconnected',action='store_true')
    args = parser.parse_args()
    data = image()
    symbols()
    operation = ('prepare' if args.prepare_from_stage else
                 'stage' if args.stage_inactive_a else 'trial' if args.trial_from_stage
                 else 'restore' if args.restore_from_trial else None)
    if operation is None:
        print('OFFLINE PASS: exact timeout ComputeOnly BIN/ELF, snapshot 204 B; no hardware')
        return 0
    if operation in ('stage','restore','prepare') and not args.drive_12v_off_motor_disconnected:
        parser.error('Actual drive power off and motor disconnected required')
    if operation == 'trial' and not args.drive_12v_on_motor_disconnected:
        parser.error('Actual powered drive and disconnected motor required')
    run = PREFIX+operation+'-'+str(time.time_ns())
    row = dict(pass_=False,mode=operation,image_sha256=SHA,elf_sha256=ELF_SHA,
        image_bytes=SIZE,steps=[],samples=[],hardware_attempted=False,
        programming_attempted=False,motor_commands=0,trial_requests=0,
        force_confirmation=False,direct_metadata_write=False,automatic_retry=False,
        activation=False)
    try:
        tx.baseline()
        if operation == 'stage':
            prior.stage(row,run,data)
        elif operation == 'prepare':
            prepare(row,run,data,args.prepare_from_stage)
        elif operation == 'trial':
            old.trial(row,run,data,args.trial_from_stage)
        else:
            tx.restore(row,run,data,args.restore_from_trial)
    except BaseException as error:
        row.update(pass_=False,failure=str(error))
        print('FAILED: '+str(error),flush=True)
        if ((row.get('programming_attempted') or row.get('restore_attempted') or
             (operation == 'prepare' and row.get('hardware_attempted')))
                and not row.get('final_cpu_halted')):
            try:
                prior.emergency_off(row,PRIVATE/(run+'-cleanup.bin'))
            except BaseException as cleanup:
                row['cleanup_failure'] = str(cleanup)
    finally:
        if row.get('ram_backup'):
            try:
                decode_trial_snapshot(row,data)
            except BaseException as error:
                row.update(pass_=False,snapshot_decode_failure=str(error))
        path = OUTPUT/(run+'.json')
        path.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(path),flush=True)
        if not row['pass_']:
            for step in row['steps']:
                print(step['output'],flush=True)
    return 0 if row['pass_'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
