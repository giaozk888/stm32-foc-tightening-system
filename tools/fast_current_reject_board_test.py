"""Pinned ComputeOnly A acceptance; never sends motor/bridge START.

Reuse the established inactive-A/full-capture/bootloader-mailbox transaction.
All replacement identities are explicit; original historical scripts stay intact.
Default is offline. Full captures remain in the ignored private directory.
"""
import argparse
import json
import re
import struct
import time
import zlib

import rc_deferred_shadow_board_test as transaction
from original_closed_loop_updated_stage import debug, off_report
from firmware_transfer_iap import image_info, fields
from protected_irq_optimized_stage import open_port
from tighten_synthetic_swd_recovery import latest_meta
from original_closed_loop_trial import emergency_off
from latest_original_fsm_stage import full_compare_commands, off_commands, write_mailbox

ROOT, OUTPUT, PRIVATE = transaction.ROOT, transaction.OUTPUT, transaction.PRIVATE
IMAGE = ROOT / 'foc2_app_a/build/FastCurrentRejectComputeOnly/foc2.bin'
SHA = 'c46cd82789ea702cebf04d19dd379b5021e3abd33f3081ae35ef2751583aed4c'
SIZE = 224996
BASE_RECEIPT = OUTPUT / 'rc-deferred-shadow-restore-1792140423717718000.json'
BASE_SHA = 'bf6c3f31ef25a8285d7dd025e9b650ffc5f236765ca3404db4042ea727c14e4d'
BASE_META = (1112493908,3,2,0,0,579,211340,2639054818,210916,453748590,0,1889276060)
PREFIX = 'fast-reject-'


def image():
    raw = IMAGE.read_bytes()
    if len(raw) != SIZE or transaction.digest(raw) != SHA or image_info(raw)[0] != 'A':
        raise ValueError('Exact offline-tested ComputeOnly A required')
    for marker in (b'NAME=FAST_CURRENT_REJECT HARD_OFF=1',
                   b'FAST_REJECT=1 REPAIR=0', b'FILTER=NONE OC=RAW_2_OF_3',
                   b'CURRENT VALIDATION samples='):
        if marker not in raw:
            raise ValueError('Missing hard-off/fast-reject identity')
    return raw


# Transaction code resolves these globals in its own module. Keep every gate,
# full comparison, erase-page boundary check and restore operation unchanged.
transaction.IMAGE, transaction.SHA, transaction.SIZE = IMAGE, SHA, SIZE
transaction.BASE_RECEIPT, transaction.BASE_SHA = BASE_RECEIPT, BASE_SHA
transaction.BASE_META, transaction.PREFIX = BASE_META, PREFIX
transaction.image = image


def inspect(row, run):
    path = PRIVATE / (run + '-live.bin')
    out = debug(row, ['init', *off_report(),
                     'echo CR1=[mrw 0x40012C00]',
                     f'dump_image {{{path.as_posix()}}} 0x08000000 0x80000', 'shutdown'])
    print(out, flush=True)
    raw = path.read_bytes()
    _, baseline = transaction.baseline()
    row.update(backup=str(path), metadata=list(latest_meta(raw)),
               sha256=transaction.digest(raw), baseline_matches=(raw == baseline))
    if raw != baseline:
        raise ValueError('Live Flash differs from exact B579 backup')
    row['pass_'] = True


def inspect_stopped(row, run):
    path = PRIVATE / (run + '-live.bin')
    ram = PRIVATE / (run + '-ram.bin')
    out = debug(row, ['init',
        'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU not halted"}',
        *off_report(), 'echo CR1=[mrw 0x40012C00]',
        f'dump_image {{{ram.as_posix()}}} 0x20000000 0x20000',
        f'dump_image {{{path.as_posix()}}} 0x08000000 0x80000', 'shutdown'])
    print(out, flush=True)
    raw = path.read_bytes()
    row.update(backup=str(path),metadata=list(latest_meta(raw)),
        sha256=transaction.digest(raw),
        ram_backup=str(ram),mailbox_trace=[hex(w) for w in struct.unpack_from('<16I',ram.read_bytes(),0x1ffc0)],
        new_a_exact=raw[0x8000:0x8000+SIZE]==image())
    print(json.dumps({k:v for k,v in row.items() if k!='steps'},indent=2),flush=True)
    row['pass_'] = True


