"""Pinned optimized RC B: offline by default, separate OFF staging/ON trial.

No START, bridge enable, fault clear, forced B confirmation or automatic retry.
Recover only the already-confirmed A564 at its reset entry, then stage B.
Full captures remain in the established private directory, never printed.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib

import rc_protected_board_test as old
import rc_protected_trial as previous
from firmware_transfer_iap import image_info, fields
from latest_original_fsm_stage import full_compare_commands, off_commands, write_mailbox
from original_closed_loop_updated_stage import debug, check_off, off_report
from original_closed_loop_trial import emergency_off
from protected_irq_optimized_stage import open_port

ROOT, OUTPUT, PRIVATE = old.ROOT, old.OUTPUT, old.PRIVATE
IMAGE = ROOT/'foc2_app_b/build/RcSamplingOptimizedCandidate/foc2.bin'
SHA = '9fd54166df782cce3e737ecfebe67bc4aff8f15a005fca1f1136c91bb8786f44'
SIZE = 210916
PRIOR = OUTPUT/'rc-protected-trial-1792123335544055000.json'
BASELINE_SHA = '1c5004718123bad10f3e69eefc0525c12c934a479e47f8be7ac3ecd924ac101a'
FAILED_META = (1112493908,3,1,2,1,566,208236,1538858691,210724,1932594806,0,2726121964)
OBSERVE_SECONDS = 30.0
RECOVERY_INTERRUPTION = OUTPUT/'rc-optimized-stage-1792126647893980900.json'


def pinned_image():
    data = IMAGE.read_bytes()
    if len(data) != SIZE or old.digest(data) != SHA or image_info(data)[0] != 'B':
        raise ValueError('Exact independently built optimized B required')
    for marker in (b'NAME=RC_PROTECTED_CANDIDATE HARD_OFF=0 ADAPT=1 FSM=ORIGINAL',
                   b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000', b'USE_ORIGINAL_START',
                   b'RAM ENABLED=1 HARD_OFF=0 DEADLINE_US=50',
                   b'LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000',
                   b'BOTTOM_LATE=%lu GUARD=%u HW_VERIFIED=0'):
        if marker not in data:
            raise ValueError('Protected optimized identity missing')
    return data


def capture_path(value):
    path = Path(value).resolve()
    if path.parent != PRIVATE.resolve():
        raise ValueError('Full captures must remain in private evidence directory')
    return path


def validate_failed(raw):
    if len(raw) != 0x80000 or old.digest(raw) != BASELINE_SHA or old.latest_meta(raw) != FAILED_META:
        raise ValueError('Exact halted failed B566 baseline required')
    if (old.digest(raw[0x8000:0x8000+FAILED_META[6]]) != old.A_SHA or
            raw[0x40000:0x40000+old.SIZE] != old.pinned_image()):
        raise ValueError('Fallback A564 or previous B candidate changed')


def load_failed():
    row = json.loads(PRIOR.read_text('utf-8'))
    if (row.get('pass_') is not False or row.get('image_sha256') != old.SHA or
            row.get('final_sha256') != BASELINE_SHA or row.get('host_motor_commands') != 0 or
            row.get('host_uart_trial_commits') != 0 or row.get('cleanup_failure') or
            tuple(row.get('final_metadata', ())) != FAILED_META or
            any(row.get(k) is not True for k in ('final_outputs_off', 'final_cpu_halted',
                                               'all_app_and_private_bytes_unchanged'))):
        raise ValueError('Exact failed compute-only receipt required')
    path = capture_path(row['final_backup'])
    raw = path.read_bytes()
    validate_failed(raw)
    return path, raw


def mailbox(command, image=None):
    if command == 3 and image is None:
        values = (3,1,1,0,0)  # select ONLY the existing confirmed A
    elif command == 2 and image is not None and len(image) == SIZE and old.digest(image) == SHA:
        values = (2,1,2,len(image),zlib.crc32(image))
    else:
        raise ValueError('Only confirmed-A recovery or exact optimized-B trial')
    body = struct.pack('<7I',0x584f424d,1,*values)
    return struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))


def nonmetadata_equal(before, actual):
    if len(before) != 0x80000 or len(actual) != 0x80000:
        raise ValueError('Complete Flash captures required')
    if actual[:0x7e800] != before[:0x7e800] or actual[0x7f800:] != before[0x7f800:]:
        raise ValueError('Application, bootloader or private bytes changed')


def validate_recovered(before, actual):
    nonmetadata_equal(before, actual)
    meta = old.latest_meta(actual)
    if meta[2:6] != (1,0,0,567) or meta[6:11] != FAILED_META[6:11]:
        raise ValueError('Existing A recovery metadata mismatch')
    return meta


def bootloader_gate():
    return ['init','if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU not already halted"}',
        'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted bootloader"}',
        'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20] || [mrw 0x40012C00] & 1} {error "Outputs not off"}']


def recovery_commands(live, baseline, recovered, entry):
    if not 0x08008000 <= entry < 0x08040000 or entry & 1:
        raise ValueError('A reset entry invalid')
    return [*old.output_gate(0x08040000), *full_compare_commands(live, baseline),
        'reset halt',f'bp {entry:#x} 2 hw',*write_mailbox(mailbox(3)),
        'reset run','wait_halt 25000',f'rbp {entry:#x}',
        f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not stopped before A instructions"}}',
        *off_commands(),*off_report(),
        f'dump_image {{{recovered.as_posix()}}} 0x08000000 0x80000','halt','shutdown']


def compare_stage(before, actual, image):
    if len(before) != 0x80000 or len(actual) != 0x80000 or actual[0x40000:0x40000+len(image)] != image:
        raise ValueError('Full capture / optimized B mismatch')
    end = 0x40000+len(image)
    erased_end = (end+0x7ff)&~0x7ff
    if actual[end:erased_end] != b'\xff'*(erased_end-end):
        raise ValueError('Last erased B page tail mismatch')
    if actual[:0x40000] != before[:0x40000] or actual[erased_end:] != before[erased_end:]:
        raise ValueError('Bytes outside inactive B erase pages changed')
    if old.latest_meta(actual) != old.latest_meta(before):
        raise ValueError('Staging changed metadata')


def stage_commands(live, baseline, staged, entry=None):
    # Bootloader installs A's VTOR before branching to its reset entry. Accept
    # that exact entry as well, not arbitrary running or faulted A code.
    if entry is None:
        gate = bootloader_gate()
    else:
        if not 0x08008000 <= entry < 0x08040000 or entry & 1:
            raise ValueError('Exact recovered A reset entry required')
        # Synchronize OpenOCD's cached core state after reconnecting; DHCSR
        # proves a hardware halt but reg pc otherwise fails in UNKNOWN state.
        gate = [*old.output_gate(0x08008000), 'poll',
                f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not at recovered A reset entry"}}']
    return [*gate, *full_compare_commands(live, baseline),
        'reset halt',*off_commands(),
        f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08040000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08040000 bin',
        f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000',*off_report(),
        'if {[mrw 0x40012C00] & 1} {error "Timer not stopped"}','halt','shutdown']


def load_completed_recovery(receipt):
    if receipt.resolve() != RECOVERY_INTERRUPTION.resolve():
        raise ValueError('Only exact host-validation interruption may continue staging')
    prior = json.loads(receipt.read_text('utf-8'))
    if (prior.get('pass_') is not False or prior.get('mode') != 'stage' or
            prior.get('image_sha256') != SHA or prior.get('recovery_requests') != 1 or
            prior.get('failure') != 'Halted/off output proof incomplete' or
            prior.get('programming_attempted') or prior.get('trial_requests') != 0 or
            prior.get('motor_commands') != 0 or prior.get('cleanup_failure') or
            prior.get('final_outputs_off') is not True or prior.get('final_cpu_halted') is not True):
        raise ValueError('Not a completed A recovery before any B write or trial')
    path = capture_path(prior['final_backup'])
    raw = path.read_bytes()
    _,before = load_failed()
    validate_recovered(before,raw)
    entry = struct.unpack_from('<I',raw,0x8004)[0]&~1
    # Check the successful recovery report as well as the complete captures.
    check_off(prior['steps'][0]['output'],(0x08008000,))
    if f'pc: {entry:#010x}' not in prior['steps'][0]['output']:
        raise ValueError('Successful reset-entry breakpoint evidence missing')
    return path,raw,entry


def stage(row, run, image, completed_recovery=None):
    if completed_recovery:
        recovered,raw,entry = load_completed_recovery(completed_recovery)
        row.update(hardware_attempted=True,recovery_requests=1,
                   recovery_reused_from=str(completed_recovery.resolve()))
    else:
        path, before = load_failed()
        recovered = PRIVATE/(run+'-recovered.bin')
        entry = struct.unpack_from('<I',before,0x8004)[0]&~1
        row.update(hardware_attempted=True, recovery_requests=1)
        report = debug(row,recovery_commands(PRIVATE/(run+'-before.bin'),path,recovered,entry))
        row['recovery_outputs'] = check_off(report,(0x08008000,))
        raw = recovered.read_bytes()
        validate_recovered(before,raw)
    row.update(recovered_backup=str(recovered),recovered_metadata=list(old.latest_meta(raw)),
               recovery_nonmetadata_unchanged=True)
    print('RECOVERY PASS: existing confirmed A564; halted before APP; no motor command',flush=True)
    staged = PRIVATE/(run+'-staged.bin')
    row['programming_attempted'] = True
    report = debug(row,stage_commands(PRIVATE/(run+'-prewrite.bin'),recovered,staged,entry))
    row['outputs'] = check_off(report,(0,0x08000000))
    actual = staged.read_bytes()
    compare_stage(raw,actual,image)
    row.update(pass_=True,staged_backup=str(staged),staged_sha256=old.digest(actual),
        staged_metadata=list(old.latest_meta(actual)),metadata_unchanged=True,
        all_bytes_outside_b_pages_unchanged=True,preserved_a_sha256=old.A_SHA,
        final_outputs_off=True,final_cpu_halted=True,activation=False)
    print('STAGE PASS: optimized B byte-exact; A/private unchanged; NOT activated',flush=True)


def load_stage(receipt):
    receipt = receipt.resolve()
    if receipt.parent != OUTPUT.resolve() or not receipt.name.startswith('rc-optimized-stage-'):
        raise ValueError('Exact optimized stage receipt location required')
    row = json.loads(receipt.read_text('utf-8'))
    if (row.get('pass_') is not True or row.get('mode') != 'stage' or row.get('image_sha256') != SHA or
            row.get('activation') is not False or row.get('motor_commands') != 0 or
            row.get('trial_requests') != 0 or row.get('recovery_requests') != 1 or
            any(row.get(k) is not True for k in ('metadata_unchanged','all_bytes_outside_b_pages_unchanged',
                                               'final_outputs_off','final_cpu_halted'))):
        raise ValueError('Successful unactivated optimized B stage required')
    recovered = capture_path(row['recovered_backup']).read_bytes()
    _,failed = load_failed()
    validate_recovered(failed,recovered)
    path = capture_path(row['staged_backup'])
    raw = path.read_bytes()
    if old.digest(raw) != row.get('staged_sha256') or tuple(row.get('staged_metadata',())) != old.latest_meta(raw):
        raise ValueError('Staged capture changed')
    compare_stage(recovered,raw,pinned_image())
    return path,raw


def trial_commands(live, baseline, image):
    return [*bootloader_gate(),*full_compare_commands(live,baseline),'reset halt',
            *write_mailbox(mailbox(2,image)),'reset run','shutdown']


def compare_final(before, actual, image):
    nonmetadata_equal(before,actual)
    meta = old.latest_meta(actual)
    initial = old.latest_meta(before)
    if (meta[5] <= initial[5] or meta[6:8] != initial[6:8] or
            meta[8:10] != (len(image),zlib.crc32(image)) or
            meta[2:5] not in ((1,2,1),(2,0,0),(1,0,0))):
        raise ValueError('Unexpected normal optimized trial metadata')
    return meta


def trial(row, run, image, receipt):
    path,before = load_stage(receipt)
    port = uart = None
    try:
        port = open_port()
        uart = previous.Console(port)  # strict diagnostic/off allowlist; no START
        row.update(hardware_attempted=True,trial_requests=1)
        debug(row,trial_commands(PRIVATE/(run+'-before.bin'),path,image))
        row['activation_submitted'] = True
        print('ONE optimized B computation trial; no motor/bridge START',flush=True)
        deadline = time.monotonic()+60
        while time.monotonic() < deadline:
            try:
                fw = fields(uart.query('FW STATUS',.6))
            except TimeoutError:
                continue
            row['fw'] = fw
            if fw.get('CURRENT') == 'A' and fw.get('PENDING') == '-':
                raise RuntimeError('Rejected/rolled back to A; no retry')
            if fw.get('CURRENT') != 'B':
                continue
            try:
                state = fields(uart.query('MOTOR TEST STATUS',.6))
            except TimeoutError:
                continue  # normal health-confirmation reset may cross query
            row['last_state'] = state
            if state.get('STATE') == '4':
                row['sample'] = previous.snapshot(uart)
                raise RuntimeError('Startup fault captured; no retry')
            if (fw.get('CONFIRMED') == 'B' and fw.get('PENDING') == '-' and
                    fw.get('ATTEMPTS') == '0' and fw.get('ACTIVE') == '0'):
                row['normally_confirmed'] = True
                break
            uart.poll(.02)
        else:
            raise TimeoutError('Normal B health confirmation absent')
        first = previous.snapshot(uart)
        row['samples'].append(first)
        row['sample'] = first
        previous.validate(first)
        print('Boot/zero PASS; observing 30s output-off computation',flush=True)
        while True:
            end = time.monotonic()+1.5
            while time.monotonic() < end:
                uart.poll(.05)
            last = previous.snapshot(uart)
            row['samples'].append(last)
            row['sample'] = last
            previous.validate(last)
            if last['host_time']-first['host_time'] >= OBSERVE_SECONDS:
                break
        for key,counter in (('adc','PAIRS'),('timing','WORK'),('timing','OUTER'),('buffer','DONE')):
            if int(last[key][counter]) <= int(first[key][counter]):
                raise RuntimeError('Computation/worker stopped: '+counter)
        row.update(pass_=True,compute_50us_pass=True,observed_seconds=last['host_time']-first['host_time'],
            observed_pairs=int(last['adc']['PAIRS'])-int(first['adc']['PAIRS']),
            compute_max_us=int(last['timing']['MAX_US']),adc_irq_max_us=int(last['adc']['MAX_CYC'])/170.0,
            rc_software_admission=last['commit']['READY']=='1')
        print('COMPUTE PASS; actual PWM/analog/motor qualification NOT claimed',flush=True)
    finally:
        try:
            if row.get('hardware_attempted'):
                if uart:
                    try:
                        row['off_ack'] = uart.query('ANALOG SAFE',.8)
                    except BaseException as error:
                        row['uart_off_error'] = str(error)
                final = PRIVATE/(run+'-final.bin')
                emergency_off(row,final)
                actual = final.read_bytes()
                meta = old.latest_meta(actual) if actual == before else compare_final(before,actual,image)
                row.update(all_app_and_private_bytes_unchanged=True,
                           final_metadata=list(meta),final_sha256=old.digest(actual))
                if row.get('normally_confirmed') and meta[2:5] != (2,0,0):
                    raise RuntimeError('Normally confirmed B not retained')
        finally:
            if uart:
                row.update(uart=uart.lines,host_motor_commands=uart.starts,host_uart_trial_commits=uart.ends)
            if port and port.is_open:
                port.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    modes = p.add_mutually_exclusive_group()
    modes.add_argument('--recover-confirmed-a-and-stage-b',action='store_true')
    modes.add_argument('--stage-after-completed-recovery',type=Path)
    modes.add_argument('--trial-from-stage',type=Path)
    p.add_argument('--drive-12v-off-motor-disconnected',action='store_true')
    p.add_argument('--drive-12v-on-motor-disconnected',action='store_true')
    args = p.parse_args()
    image = pinned_image()
    if not args.recover_confirmed_a_and_stage_b and not args.stage_after_completed_recovery and not args.trial_from_stage:
        print('OFFLINE PASS: pinned optimized B; no device/private access')
        return 0
    mode = 'trial' if args.trial_from_stage else 'stage'
    if (mode == 'stage' and not args.drive_12v_off_motor_disconnected or
            mode == 'trial' and not args.drive_12v_on_motor_disconnected):
        p.error('Confirmed physical supply/motor-disconnected phase required')
    run = 'rc-optimized-'+mode+'-'+str(time.time_ns())
    row = dict(pass_=False,mode=mode,image_sha256=SHA,image_bytes=SIZE,steps=[],samples=[],
        hardware_attempted=False,trial_requests=0,motor_commands=0,automatic_retry=False,
        force_confirmation=False,direct_metadata_write=False,motor_closed_loop_verified=False,
        physical_pwm_preload_deadline_verified=False,bridge_analog_settling_verified=False,
        requested_observation_seconds=OBSERVE_SECONDS)
    if args.trial_from_stage:
        row['stage_receipt'] = str(args.trial_from_stage.resolve())
    try:
        if mode == 'stage':
            stage(row,run,image,args.stage_after_completed_recovery)
        else:
            trial(row,run,image,args.trial_from_stage)
    except BaseException as error:
        row.update(pass_=False,failure=str(error))
        print('FAILED: '+str(error),flush=True)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:
                emergency_off(row,PRIVATE/(run+'-cleanup.bin'))
            except BaseException as cleanup:
                row['cleanup_failure'] = str(cleanup)
    finally:
        receipt = OUTPUT/(run+'.json')
        receipt.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(receipt),flush=True)
    return 0 if row['pass_'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
