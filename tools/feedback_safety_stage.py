"""Exact A449 -> inactive B feedback guardian staging, NO reset/activation.

Physical 12 V OFF and motor U/V/W disconnected are required. Official UART
pw_transfer only; independent full private Flash backups verify all bytes
outside B unchanged, including metadata. Never START, sample or clear faults.
"""
import argparse
import hashlib
import json
import struct
import re
import subprocess
import time
from firmware_transfer_iap import ROOT, DEFAULT_CLIENT, image_info, stage, fields
from zero_retest_deploy import CLI, SN, compare_flash, require_confirmed
from zero_span100_acceptance import ADDRESSES, require_registers
from zero_async_clock_acceptance import locked_baseline
from median_control_acceptance import Console as BaseConsole
from phase_current_4a_stage import require_staged
from tighten_synthetic_acceptance import require_stopped, locked

IMAGE = ROOT / 'foc2_app_b/build/FeedbackSafety20261013/foc2.bin'
SHA = 'cdd2e3f21ad3806a828c19c690b54951ac4344058434848eeed762051a112591'
OLD_A = '350408d649507d3b9a360b778bedd14be88c433fde27a811f35938888e5cf241'
OLD_B = 'f725799506142c1cb55d47ce39069e14fc1fa3519508f0374528c628cf20fc0f'
OUTPUT = ROOT / 'safety_backups/feedback-safety-live-20261013'
GEN = 449

def image():
    data = IMAGE.read_bytes()
    if len(data) != 207024 or image_info(data)[0] != 'B' or hashlib.sha256(data).hexdigest() != SHA:
        raise RuntimeError('Exact offline-tested hard-off guardian B required')
    for marker in (b'COMPUTE_ONLY=1 MOTOR_QUALIFIED=0', b'SD=MOE=CCER=0',
                   b'RAW=VALIDITY_ONLY FILTERED=2_OF_3', b'GUARD_US=25',
                   b'SCOPE=PAIR_CHECK_TO_FOC_END', b'TIMEOUT_TEST_REJECTED'):
        if marker not in data: raise RuntimeError('Missing hard-off guardian marker')
    if b'OPEN_LOAD_ONLY' in data: raise RuntimeError('Bridge fixture forbidden')
    pc = (struct.unpack_from('<I', data, 4)[0] & ~1) - 0x08040000
    if data[pc:pc+2] != b'\x72\xb6': raise RuntimeError('Reset IRQ mask missing')
    return data

def baseline(data):
    row = locked_baseline(data, known={'A': frozenset((OLD_A,)), 'B': frozenset((OLD_B,))})
    if row['current'] != 'A' or row['generation'] != GEN:
        raise RuntimeError('Only exact confirmed A449/B446 baseline admitted')
    return row

class Console(BaseConsole):
    def command(self, text, timeout=5):
        if not re.fullmatch(r'FW (STATUS|BEGIN [0-9]+ [0-9A-F]{8})|ANALOG SAFE STATUS|'
                            r'XFER ENGINE (STATUS|CLOSE|[0-9A-F]{2,192})', text):
            raise ValueError('Stage only: no activation, reset, sample or motion')
        return super().command(text, timeout)

    def query(self, text, timeout=2):
        if text not in ('FW STATUS', 'ANALOG SAFE STATUS', 'BENCH STATUS'):
            raise ValueError('Stage-only read queries')
        return super().query(text, timeout)

