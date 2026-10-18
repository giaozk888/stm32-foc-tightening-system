"""Pinned two-sample discriminator ComputeOnly acceptance, no motor START.

Default is offline. Stage/restore require physical drive power off; the single
trial requires the motor disconnected. Historical board scripts stay unchanged.
"""
import argparse
import json
import re
import time

import fast_current_reject_board_test as prior

tx = prior.transaction
ROOT, OUTPUT, PRIVATE = prior.ROOT, prior.OUTPUT, prior.PRIVATE
IMAGE = ROOT / 'foc2_app_a/build/FastCurrentRejectComputeOnly/foc2.bin'
SHA = 'cd2539cad04e76685dd5dcc72b4e82071512b9813ecbd8c1eedffb1c69f5b11e'
SIZE = 225068
BASE_RECEIPT = OUTPUT / 'fast-reject-restore-1792149127646760600.json'
BASE_SHA = '34be74369f9b834353debb3d31affa4eec08fd7dc21d37eafbc20ea6036eae05'
BASE_META = (1112493908,3,2,0,0,582,224996,422321414,210916,453748590,0,3297121505)
PREFIX = 'current-impulse-'


def image():
    data = IMAGE.read_bytes()
    if (len(data) != SIZE or tx.digest(data) != SHA or
            prior.image_info(data)[0] != 'A'):
        raise ValueError('Exact offline-tested two-sample ComputeOnly A required')
    for marker in (b'NAME=FAST_CURRENT_REJECT HARD_OFF=1',
                   b'FAST_REJECT=1 REPAIR=0', b'METHOD=TWO_SAMPLE',
                   b'FILTER=NONE OC=RAW_2_OF_3',
                   b'CURRENT VALIDATION samples=', b'unresolved_max_cycles='):
        if marker not in data:
            raise ValueError('Missing hard-off/two-sample/profiling marker')
    return data


# Rebind only this process to the new pinned image and last restored B capture.
# All whole-Flash comparisons and erase-page boundaries remain mandatory.
for module in (prior, tx):
    for key in ('IMAGE', 'SHA', 'SIZE', 'BASE_RECEIPT', 'BASE_SHA', 'BASE_META', 'PREFIX'):
        setattr(module, key, globals()[key])
    module.image = image


def statistics(lines):
    return [dict(re.findall(r'\b([a-z_]+)=([^\s]+)', line))
            for line in lines if 'CURRENT VALIDATION ' in line]


def validate_statistics(stats):
    if len(stats) < 2:
        raise RuntimeError('Missing periodic two-sample profiling evidence')
    required = ('samples', 'suspect', 'spike', 'transition', 'unresolved',
                'max_unresolved_run', 'fault', 'normal_max_cycles',
                'suspect_max_cycles', 'unresolved_max_cycles', 'max_cycles',
                'deadline_miss')
    for s in stats:
        if any(k not in s for k in required):
            raise RuntimeError('Incomplete new state-machine statistics')
        if (int(s['fault']) or int(s['deadline_miss']) or
                not 0 < int(s['normal_max_cycles']) < 8500 or
                not 0 < int(s['max_cycles']) < 8500):
            raise RuntimeError('Fault or observed 50 us compute budget failure')
        for key in ('suspect_max_cycles', 'unresolved_max_cycles'):
            if not 0 <= int(s[key]) < 8500:
                raise RuntimeError('Hold-path profiling outside 50 us')
    if int(stats[-1]['samples']) <= int(stats[0]['samples']):
        raise RuntimeError('No current sample progression')
    last = stats[-1]
    return dict(compute_50us_pass=True,
        observed_normal_max_us=int(last['normal_max_cycles'])/170,
        observed_suspect_max_us=int(last['suspect_max_cycles'])/170,
        observed_unresolved_max_us=int(last['unresolved_max_cycles'])/170,
        observed_all_max_us=int(last['max_cycles'])/170,
        suspect_path_observed=int(last['suspect']) > 0,
        unresolved_path_observed=int(last['unresolved']) > 0,
        physical_pwm_preload_deadline_verified=False,
        motor_closed_loop_verified=False)