def diagnose_mailbox(row, run, data):
    """Stop before metadata save/app jump: evaluate only image admission."""
    source=OUTPUT/'fast-reject-stopped-1792148524219736300.json'
    previous=json.loads(source.read_text('utf-8'))
    expected=transaction.prior.private_path(previous['backup'])
    before=expected.read_bytes()
    if transaction.digest(before)!='f95be1e5613354d3e9272b9607f01e679917ac442f3dd4d1667bd238c1d32678':
        raise ValueError('Exact stopped B579/staged A required')
    boot=(ROOT/'foc2_bootloader/build/Debug/foc2_bootloader.bin').read_bytes()
    if before[:len(boot)]!=boot: raise ValueError('Pinned debug addresses require exact bootloader')
    final=PRIVATE/(run+'-final.bin')
    ram=PRIVATE/(run+'-ram.bin')
    row['hardware_attempted']=True
    out=debug(row,[*transaction.prior.off_gate(0x08040000),
        *full_compare_commands(PRIVATE/(run+'-before.bin'),expected),
        'reset halt','bp 0x08002a22 2 hw','bp 0x08002f1a 2 hw',
        *write_mailbox(transaction.mailbox(data)),
        'reset run','wait_halt 25000',
        'set task_pc [lindex [reg pc] 2]',
        'if {$task_pc != 0x08002a22 && $task_pc != 0x08002f1a} {error "Not halted before metadata save/application"}',
        'echo DIAG_PC=$task_pc','echo DIAG_RESULT=[lindex [reg r0] 2]',
        'set task_frame [lindex [reg r7] 2]',
        'echo DIAG_FRAME=$task_frame',
        'echo DIAG_CRC_ACTUAL=[mrw [expr {$task_frame-28}]]',
        'echo DIAG_CRC_EXPECTED=[mrw [expr {$task_frame-16}]]',
        'echo DIAG_CRC_BYTES=[mrw [expr {$task_frame-12}]]',
        'rbp 0x08002a22','rbp 0x08002f1a',*off_commands(),*off_report(),
        f'dump_image {{{ram.as_posix()}}} 0x20000000 0x20000',
        f'dump_image {{{final.as_posix()}}} 0x08000000 0x80000','halt','shutdown'])
    row['diagnostic']={k:v for k,v in re.findall(r'(?m)^(DIAG_[A-Z_]+)=(\S+)',out)}
    if final.read_bytes()!=before: raise RuntimeError('Admission diagnostic unexpectedly changed Flash')
    row.update(pass_=True,final_cpu_halted=True,final_outputs_off=True,
        final_backup=str(final),ram_backup=str(ram),all_flash_unchanged=True,
        final_metadata=list(latest_meta(before)),application_started=False)
    print(json.dumps(row['diagnostic'],indent=2),flush=True)


def finish_mailbox_no_app(row,run,data):
    """Continue the stopped bootloader request, halt before APP selection."""
    previous=json.loads((OUTPUT/'fast-reject-diagnose-1792148720114073800.json').read_text())
    if previous.get('diagnostic',{}).get('DIAG_RESULT')!='0x00000001' or not previous.get('all_flash_unchanged'):
        raise ValueError('Successful stopped image CRC diagnostic required')
    expected=transaction.prior.private_path(previous['final_backup'])
    before=expected.read_bytes()
    final=PRIVATE/(run+'-final.bin'); ram=PRIVATE/(run+'-ram.bin')
    row['hardware_attempted']=True
    out=debug(row,[*transaction.prior.off_gate(0),
        'poll',
        'if {[lindex [reg pc] 2] != 0x08002a22} {error "Image-admission stop lost"}',
        *full_compare_commands(PRIVATE/(run+'-before.bin'),expected),
        'bp 0x08002f1a 2 hw','resume','wait_halt 25000',
        'if {[lindex [reg pc] 2] != 0x08002f1a} {error "Not stopped before APP selection"}',
        'echo DIAG_RESULT=[lindex [reg r0] 2]','rbp 0x08002f1a',
        *off_report(),f'dump_image {{{ram.as_posix()}}} 0x20000000 0x20000',
        f'dump_image {{{final.as_posix()}}} 0x08000000 0x80000','halt','shutdown'])
    raw=final.read_bytes(); mem=ram.read_bytes()
    if raw[:0x7e800]!=before[:0x7e800] or raw[0x7f800:]!=before[0x7f800:]:
        raise RuntimeError('Bootloader request changed non-metadata Flash')
    row.update(pass_=True,diagnostic={k:v for k,v in re.findall(r'(?m)^(DIAG_[A-Z_]+)=(\S+)',out)},
        boot_meta_save_stage=struct.unpack_from('<I',mem,0x74)[0],
        boot_hal_status=mem[0x78],boot_lock_status=mem[0x79],
        boot_page_error=hex(struct.unpack_from('<I',mem,0x2c)[0]),
        boot_flash_error=hex(struct.unpack_from('<I',mem,0x7c)[0]),
        boot_flash_sr=hex(struct.unpack_from('<I',mem,0x80)[0]),
        boot_flash_cr=hex(struct.unpack_from('<I',mem,0x84)[0]),
        final_metadata=list(latest_meta(raw)),final_backup=str(final),ram_backup=str(ram),
        final_sha256=transaction.digest(raw),all_app_and_private_bytes_unchanged=True,
        final_cpu_halted=True,final_outputs_off=True,application_started=False)
    print(json.dumps({k:v for k,v in row.items() if k not in ('steps','samples')},indent=2),flush=True)