def main(profile=None):
    # Explicit pinned profiles share the stage-only engine, not its identity.
    # Historical default constants and artifacts remain unchanged.
    if profile is None:
        import sys
        profile = sys.modules[__name__]
    IMAGE, SHA, OUTPUT, GEN = profile.IMAGE, profile.SHA, profile.OUTPUT, profile.GEN
    image, baseline = profile.image, profile.baseline
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-stage', action='store_true')
    parser.add_argument('--drive-12v-off', action='store_true')
    parser.add_argument('--motor-disconnected', action='store_true')
    args = parser.parse_args()
    if not (args.allow_stage and args.drive_12v_off and args.motor_disconnected):
        parser.error('Stage permission, physical 12 V OFF and disconnected motor required')
    data = image()
    if not DEFAULT_CLIENT.is_file(): parser.error('Official transfer client unavailable')
    OUTPUT.mkdir(exist_ok=True)
    private = OUTPUT / 'private'; private.mkdir(exist_ok=True)
    subprocess.run(['icacls', str(private), '/inheritance:r', '/grant:r',
                    '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'],
                   capture_output=True, check=True)
    run = str(time.time_ns()); target = OUTPUT / f'stage-{run}.json'
    record = dict(pass_=False, stage_only=True, image_sha256=SHA, target_slot='B',
                  physical_drive_off_user_confirmed=True, motor_disconnected_user_confirmed=True,
                  fw_end=False, resets=0, activation=False, motion_commands=False,
                  sampling_commands=False, motor_qualified=False, steps=[])
    port = uart = None

    def cli(*tokens):
        if not tokens or tokens[0] not in ('-u', '-r32'): raise ValueError('Read-only probe only')
        p = subprocess.run([CLI, '-c', 'port=SWD', 'mode=HOTPLUG', 'freq=1000', 'sn='+SN,
                            *map(str, tokens)], capture_output=True, text=True,
                           errors='replace', timeout=30)
        out = p.stdout+p.stderr
        record['steps'].append(dict(args=list(map(str, tokens)), code=p.returncode, output=out))
        if p.returncode or 'Error:' in out: raise RuntimeError('Read failed; no retry/reset')
        return out

    def capture(name):
        path = private / f'{run}-{name}.bin'
        cli('-u', '0x08000000', '0x80000', path)
        raw = path.read_bytes()
        if len(raw) != 0x80000: raise RuntimeError('Incomplete full Flash capture')
        record[name+'_backup'] = str(path)
        return raw

    def outputs():
        return require_registers(cli(*(x for a in ADDRESSES for x in ('-r32', hex(a), '4'))), 'A')

    try:
        before = capture('before')
        record['baseline'] = baseline(before)
        record['before_outputs'] = outputs()
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=2)
        port.dtr = port.rts = False; port.port = 'COM5'; port.open(); uart = Console(port)
        record['before_fw'] = require_confirmed(uart.query('FW STATUS'), 'A')
        if record['before_fw'].get('GEN') != str(GEN): raise RuntimeError('UART/Flash mismatch')
        record['before_safe'] = fields(uart.query('ANALOG SAFE STATUS'))
        if not locked(record['before_safe']): raise RuntimeError('Output latch absent')
        record['before_bench'] = fields(uart.query('BENCH STATUS'))
        require_stopped(' '.join(f'{k}={v}' for k, v in record['before_bench'].items()))
        record['stage_attempted'] = True
        stage(uart, IMAGE, DEFAULT_CLIENT, allow_reset=False)
        after = capture('staged')
        record['protected_flash'] = compare_flash(before, after, data, 'B', staged=True)
        if before[:0x40000] != after[:0x40000] or before[0x78000:] != after[0x78000:]:
            raise RuntimeError('Bytes outside inactive B changed')
        record['all_bytes_outside_b_unchanged'] = True
        record['after_outputs'] = outputs()
        record['staged_fw'] = require_staged(uart.query('FW STATUS'), GEN, data)
        # While FW ACTIVE=1 the app gates BENCH and ANALOG SAFE queries.
        # Fresh independent register proof is authoritative for output OFF;
        # do not clear/abort the transaction just to make a query work.
        record['post_stage_console_diagnostics_gated'] = True
        record['pass_'] = True
        print('GUARDIAN STAGE PASS: inactive B verified; A/bootloader/KVS/parameters/metadata unchanged.', flush=True)
        print('NO RESET, ACTIVATION, SAMPLE OR MOTOR COMMAND.', flush=True)
    except BaseException as error:
        record['failure'] = str(error); raise
    finally:
        if uart: record['uart'] = uart.lines
        if port: port.close()
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print('Evidence: '+str(target), flush=True)

if __name__ == '__main__': main()