def trial(row, run, data, receipt):
    expected, before = tx.load_stage(receipt, data)
    port = uart = None
    try:
        port = prior.open_port()
        uart = prior.Console(port)
        row.update(hardware_attempted=True, trial_requests=1)
        prior.debug(row, [*tx.prior.off_gate(0),
            *prior.full_compare_commands(PRIVATE/(run+'-before.bin'), expected),
            'reset halt', *prior.write_mailbox(tx.mailbox(data)),
            'reset run', 'shutdown'])
        row['activation_submitted'] = True
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                fw = prior.fields(uart.query('FW STATUS', .6))
            except TimeoutError:
                continue
            row['last_fw'] = fw
            if fw.get('CURRENT') == 'B' and fw.get('PENDING') == '-':
                raise RuntimeError('A rejected/rolled back; no retry')
            if fw.get('CURRENT') != 'A':
                continue
            try:
                state = prior.fields(uart.query('MOTOR TEST STATUS', .6))
            except TimeoutError:
                continue
            row['last_state'] = state
            if state.get('STATE') == '4':
                row['sample'] = prior.sample(uart)
                end = time.monotonic() + 5.5
                while time.monotonic() < end:
                    uart.poll(.05)
                raise RuntimeError('Startup/runtime fault captured; no retry')
            if all(fw.get(k) == v for k,v in
                   (('CONFIRMED','A'),('PENDING','-'),('ATTEMPTS','0'),('ACTIVE','0'))):
                row['normally_confirmed'] = True
                print('A normally confirmed; observing 30 seconds, power hard off', flush=True)
                break
        else:
            raise TimeoutError('Normal application health confirmation absent')
        start = time.monotonic()
        while True:
            s = prior.sample(uart)
            row['sample'] = s
            row['samples'].append(s)
            prior.healthy(s)
            if s['filter'].get('METHOD') != 'TWO_SAMPLE':
                raise RuntimeError('Wrong discriminator at runtime')
            if time.monotonic() - start >= 30:
                break
            end = time.monotonic() + 2
            while time.monotonic() < end:
                uart.poll(.05)
        row['observed_seconds'] = time.monotonic() - start
        row['current_validation'] = statistics(uart.lines)
        row.update(validate_statistics(row['current_validation']))
        b = s['buffer']
        if b.get('STK_VALID') != '1' or int(b.get('FREE_B','0')) < 256:
            raise RuntimeError('ADC worker stack margin failed')
        row['pass_'] = True
        print('TRIAL PASS: two-sample ComputeOnly; no START', flush=True)
    finally:
        try:
            if row.get('hardware_attempted'):
                if uart:
                    try:
                        row['off_ack'] = uart.query('ANALOG SAFE', .8)
                    except BaseException as error:
                        row['uart_off_error'] = str(error)
                final = PRIVATE/(run+'-final.bin')
                prior.emergency_off(row, final)
                raw = final.read_bytes()
                row.update(final_metadata=list(prior.latest_meta(raw)),
                           final_sha256=tx.digest(raw))
                tx.compare_final(before, raw, data, row.get('activation_submitted',False))
                row['all_app_and_private_bytes_unchanged'] = True
                ram = PRIVATE/(run+'-ram.bin')
                prior.debug(row, ['init',
                    'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "Not halted"}',
                    'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20]} {error "Not off"}',
                    f'dump_image {{{ram.as_posix()}}} 0x20000000 0x20000','shutdown'])
                row['ram_backup'] = str(ram)
        finally:
            if uart:
                row.update(uart=uart.lines, host_motor_commands=uart.starts,
                    host_uart_trial_commits=uart.ends,
                    current_validation=statistics(uart.lines))
            if port and port.is_open:
                port.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--stage-inactive-a', action='store_true')
    mode.add_argument('--trial-from-stage', type=tx.Path)
    mode.add_argument('--restore-from-trial', type=tx.Path)
    p.add_argument('--drive-12v-off-motor-disconnected', action='store_true')
    p.add_argument('--drive-12v-on-motor-disconnected', action='store_true')
    args = p.parse_args()
    data = image()
    tx.baseline()
    operation = ('stage' if args.stage_inactive_a else 'trial' if args.trial_from_stage
                 else 'restore' if args.restore_from_trial else None)
    if operation is None:
        print('OFFLINE PASS: pinned two-sample A and confirmed B582 full capture')
        return 0
    if operation in ('stage','restore') and not args.drive_12v_off_motor_disconnected:
        p.error('Actual drive power off and motor disconnected required')
    if operation == 'trial' and not args.drive_12v_on_motor_disconnected:
        p.error('Actual drive powered and motor disconnected required')
    run = PREFIX + operation + '-' + str(time.time_ns())
    row = dict(pass_=False, mode=operation, image_sha256=SHA, image_bytes=SIZE,
        steps=[], samples=[], hardware_attempted=False, programming_attempted=False,
        motor_commands=0, trial_requests=0, force_confirmation=False,
        direct_metadata_write=False, automatic_retry=False, activation=False)
    try:
        if operation == 'stage':
            prior.stage(row, run, data)
        elif operation == 'trial':
            trial(row, run, data, args.trial_from_stage)
        else:
            tx.restore(row, run, data, args.restore_from_trial)
    except BaseException as error:
        row.update(pass_=False, failure=str(error))
        print('FAILED: '+str(error), flush=True)
        if ((row.get('programming_attempted') or row.get('restore_attempted'))
                and not row.get('final_cpu_halted')):
            try:
                prior.emergency_off(row, PRIVATE/(run+'-cleanup.bin'))
            except BaseException as cleanup:
                row['cleanup_failure'] = str(cleanup)
    finally:
        path = OUTPUT/(run+'.json')
        path.write_text(json.dumps(row, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print('Evidence: '+str(path), flush=True)
        if not row['pass_']:
            for step in row['steps']:
                print(step['output'], flush=True)
    return 0 if row['pass_'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