def stage(row, run, data):
    expected, before = transaction.baseline()
    # The board was power-cycled since the historical halted receipt. Verify
    # live Flash before halting; do not assume that an old halt still holds.
    live = PRIVATE / (run + '-running-before.bin')
    out = debug(row, ['init',
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected confirmed B"}',
        'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20]} {error "Outputs not off"}',
        *full_compare_commands(live, expected), 'halt', *off_commands(),
        *off_report(), 'shutdown'])
    transaction.check_off(out, (0x08040000,))
    row['physically_off_running_b_halted'] = True
    transaction.stage(row, run, data)


class Console(transaction.Console):
    READ = frozenset(('FW STATUS','MOTOR TEST PROFILE','MOTOR TEST STATUS',
        'MOTOR TEST ZERO','MOTOR TEST FILTER','MOTOR TEST PROTECTION',
        'MOTOR TEST TIMING','MOTOR TEST FAULT','MOTOR TEST COST',
        'ADC TIMING','ADC BUFFER','ADC COMMIT','STATUS','ENC DIAG'))

    def query(self, text, timeout=2):
        if text not in self.READ and text != 'ANALOG SAFE':
            raise ValueError('Read/shutdown only; no START, reset, clear or confirm')
        return super().query(text, timeout)

    def dispatch(self, line):
        super().dispatch(line)
        if 'CURRENT VALIDATION ' in line:
            print(line, flush=True)


def sample(uart):
    row = {'host_time': time.monotonic()}
    for key, command in (('fw','FW STATUS'),('profile','MOTOR TEST PROFILE'),
            ('state','MOTOR TEST STATUS'),('zero','MOTOR TEST ZERO'),
            ('filter','MOTOR TEST FILTER'),('protection','MOTOR TEST PROTECTION'),
            ('timing','MOTOR TEST TIMING'),('adc','ADC TIMING'),
            ('buffer','ADC BUFFER'),('commit','ADC COMMIT'),
            ('cost','MOTOR TEST COST'),('fault','MOTOR TEST FAULT'),('status','STATUS')):
        row[key] = fields(uart.query(command))
    return row


def healthy(s):
    if s['profile'].get('NAME') != 'FAST_CURRENT_REJECT' or s['profile'].get('HARD_OFF') != '1':
        raise RuntimeError('Wrong compute-only profile')
    if any(s['state'].get(k) != '0' for k in ('SD','MOE','CCER','FLAGS','FAULT')):
        raise RuntimeError('Not healthy/output locked')
    if s['state'].get('STATE') != '1' or s['zero'].get('STATE') != '3':
        raise RuntimeError('Not calibrated READY')
    if s['fault'].get('VALID') != '0' or s['status'].get('FLT') != '0':
        raise RuntimeError('Runtime fault; no retry')


