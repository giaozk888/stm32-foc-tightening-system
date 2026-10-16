"""Pinned original-task reconnect acceptance. Power HARD OFF, motor disconnected.

stage: official Transfer to inactive A only; no reset or commit.
commit: one FW END, normal health confirmation, one bounded original-task
TIGHTEN arithmetic run, then stopped-ADC guardian test and output readback.
Never enable bridge, clear faults, force confirmation or retry activation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import time
import zlib

from firmware_transfer_iap import ROOT, Uart, fields, image_info, stage, DEFAULT_CLIENT
from zero_retest_deploy import CLI, SN, compare_flash, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers
from zero_async_clock_acceptance import locked_baseline
from powered_boot_probe import require_staged
from tighten_synthetic_acceptance import locked, confirmed, require_stopped
from median_control_acceptance import require_zero
from feedback_safety_commit import protection, timing, fault_fields, timeout_result

IMAGE = ROOT/'foc2_app_a/build/ControlChainReconnect/foc2.bin'
SHA = '3a72c69ca6bed808f3d4cebf17f957569e355b1654c7880dc9aa55c4538d8a32'
REFERENCE = ROOT/'safety_backups/filtered-bridge-live-20261013/capture-1791896441437660100.json'
OUTPUT = ROOT/'safety_backups/control-chain-live-20261013'
OLD = {'A': frozenset(('8769374cec2038667aa505bbfbd909b5ddb2010d95dccbbb2294a498aad1fe45',)),
       'B': frozenset(('eb13779af465650dc7a82ac99b0a494e1e0796bb783a2e76b5b10020d4779ca9',))}
READ = frozenset(('FW STATUS', 'ZERO STATUS', 'ANALOG SAFE STATUS', 'STATUS',
    'BENCH STATUS', 'BENCH ZERO', 'BENCH ZERO FILTER', 'BENCH STACK',
    'BENCH PROTECTION', 'BENCH PROTECTION FAULT', 'BENCH PROTECTION TIMING',
    'BENCH CHAIN STATUS'))

def image():
    data = IMAGE.read_bytes()
    if len(data) != 210280 or hashlib.sha256(data).hexdigest() != SHA or image_info(data)[0] != 'A':
        raise RuntimeError('Exact offline-tested hard-OFF A image required')
    reset = (struct.unpack_from('<I', data, 4)[0] & ~1) - 0x08008000
    guard = struct.unpack_from('<I', data, (16+55)*4)[0]
    if data[reset:reset+2] != b'\x72\xb6' or not guard&1 or not 0x08008000 <= guard&~1 < 0x08008000+len(data):
        raise RuntimeError('Reset mask/strong independent guard missing')
    for marker in (b'OK BENCH CHAIN HARD_OFF=1 MOTOR_QUALIFIED=0',
                   b'COMPUTE_ONLY=1 MOTOR_QUALIFIED=0', b'SD=MOE=CCER=0',
                   b'SCOPE=PAIR_CHECK_TO_FOC_END', b'RAW=VALIDITY_ONLY FILTERED=2_OF_3'):
        if marker not in data: raise RuntimeError('Missing pinned compute-only marker')
    if b'DISCONNECTED_50MS' in data: raise RuntimeError('Bridge fixture forbidden')
    return data

def baseline(raw):
    identity = locked_baseline(raw, known=OLD)
    receipt = json.loads(REFERENCE.read_text('utf-8'))
    backup = Path(receipt['final_backup']).resolve()
    if (identity['current'] != 'B' or identity['generation'] != 463 or
        receipt.get('pass_') is not True or receipt.get('final_safe_locked') is not True or
        backup.parent != (REFERENCE.parent/'private').resolve() or raw != backup.read_bytes()):
        raise RuntimeError('Exact confirmed B463/A460 private baseline required')
    return identity

class Console(Uart):
    def __init__(self, port, commit=False):
        super().__init__(port); self.request = 97000
        self.commit = commit; self.ends = 0; self.starts = set(); self.lines = []
    def dispatch(self, line):
        if line: self.lines.append(line)
        super().dispatch(line)
        if line and any(s in line for s in ('BOOT HEALTH:', 'ISOLATED ZERO', 'TIGHTEN:', 'RTOS-FOC', 'ISOLATED CONCURRENCY:')):
            print(line, flush=True)
        if 'HardFault' in line or 'CREATE FAILED' in line:
            raise RuntimeError('Task/startup fault; no retry')
    def command(self, text, timeout=5):
        if text == 'FW END':
            if not self.commit or self.ends: raise ValueError('One commit only')
            self.ends += 1
        elif self.commit: raise ValueError('No programming during commit')
        return super().command(text, timeout)
    def query(self, text, timeout=2):
        writes = {'BENCH CHAIN TIGHTEN', 'BENCH CHAIN STOP', 'BENCH STOP', 'BENCH PROTECTION TEST TIMEOUT'}
        if text not in READ and not (self.commit and text in writes):
            raise ValueError('No actuation, clear-fault, restart or variable setpoint')
        if text in ('BENCH CHAIN TIGHTEN', 'BENCH PROTECTION TEST TIMEOUT'):
            if text in self.starts: raise ValueError('Single attempt, never resend')
            self.starts.add(text)
        self.request += 1; request = self.request
        self.port.write(f'{request} {text}\r\n'.encode('ascii'))
        end = time.monotonic()+timeout
        while time.monotonic() < end:
            line = self.read_line(.05)
            if line is None: continue
            self.dispatch(line)
            if line.startswith(f'{request} '):
                if not line.startswith(f'{request} OK '): raise RuntimeError(line)
                print(line, flush=True); return line
        raise TimeoutError('No ACK; no resend: '+text)

def stage_evidence(path, data):
    path = path.resolve()
    if path.parent != OUTPUT.resolve(): raise RuntimeError('Stage evidence directory mismatch')
    receipt = json.loads(path.read_text('utf-8'))
    if (receipt.get('pass_') is not True or receipt.get('mode') != 'stage' or
        receipt.get('image_sha256') != SHA or not receipt.get('all_bytes_outside_a_unchanged')):
        raise RuntimeError('Exact successful stage receipt required')
    paths = [Path(receipt[k+'_backup']).resolve() for k in ('before', 'staged')]
    if any(p.parent != (OUTPUT/'private').resolve() for p in paths): raise RuntimeError('Private path mismatch')
    original, staged = (p.read_bytes() for p in paths)
    baseline(original); compare_flash(original, staged, data, 'A', staged=True)
    return original, staged

def chain(line):
    row = fields(line)
    if row.get('HARD_OFF') != '1' or row.get('MOTOR_QUALIFIED') != '0':
        raise RuntimeError('Not the hard-OFF chain')
    return row

def original_chain_result(samples, final):
    """Validate actual SPD wire spelling and original IQ/application stages."""
    if (final.get('ACTIVE') != '0' or final.get('USED') != '1' or final.get('KIND') != '3' or
        int(final.get('CURRENT', '0')) < 20000 or int(final.get('OUTER', '0')) < 500 or
        int(final.get('APP', '0')) < 100):
        raise RuntimeError('Original-task execution counts failed')
    if not any('MODE=SPD' in s['status'] and re.search(r'IqRef=-?[1-9]\d*mA', s['status']) for s in samples):
        raise RuntimeError('No original speed PI to Iq execution evidence')
    states = [fields(s['status']) for s in samples]
    required = {1:'SPD', 2:'IDLE', 3:'IQ', 4:'IQ', 5:'IQ', 6:'IQ', 7:'IQ', 9:'IDLE'}
    if not all(any(s.get('STAGE') == str(k) and s.get('MODE') == mode for s in states) for k,mode in required.items()):
        raise RuntimeError('Complete original application stage progression not observed')
    if any(s.get('FLT') != '0' for s in states) or not any(s.get('STAGE') == '9' and s.get('OUTCOME') == 'OK' for s in states):
        raise RuntimeError('Application cycle did not complete without fault')
    ms = int(final['MS'])
    if not 1000 <= ms < 5000: raise RuntimeError('Unbounded/missing chain interval')
    hz = int(final['CURRENT'])*1000/ms
    if not 18000 <= hz <= 22000: raise RuntimeError('Current-loop count/interval mismatch')
    return dict(control_chain_pass=True, motor_qualified=False, elapsed_ms=ms,
                current_loop_count=int(final['CURRENT']), diagnostic_current_rate_hz=hz,
                outer_steps=int(final['OUTER']), application_steps=int(final['APP']),
                stages=list(required), mechanical_contact_verified=False, torque_accuracy_verified=False)

def trial_request(data, fw_line):
    """Same START_TRIAL packet as FW END; never CONFIRM or SET_CONFIRMED.

    Caller must first prove complete Flash equals the exact stage receipt,
    including protected bytes and old confirmed B463 metadata.
    """
    fw = require_confirmed(fw_line, 'B')
    if fw.get('GEN') != '463' or fw.get('TARGET') != 'A' or image_info(data)[0] != 'A':
        raise RuntimeError('Existing-image trial requires confirmed B463, inactive A')
    head = struct.pack('<7I', 0x584F424D, 1, 2, 2, 1, len(data), zlib.crc32(data))
    words = struct.unpack('<8I', head+struct.pack('<I', zlib.crc32(head)))
    return ('-w32', '0x2001FFC0', '0', '-w32', '0x2001FFC4',
            *map(hex, words[1:]), '-w32', '0x2001FFC0', hex(words[0]), '-rst')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('stage', 'commit', 'trial-existing'))
    parser.add_argument('--drive-12v-off', action='store_true')
    parser.add_argument('--motor-disconnected', action='store_true')
    parser.add_argument('--powered-inputs-ready', action='store_true')
    parser.add_argument('--stage-evidence', type=Path)
    args = parser.parse_args()
    if not args.motor_disconnected: parser.error('Motor disconnected required')
    if args.mode == 'stage' and not args.drive_12v_off: parser.error('Physical drive OFF required')
    if args.mode != 'stage' and not (args.powered_inputs_ready and args.stage_evidence):
        parser.error('Powered sensing + stage receipt required')
    data = image(); OUTPUT.mkdir(parents=True, exist_ok=True)
    private = OUTPUT/'private'; private.mkdir(exist_ok=True)
    subprocess.run(['icacls', str(private), '/inheritance:r', '/grant:r',
                    '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'], capture_output=True, check=True)
    run = str(time.time_ns()); target = OUTPUT/f'{args.mode}-{run}.json'
    record = dict(pass_=False, mode=args.mode, image_sha256=SHA, target_slot='A',
                  motor_qualified=False, bridge_enabled=False, motor_start_sent=False,
                  force_confirm=False, direct_metadata_write=False, automatic_retry=False,
                  disconnected_user_confirmed=True, steps=[])
    port = uart = None
    def cli(*tokens):
        if not tokens or tokens[0] not in ('-u', '-r32'): raise ValueError('Read-only SWD only')
        result = subprocess.run([CLI, '-c', 'port=SWD', 'mode=HOTPLUG', 'freq=1000', 'sn='+SN,
            *map(str, tokens)], capture_output=True, text=True, errors='replace', timeout=30)
        out = result.stdout+result.stderr
        record['steps'].append(dict(args=list(map(str, tokens)), code=result.returncode, output=out))
        if result.returncode or 'Error:' in out: raise RuntimeError('Read-only probe failed; no retry')
        return out
    def capture(name):
        path = private/f'{run}-{name}.bin'; cli('-u', '0x08000000', '0x80000', path)
        raw = path.read_bytes(); record[name+'_backup'] = str(path)
        if len(raw) != 0x80000: raise RuntimeError('Incomplete Flash backup')
        return raw
    def outputs(slot):
        return require_registers(cli(*(x for a in ADDRESSES for x in ('-r32', hex(a), '4'))), slot)
    try:
        before = capture('before')
        if args.mode == 'stage':
            original = before; record['baseline'] = baseline(before)
        else:
            original, staged = stage_evidence(args.stage_evidence, data)
            if before != staged: raise RuntimeError('Flash differs from successful uncommitted stage')
            record['stage_evidence'] = str(args.stage_evidence)
        record['before_outputs'] = outputs('B')
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=2)
        port.dtr = port.rts = False; port.port = 'COM5'; port.open()
        uart = Console(port, commit=args.mode != 'stage')
        if args.mode == 'stage':
            fw = require_confirmed(uart.query('FW STATUS'), 'B')
            if fw.get('GEN') != '463': raise RuntimeError('UART/Flash identity mismatch')
            require_service(uart.query('ZERO STATUS'))
            if not locked(fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('Output latch absent')
            record['stage_attempted'] = True
            stage(uart, IMAGE, DEFAULT_CLIENT, allow_reset=False)
            after = capture('staged')
            record['staged_flash'] = compare_flash(before, after, data, 'A', staged=True)
            if before[:0x8000] != after[:0x8000] or before[0x40000:] != after[0x40000:]:
                raise RuntimeError('Outside inactive A changed')
            record['all_bytes_outside_a_unchanged'] = True
            record['staged_outputs'] = outputs('B')
            record['staged_fw'] = uart.query('FW STATUS')
            require_staged(record['staged_fw'], 'SOURCE=SWD SD=0 MOE=0 CEN=0', data)
        else:
            fw_line = uart.query('FW STATUS')
            if args.mode == 'trial-existing':
                tokens = trial_request(data, fw_line)
                require_service(uart.query('ZERO STATUS'))
                if not locked(fields(uart.query('ANALOG SAFE STATUS'))):
                    raise RuntimeError('Existing-image trial output latch absent')
                record['commit_method'] = 'EXISTING_BOOTLOADER_START_TRIAL_SRAM'
                record['host_flash_write'] = False
                record['commit_attempted'] = True
                # Exact single request, magic last and reset; no register writes
                # to output enables, Flash, boot metadata or force-confirm.
                result = subprocess.run([CLI, '-c', 'port=SWD', 'mode=HOTPLUG',
                    'freq=1000', 'sn='+SN, *tokens], capture_output=True, text=True,
                    errors='replace', timeout=30)
                record['trial_request'] = dict(args=list(tokens), code=result.returncode,
                                              output=result.stdout+result.stderr)
                if result.returncode or 'Error:' in result.stdout+result.stderr:
                    raise RuntimeError('Trial request outcome unverified; no resend')
            else:
                require_staged(fw_line, 'SOURCE=SWD SD=0 MOE=0 CEN=0', data)
                record['commit_attempted'] = True
                try: record['commit_reply'] = uart.command('FW END', 20)
                except TimeoutError: record['commit_ack_uncertain'] = True
            until = time.monotonic()+90; seen = False
            while time.monotonic() < until:
                try: fw = fields(uart.query('FW STATUS', .5))
                except TimeoutError: continue
                record['last_fw'] = fw
                if fw.get('CURRENT') == 'A':
                    seen = True
                    record['last_protection'] = p = fields(uart.query('BENCH PROTECTION'))
                    if p.get('STATE') == '2':
                        record['startup_fault'] = fault_fields(uart.query('BENCH PROTECTION FAULT'))
                        raise RuntimeError('Startup guardian fault; no retry')
                    if confirmed(fw, 'A'): break
                elif confirmed(fw, 'B') and (seen or int(fw.get('GEN', '0')) > 463):
                    raise RuntimeError('Normal boot rollback; no forced confirmation')
                uart.poll(.1)
            else: raise TimeoutError('No normal confirmation; no reset retry')
            record['confirmed_fw'] = require_confirmed(uart.query('FW STATUS'), 'A')
            if not locked(fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('Compute latch absent')
            record['zero'] = require_zero(uart.query('BENCH ZERO'))
            record['zero_filter'] = fields(uart.query('BENCH ZERO FILTER'))
            record['before_protection'] = protection(uart.query('BENCH PROTECTION'), repair_budget=(6,4))
            initial = chain(uart.query('BENCH CHAIN STATUS'))
            if initial.get('USED') != '0' or initial.get('ACTIVE') != '0': raise RuntimeError('Not fresh chain')
            record['chain_start'] = uart.query('BENCH CHAIN TIGHTEN')
            record['chain_observations'] = samples = []
            # Leave generous time before the independent five-second lease.
            start = time.monotonic()
            while time.monotonic()-start < 2.8:
                c = chain(uart.query('BENCH CHAIN STATUS'))
                status = uart.query('STATUS')
                p = protection(uart.query('BENCH PROTECTION'), repair_budget=(6,4))
                samples.append(dict(chain=c, status=status, protection=p))
                uart.poll(.12)
            record['chain_stop'] = uart.query('BENCH CHAIN STOP'); uart.poll(.05)
            record['chain_final'] = c = chain(uart.query('BENCH CHAIN STATUS'))
            record['chain_result'] = original_chain_result(samples, c)
            record['after_timing'] = timing(uart.query('BENCH PROTECTION TIMING'))
            record['stacks'] = stacks = fields(uart.query('BENCH STACK'))
            if any(int(stacks.get(k,'0')) < 256 for k in ('MOTOR','ROUTER','PROTO','TRANSFER')):
                raise RuntimeError('Reported task stack margin failed')
            record['tightening_stack_measured'] = False
            record['timeout_injection'] = uart.query('BENCH PROTECTION TEST TIMEOUT'); uart.poll(.03)
            record['timeout'] = timeout_result(uart.query('BENCH PROTECTION'),
                uart.query('BENCH PROTECTION FAULT'), uart.query('BENCH PROTECTION TIMING'))
            require_stopped(uart.query('BENCH STATUS'))
            record['final_outputs'] = outputs('A')
            record['final_flash'] = compare_flash(original, capture('final'), data, 'A')
            record['final_fw'] = require_confirmed(uart.query('FW STATUS'), 'A')
        record['pass_'] = True
        print(args.mode.upper()+' PASS: original-task hard-OFF profile; no powered motor qualification.', flush=True)
    except BaseException as error:
        record['failure'] = str(error); raise
    finally:
        if uart and record.get('commit_attempted'):
            try:
                slot = fields(uart.query('FW STATUS')).get('CURRENT')
                if slot == 'A':
                    record['cleanup_fault'] = fault_fields(uart.query('BENCH PROTECTION FAULT'))
                    uart.query('BENCH CHAIN STOP'); require_stopped(uart.query('BENCH STOP'))
                elif slot == 'B': require_service(uart.query('ZERO STATUS'))
                else: raise RuntimeError('Unknown final slot')
                if not locked(fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('Final latch absent')
                record['cleanup_outputs'] = outputs(slot); record['final_safe_locked'] = True
            except BaseException as error:
                record['pass_'] = False; record['cleanup_failure'] = str(error)
        if uart: record['uart'] = uart.lines
        if port: port.close()
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print('Evidence: '+str(target), flush=True)

if __name__ == '__main__': main()
