"""Exact B457 -> inactive A signal-only qualification fixture.

Drive power physically OFF, motor disconnected. Official UART Transfer only;
verify all protected Flash before one FW END. Bootloader confirms its own
locked service. Guard test only; no zero sampling/PWM/bridge/motor command.
No direct metadata write, forced confirmation, host reset or retry.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import time

from firmware_transfer_iap import ROOT, DEFAULT_CLIENT, image_info, stage, fields
from switch_feedback_acceptance import Console as BaseConsole, require_switch
from switch_feedback_timerfix_acceptance import guard_result
from powered_boot_probe import require_staged
from zero_async_clock_acceptance import locked_baseline
from zero_retest_deploy import CLI, SN, compare_flash, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers
from tighten_synthetic_acceptance import locked, require_stopped

MANIFEST = ROOT/'firmware_common/SIX_SIGNAL_A_MANIFEST.json'
IMAGE = ROOT/'foc2_app_a/build/SixSignalQualification20261013/foc2.bin'
SHA = '8769374cec2038667aa505bbfbd909b5ddb2010d95dccbbb2294a498aad1fe45'
OLD_A = '350408d649507d3b9a360b778bedd14be88c433fde27a811f35938888e5cf241'
OLD_B = '89f6e449c105bb4eb8ea4d5e52fecea8dc7443061abb1f175758a637e2a6de00'
REFERENCE = ROOT/'safety_backups/feedback-budget2x-live-20261013/retest-1791891369744929400.json'
OUTPUT = ROOT/'safety_backups/six-signal-live-20261013'


def image():
    manifest = json.loads(MANIFEST.read_text('utf-8'))
    data = IMAGE.read_bytes()
    if (manifest['sha256'] != SHA or manifest['bridge_compiled'] is not False or
            manifest['image'] != str(IMAGE.relative_to(ROOT)).replace('\\','/') or
            len(data) != manifest['bytes'] or len(data) != 149828 or
            image_info(data)[0] != 'A' or hashlib.sha256(data).hexdigest() != SHA):
        raise RuntimeError('Exact signal-only A fixture required')
    pc = (struct.unpack_from('<I',data,4)[0]&~1)-0x08008000
    irq = struct.unpack_from('<I',data,(16+55)*4)[0]
    if data[pc:pc+2] != b'\x72\xb6' or not irq&1 or not 0x08008000 <= irq&~1 < 0x08008000+len(data):
        raise RuntimeError('Reset masking/independent cutoff vector missing')
    for marker in (b'MOTOR_READY=0 BRIDGE_COMPILED=0', b'BRIDGE_COMPILED_OUT',
                   b'POLICY=OBSERVER_ONLY', b'IRQ_SR='):
        if marker not in data: raise RuntimeError('Signal-only identity missing')
    return data


def baseline_identity(raw):
    row = locked_baseline(raw,known={'A':frozenset((OLD_A,)), 'B':frozenset((OLD_B,))})
    if row['current'] != 'B' or row['generation'] != 457:
        raise RuntimeError('Exact confirmed B457 required; no automatic adaptation')
    return row


def baseline(raw):
    row = baseline_identity(raw)
    receipt = json.loads(REFERENCE.read_text('utf-8'))
    if (receipt.get('pass_') is not True or receipt.get('final_safe_locked') is not True or
            receipt.get('all_flash_unchanged') is not True or
            receipt.get('image_sha256') != OLD_B or receipt.get('final_fw',{}).get('GEN') != '457'):
        raise RuntimeError('Exact prior B457 locked closeout required')
    path = Path(receipt['final_backup']).resolve()
    if path.parent != (REFERENCE.parent/'private').resolve() or raw != path.read_bytes():
        raise RuntimeError('Flash differs from private verified baseline')
    return row


class Console(BaseConsole):
    def query(self,text,timeout=2):
        if text not in ('FW STATUS','ANALOG SAFE STATUS','BENCH STATUS','ZERO STATUS',
                        'SWITCH STATUS','SWITCH START GUARD','SWITCH ABORT'):
            raise ValueError('Deployment/guard only; no sampling or PWM')
        return super().query(text,timeout)

    def command(self,text,timeout=5):
        if not re.fullmatch(r'FW (STATUS|END|BEGIN [0-9]+ [0-9A-F]{8})|ANALOG SAFE STATUS|'
                            r'XFER ENGINE (STATUS|CLOSE|[0-9A-F]{2,192})',text):
            raise ValueError('No motion, fault clear, direct metadata or reset command')
        return super().command(text,timeout)


def signal_status(line,**kwargs):
    row = require_switch(line,**kwargs)
    if row.get('BRIDGE_COMPILED') != '0' or row.get('SD') != '0':
        raise RuntimeError('Bridge must be compiled out and SD low')
    return row


def observe(uart,seconds=90):
    deadline = time.monotonic()+seconds
    seen = False
    while time.monotonic() < deadline:
        try: fw = fields(uart.query('FW STATUS',.5))
        except TimeoutError: continue
        if fw.get('CURRENT') != 'A':
            if seen or fw.get('PENDING') == '-':
                raise RuntimeError('Trial returned to B; no host retry or force confirm')
            uart.poll(.1); continue
        seen = True
        require_service(uart.query('ZERO STATUS',1))
        signal_status(uart.query('SWITCH STATUS',1))
        if fw.get('CONFIRMED') == 'A' and fw.get('PENDING') == '-':
            return require_confirmed(' '.join(f'{k}={v}' for k,v in fw.items()),'A')
        uart.poll(.1)
    raise TimeoutError('No normal service confirmation; no host reset/retry')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-inactive-a',action='store_true')
    parser.add_argument('--drive-12v-off',action='store_true')
    parser.add_argument('--motor-disconnected',action='store_true')
    args = parser.parse_args()
    if not (args.allow_inactive_a and args.drive_12v_off and args.motor_disconnected):
        parser.error('Inactive-A permission, physical drive OFF and disconnected motor required')
    data = image()
    import serial  # Validate host dependency before touching the programmer.
    if not DEFAULT_CLIENT.is_file(): parser.error('Official Transfer client unavailable')
    OUTPUT.mkdir(parents=True,exist_ok=True)
    private = OUTPUT/'private'; private.mkdir(exist_ok=True)
    subprocess.run(['icacls',str(private),'/inheritance:r','/grant:r',
                    '*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F'],check=True,capture_output=True)
    run = str(time.time_ns()); target = OUTPUT/f'deploy-{run}.json'
    record = dict(pass_=False,image_sha256=SHA,target_slot='A',bridge_enabled=False,
                  motion_commands=False,pwm_enabled=False,adc_capture=False,force_confirm=False,
                  motor_qualified=False,host_reset=False,automatic_retry=False,steps=[])
    port = uart = None
    before = None
    def cli(*tokens):
        if not tokens or tokens[0] not in ('-u','-r32'): raise ValueError('Read-only SWD')
        proc = subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,*map(str,tokens)],
                              capture_output=True,text=True,errors='replace',timeout=30)
        out = proc.stdout+proc.stderr
        record['steps'].append(dict(args=list(map(str,tokens)),code=proc.returncode,output=out))
        if proc.returncode or 'Error:' in out: raise RuntimeError('Probe failed; no retry')
        return out
    def capture(name):
        path = private/f'{run}-{name}.bin'; cli('-u','0x08000000','0x80000',path)
        record[name+'_backup'] = str(path)
        raw = path.read_bytes()
        if len(raw) != 0x80000: raise RuntimeError('Incomplete private backup')
        return raw
    def outputs(slot):
        return require_registers(cli(*(x for a in ADDRESSES for x in ('-r32',hex(a),'4'))),slot)
    try:
        before = capture('before'); record['baseline'] = baseline(before)
        record['before_outputs'] = outputs('B')
        port = serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr = port.rts = False; port.port = 'COM5'; port.open(); uart = Console(port)
        record['before_fw'] = require_confirmed(uart.query('FW STATUS'),'B')
        if record['before_fw'].get('GEN') != '457': raise RuntimeError('UART/Flash mismatch')
        if not locked(fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('Output latch absent')
        require_stopped(uart.query('BENCH STATUS'))
        print('BASELINE PASS: exact stopped B457; private backup retained',flush=True)
        record['stage_attempted'] = True
        stage(uart,IMAGE,DEFAULT_CLIENT,allow_reset=False)
        staged = capture('staged')
        record['staged_flash'] = compare_flash(before,staged,data,'A',staged=True)
        if before[:0x8000] != staged[:0x8000] or before[0x40000:] != staged[0x40000:]:
            raise RuntimeError('Bytes outside inactive A changed')
        record['all_bytes_outside_a_unchanged'] = True
        record['staged_outputs'] = outputs('B')
        line = uart.query('FW STATUS')
        if fields(line).get('GEN') != '457': raise RuntimeError('Staged generation differs')
        require_staged(line,'SOURCE=SWD SD=0 MOE=0 CEN=0',data)
        print('STAGE PASS: inactive A exact; B/boot/data/metadata unchanged',flush=True)
        record['commit_attempted'] = True
        try: uart.command('FW END',20)
        except TimeoutError: print('END ACK uncertain: observe once, never resend',flush=True)
        record['confirmed'] = observe(uart)
        record['before_guard_zero'] = require_service(uart.query('ZERO STATUS'))
        fresh = signal_status(uart.query('SWITCH STATUS'))
        if fresh.get('ATTEMPTS') != '0' or fresh.get('N') != '0': raise RuntimeError('Not fresh fixture')
        record['start_guard'] = signal_status(uart.query('SWITCH START GUARD'),mode=4)
        time.sleep(.25)  # Timer alone runs; no UART/SWD polling during guard.
        record['guard_line'] = uart.query('SWITCH STATUS')
        signal_status(record['guard_line'],mode=4)
        record['final_outputs'] = outputs('A')
        record['final_fw'] = require_confirmed(uart.query('FW STATUS'),'A')
        record['final_zero'] = require_service(uart.query('ZERO STATUS'))
        record['final_flash'] = compare_flash(before,capture('final'),data,'A')
        if record['final_flash']['generation'] != int(record['final_fw']['GEN']):
            raise RuntimeError('Final UART/Flash generation mismatch')
        record['guard'] = guard_result(record['guard_line'])
        record['final_safe_locked'] = record['pass_'] = True
        print('SIGNAL FIXTURE DEPLOY PASS: A confirmed, guard PASS, SD/PWM OFF; no motor test',flush=True)
    except BaseException as error:
        record['failure'] = str(error)
        # Guard is the ONLY start allowed here. No power start occurred; do not
        # inject a reset or repeat uncertain Transfer/commit on a failed run.
        if uart and record.get('commit_attempted'):
            try:
                fw = fields(uart.query('FW STATUS',2)); record['failure_fw'] = fw
                if fw.get('CURRENT') == 'A':
                    record['abort'] = signal_status(uart.query('SWITCH ABORT'))
                    require_service(uart.query('ZERO STATUS'))
                elif fw.get('CURRENT') == 'B': require_stopped(uart.query('BENCH STATUS'))
                else: raise RuntimeError('Unknown failure slot')
                record['failure_outputs'] = outputs(fw['CURRENT'])
                record['failure_backup'] = str(private/f'{run}-failure.bin')
                capture('failure')
                record['failure_safe_locked'] = True
            except BaseException as cleanup: record['cleanup_failure'] = str(cleanup)
        raise
    finally:
        if uart: record['uart'] = uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)


if __name__ == '__main__': main()