def trial(row, run, data, receipt, committed=False):
    if committed:
        prior=json.loads(receipt.read_text('utf-8'))
        if (receipt.resolve()!= (OUTPUT/'fast-reject-commit-diagnose-1792148858903020400.json').resolve()
                or prior.get('diagnostic',{}).get('DIAG_RESULT')!='0x00000001'
                or prior.get('final_sha256')!='a2c070a902a7345441ba0ab930b8de0ceef3aa24111e05a3d11a075dde1f7c9b'):
            raise ValueError('Exact committed request, not a new trial')
        expected=transaction.prior.private_path(prior['final_backup'])
        before=expected.read_bytes()
        if transaction.digest(before)!=prior['final_sha256'] or latest_meta(before)[2:6]!=(2,1,2,580):
            raise ValueError('Committed request changed')
    else:
        expected, before = transaction.load_stage(receipt, data)
    port = uart = None
    try:
        port = open_port()
        uart = Console(port)
        row.update(hardware_attempted=True, trial_requests=0 if committed else 1,
                   continued_committed_request=committed)
        commands=[*transaction.prior.off_gate(0),
            *full_compare_commands(PRIVATE/(run+'-before.bin'), expected)]
        if committed:
            commands+=['poll','if {[lindex [reg pc] 2] != 0x08002f1a} {error "Committed request stop lost"}',
                       'resume','shutdown']
        else:
            commands+=['reset halt',*write_mailbox(transaction.mailbox(data)),'reset run','shutdown']
        debug(row,commands)
        row['activation_submitted'] = True
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try: fw = fields(uart.query('FW STATUS', .6))
            except TimeoutError: continue
            row['last_fw'] = fw
            if fw.get('CURRENT') == 'B' and fw.get('PENDING') == '-':
                raise RuntimeError('A rolled back/rejected; no retry')
            if fw.get('CURRENT') != 'A': continue
            try: state = fields(uart.query('MOTOR TEST STATUS', .6))
            except TimeoutError: continue
            row['last_state'] = state
            if state.get('STATE') == '4':
                row['sample'] = sample(uart)
                # Keep reading task diagnostics, not restarting acquisition.
                end = time.monotonic()+5.5
                while time.monotonic() < end: uart.poll(.05)
                raise RuntimeError('Startup/runtime fault captured; no retry')
            if all(fw.get(k) == v for k,v in (('CONFIRMED','A'),('PENDING','-'),('ATTEMPTS','0'),('ACTIVE','0'))):
                row['normally_confirmed'] = True
                break
        else: raise TimeoutError('Normal health confirmation absent')
        start = time.monotonic()
        while True:
            s = sample(uart)
            row['sample'] = s
            row['samples'].append(s)
            try: healthy(s)
            except RuntimeError:
                end=time.monotonic()+5.5
                while time.monotonic()<end: uart.poll(.05)
                raise
            if time.monotonic()-start >= 30: break
            end=time.monotonic()+2
            while time.monotonic()<end: uart.poll(.05)
        row['observed_seconds'] = time.monotonic()-start
        stats = [dict(re.findall(r'\b([a-z_]+)=([^\s]+)', line))
                 for line in uart.lines if 'CURRENT VALIDATION ' in line]
        row['current_validation'] = stats
        if len(stats)<2: raise RuntimeError('Missing periodic current profiling evidence')
        last=stats[-1]
        if int(last['deadline_miss']) or not 0<int(last['max_cycles'])<8500:
            raise RuntimeError('Observed 50 us profiling budget failed')
        if int(stats[-1]['samples']) <= int(stats[0]['samples']):
            raise RuntimeError('No current-sample progression')
        b=s['buffer']
        if b.get('STK_VALID')!='1' or int(b.get('FREE_B','0'))<256:
            raise RuntimeError('ADC worker stack margin failed')
        row.update(pass_=True, compute_50us_pass=True,
            observed_normal_max_us=int(last['normal_max_cycles'])/170,
            observed_invalid_max_us=int(last['invalid_max_cycles'])/170,
            observed_all_max_us=int(last['max_cycles'])/170,
            invalid_path_observed=int(last['invalid'])>0,
            physical_pwm_preload_deadline_verified=False,motor_closed_loop_verified=False)
        print('TRIAL PASS: 30 seconds ComputeOnly; no START',flush=True)
    finally:
        try:
            if row.get('hardware_attempted'):
                if uart:
                    try: row['off_ack']=uart.query('ANALOG SAFE',.8)
                    except BaseException as error: row['uart_off_error']=str(error)
                final=PRIVATE/(run+'-final.bin')
                emergency_off(row, final)
                raw=final.read_bytes()
                try:
                    meta=transaction.compare_final(before,raw,data,row.get('activation_submitted',False))
                except BaseException as error:
                    row['final_comparison_failure']=str(error)
                    row['final_metadata']=list(latest_meta(raw))
                    row['final_sha256']=transaction.digest(raw)
                    raise
                row.update(final_metadata=list(meta),final_sha256=transaction.digest(raw),
                           all_app_and_private_bytes_unchanged=True)
                ram=PRIVATE/(run+'-ram.bin')
                debug(row,['init',
                    'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "Not stopped for RAM capture"}',
                    'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20]} {error "Not off for RAM capture"}',
                    f'dump_image {{{ram.as_posix()}}} 0x20000000 0x20000','shutdown'])
                row['ram_backup']=str(ram)
        finally:
            if uart:
                row.update(uart=uart.lines,host_motor_commands=uart.starts,
                    host_uart_trial_commits=uart.ends,
                    current_validation=[dict(re.findall(r'\b([a-z_]+)=([^\s]+)',line))
                        for line in uart.lines if 'CURRENT VALIDATION ' in line])
            if port and port.is_open: port.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--inspect-registers', action='store_true')
    mode.add_argument('--inspect-stopped', action='store_true')
    mode.add_argument('--diagnose-mailbox-no-app', action='store_true')
    mode.add_argument('--finish-mailbox-no-app', action='store_true')
    mode.add_argument('--stage-inactive-a', action='store_true')
    mode.add_argument('--trial-from-stage', type=transaction.Path)
    mode.add_argument('--observe-committed', type=transaction.Path)
    mode.add_argument('--restore-from-trial', type=transaction.Path)
    parser.add_argument('--drive-12v-off-motor-disconnected', action='store_true')
    parser.add_argument('--drive-12v-on-motor-disconnected', action='store_true')
    args = parser.parse_args()
    data = image()
    if not (args.inspect_registers or args.inspect_stopped or args.diagnose_mailbox_no_app or args.finish_mailbox_no_app or args.stage_inactive_a or args.restore_from_trial or args.trial_from_stage or args.observe_committed):
        transaction.baseline()
        print('OFFLINE PASS: exact ComputeOnly A and confirmed B579 backup')
        return 0
    operation = 'commit-diagnose' if args.finish_mailbox_no_app else 'diagnose' if args.diagnose_mailbox_no_app else 'stopped' if args.inspect_stopped else 'inspect' if args.inspect_registers else 'restore' if args.restore_from_trial else 'trial' if (args.trial_from_stage or args.observe_committed) else 'stage'
    if operation in ('stage','restore','diagnose','commit-diagnose') and not args.drive_12v_off_motor_disconnected:
        parser.error('Actual drive off and motor disconnected required')
    if operation == 'trial' and not args.drive_12v_on_motor_disconnected:
        parser.error('Actual powered drive and disconnected motor required')
    run = PREFIX + operation + '-' + str(time.time_ns())
    row = dict(pass_=False, mode=operation, image_sha256=SHA, image_bytes=SIZE,
               steps=[], samples=[], hardware_attempted=False, programming_attempted=False,
               motor_commands=0, trial_requests=0, force_confirmation=False,
               direct_metadata_write=False, automatic_retry=False, activation=False)
    try:
        if operation == 'inspect': inspect(row, run)
        elif operation == 'stopped': inspect_stopped(row, run)
        elif operation == 'diagnose': diagnose_mailbox(row,run,data)
        elif operation == 'commit-diagnose': finish_mailbox_no_app(row,run,data)
        elif operation == 'stage': stage(row, run, data)
        elif operation == 'trial': trial(row, run, data, args.observe_committed or args.trial_from_stage,
                                        committed=bool(args.observe_committed))
        else: transaction.restore(row, run, data, args.restore_from_trial)
    except BaseException as error:
        row.update(pass_=False, failure=str(error))
        print('FAILED: ' + str(error), flush=True)
        if (row.get('programming_attempted') or row.get('restore_attempted') or operation in ('diagnose','commit-diagnose')) and not row.get('final_cpu_halted'):
            try: emergency_off(row, PRIVATE / (run + '-cleanup.bin'))
            except BaseException as cleanup: row['cleanup_failure'] = str(cleanup)
    finally:
        path = OUTPUT / (run + '.json')
        path.write_text(json.dumps(row, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print('Evidence: ' + str(path), flush=True)
        if not row['pass_']:
            for step in row['steps']: print(step['output'], flush=True)
    return 0 if row['pass_'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
