"""One 20 rpm / 400 ms no-load START on the already-confirmed CTR2 A.

File-only default. Separate physically-OFF inspection and powered execution.
No firmware programming, trial mailbox, fault clear or threshold changes.
Always halt with outputs off and collect Flash/RAM after a reset attempt.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from unittest.mock import patch

import current_invalid_rolling_trace_board_test as rolling
from latest_original_fsm_stage import full_compare_commands, off_commands
from original_closed_loop_updated_stage import debug, check_off, off_report
from original_closed_loop_trial import emergency_off
from protected_irq_optimized_stage import open_port
from tighten_synthetic_swd_recovery import latest_meta

previous = rolling.previous
trial, candidate = previous.trial, previous.candidate
ROOT, OUTPUT, PRIVATE = rolling.ROOT, rolling.OUTPUT, previous.PRIVATE
PREFIX = 'rolling-trace-closed-loop-'
SOURCE = OUTPUT/'current-invalid-rolling-trace-trial-1792243028066757100.json'
FULL_SHA = 'f7562227e89f3124341834e796af9a17a9cd4b3b38e03bfb0514046f062b0f32'
META = (1112493908,3,1,0,0,626,229364,3112785379,210916,453748590,0,2945252698)
RUNNER = ROOT/'tools/motor_motion_smoke.py'


def baseline(data):
    r = json.loads(SOURCE.read_text('utf-8'))
    if (r.get('image_sha256') != rolling.SHA or r.get('elf_sha256') != rolling.ELF_SHA or
            r.get('final_sha256') != FULL_SHA or tuple(r.get('final_metadata',())) != META or
            r.get('first_fault',{}).get('valid') != 0 or
            any(r.get(k) is not True for k in ('pass_','timing_pass','normally_confirmed',
                'final_cpu_halted','final_outputs_off','all_app_and_private_bytes_unchanged'))):
        raise ValueError('Exact stopped, healthy A626 computation receipt required')
    expected = candidate.tx.prior.private_path(r['final_backup'])
    raw = expected.read_bytes()
    if (len(raw) != 0x80000 or candidate.digest(raw) != FULL_SHA or latest_meta(raw) != META or
            raw[0x8000:0x8000+len(data)] != data or
            candidate.digest(raw[0x40000:0x40000+META[8]]) != rolling.B_SHA):
        raise ValueError('Confirmed A626 / preserved B full capture mismatch')
    return expected, raw


def load_inspection(path):
    path = path.resolve()
    if path.parent != OUTPUT.resolve() or not path.name.startswith(PREFIX+'inspect-'):
        raise ValueError('This profile inspection receipt required')
    r = json.loads(path.read_text('utf-8'))
    if (r.get('mode') != 'inspect' or r.get('pass_') is not True or
            r.get('image_sha256') != rolling.SHA or r.get('elf_sha256') != rolling.ELF_SHA or
            r.get('baseline_sha256') != FULL_SHA or not r.get('physical_12v_off') or
            not r.get('motor_connected_fixed') or r.get('reset_attempts') != 0 or
            r.get('runner_sha256') != candidate.digest(RUNNER.read_bytes())):
        raise ValueError('Fresh exact-image OFF inspection / unchanged bounded runner required')
    return r


def inspect(row, run, expected):
    out = debug(row,[*candidate.tx.prior.off_gate(0x08008000),
        *full_compare_commands(PRIVATE/(run+'-inspection.bin'),expected),
        *off_report(),'shutdown'])
    row['inspection_outputs'] = check_off(out,(0x08008000,))
    row.update(pass_=True,baseline_sha256=FULL_SHA,reset_attempts=0,
        runner_sha256=candidate.digest(RUNNER.read_bytes()),final_outputs_off=True,
        final_cpu_halted=True)
    print('INSPECT PASS: exact A626, B/private unchanged; no reset/START/programming',flush=True)


def motion(row):
    row['original_start_runner_invocations'] = 1  # Arm before uncertain subprocess result.
    result = subprocess.run([sys.executable,'-u',str(RUNNER),'--execute',
        '--expected-slot','A','--target-rpm','20'],capture_output=True,text=True,
        errors='replace',timeout=25)
    output = result.stdout+result.stderr
    row.update(motion_returncode=result.returncode,motion_output=output)
    print(output,flush=True)
    trial.motion_result_ok(result.returncode,output)
    # A reply alone is not evidence of closed-loop movement.
    positions = re.findall(r'Position change: ([+-]?[\d.]+) deg',output)
    speeds = re.findall(r'IN_MOTION .*?\bCTRL=([+-]?[\d.]+)rpm',output)
    if not positions or abs(float(positions[-1])) < .2 or not any(abs(float(v)) > 1 for v in speeds):
        raise RuntimeError('Movement feedback insufficient; not a closed-loop PASS')
    row.update(short_start_stop_pass=True,movement_feedback_observed=True,
        steady_speed_or_torque_accuracy_verified=False)


def execute(row, run, expected, before):
    port = uart = None
    try:
        port = open_port()
        uart = trial.Console(port)
        row.update(hardware_attempted=True,reset_attempts=1)
        debug(row,[*candidate.tx.prior.off_gate(0x08008000),
            *full_compare_commands(PRIVATE/(run+'-before.bin'),expected),
            'reset halt',*off_commands(),'reset run','shutdown'])
        trial.wait_health_confirmation(uart,row,trial.fields)
        ready = trial.sample(uart)
        row['samples'].append(ready)
        trial.validate_ready(ready)
        if ready['fw'].get('GEN') != str(META[5]):
            raise RuntimeError('Confirmed metadata generation changed; no START')
        row['preflight_pass'] = True
        port.close()
        motion(row)
        row['pass_'] = True
    finally:
        try:
            if row.get('hardware_attempted'):
                if uart and port.is_open:
                    try:
                        row['off_ack'] = uart.query('ANALOG SAFE',.8)
                    except Exception as error:
                        row['uart_off_error'] = str(error)
                final = PRIVATE/(run+'-final.bin')
                emergency_off(row,final)
                raw = final.read_bytes()
                row.update(final_sha256=candidate.digest(raw),final_metadata=list(latest_meta(raw)))
                ram = PRIVATE/(run+'-ram.bin')
                out = debug(row,['init',
                    'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "Not halted"}',
                    *off_report(),f'dump_image {{{ram.as_posix()}}} 0x20000000 0x20000','shutdown'])
                regs = check_off(out,(0,0x08000000,0x08008000,0x08040000))
                row.update(snapshot_vtor=regs['VTOR'],ram_backup=str(ram))
                if raw != before:
                    raise RuntimeError('Flash/metadata changed across confirmed-A reset/motion')
                row['all_flash_bytes_unchanged'] = True
                row['all_app_and_private_bytes_unchanged'] = True
        finally:
            if uart:
                row['uart'] = uart.lines
            if port and port.is_open:
                port.close()


def decode(row, data):
    # Exact ELF/trace layout only. Do not repin historical tools on disk.
    with ExitStack() as stack:
        stack.enter_context(patch.multiple(candidate,ELF=rolling.ELF,IMAGE=rolling.IMAGE))
        stack.enter_context(patch.multiple(previous,ELF=rolling.ELF,SIZE=rolling.SIZE))
        previous.decode(row,data)
    if row.get('trace'):
        t = row['trace']
        t['timing_scope'] = 'bounded motion plus startup; binary trace overhead included'
        row['acquisition'] = rolling.acquisition(t['header'],t['frames'],row.get('first_fault',{}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    modes = p.add_mutually_exclusive_group()
    modes.add_argument('--inspect-off',action='store_true')
    modes.add_argument('--execute-from-inspection',type=Path)
    p.add_argument('--drive-12v-off-motor-connected-fixed',action='store_true')
    p.add_argument('--drive-12v-on-no-alarm-fixed-05a-emergency-off-ready',action='store_true')
    args = p.parse_args()
    if args.inspect_off and not args.drive_12v_off_motor_connected_fixed:
        p.error('Physical drive OFF and connected/fixed no-load motor required')
    if args.execute_from_inspection and not args.drive_12v_on_no_alarm_fixed_05a_emergency_off_ready:
        p.error('Powered no-alarm fixed no-load motor, 0.5A limit and emergency OFF readiness required')
    data = rolling.image()
    if not (args.inspect_off or args.execute_from_inspection):
        print('OFFLINE PASS: pinned files only; no private data or device access')
        return 0
    mode = 'inspect' if args.inspect_off else 'motion'
    run = PREFIX+mode+'-'+str(time.time_ns())
    row = dict(pass_=False,mode=mode,image_sha256=rolling.SHA,elf_sha256=rolling.ELF_SHA,
        source=str(SOURCE),steps=[],samples=[],reset_attempts=0,hardware_attempted=False,
        original_start_runner_invocations=0,flash_programming=False,mailbox_write=False,
        automatic_retry=False,force_confirmation=False,protection_edits=False,
        motor_connected_fixed=True,physical_12v_off=bool(args.inspect_off),
        target_rpm=20,host_stop_seconds=.4,torque_accuracy_verified=False)
    try:
        expected,before = baseline(data)
        if mode == 'inspect':
            inspect(row,run,expected)
        else:
            load_inspection(args.execute_from_inspection)
            row['inspection'] = str(args.execute_from_inspection.resolve())
            execute(row,run,expected,before)
    except BaseException as error:
        row.update(pass_=False,failure=str(error))
        print('FAILED: '+str(error),flush=True)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:
                emergency_off(row,PRIVATE/(run+'-cleanup.bin'))
            except BaseException as cleanup:
                row['cleanup_failure'] = str(cleanup)
    finally:
        if mode == 'motion' and row.get('ram_backup'):
            try:
                decode(row,data)
            except BaseException as error:
                row.update(pass_=False,decode_failure=str(error))
        path = OUTPUT/(run+'.json')
        path.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(path),flush=True)
        if row.get('measured'):
            print(json.dumps(row['measured'],indent=2),flush=True)
    return 0 if row['pass_'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
