"""One reset of exact confirmed hard-OFF A466; stopped-ADC guard test only.

No Flash/metadata/mailbox writes, START, bridge enable, fault clear, repeated
reset or automatic retry. Physical motor connection/power is not inferred
from UART: both known images have no automatic power output. Zero readiness
is checked after reset; missing drive supply fails closed without retry.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
import serial
import control_chain_reconnect_acceptance as profile
from feedback_safety_commit import Console as GuardConsole, protection, timing, timeout_result, fault_fields

REFERENCE = profile.OUTPUT/'readback-1791939314451047000.json'

class Console(GuardConsole):
    def command(self, *args, **kwargs):
        raise ValueError('No firmware activation/programming')

def require_a466(line):
    fw = profile.require_confirmed(line, 'A')
    if fw.get('GEN') != '466': raise RuntimeError('Only confirmed A466; no reset/retry')
    return fw

def verified_baseline(raw):
    receipt = json.loads(REFERENCE.read_text('utf-8'))
    if not receipt.get('readback_pass') or receipt.get('fw',{}).get('GEN') != '466':
        raise RuntimeError('Exact completed A466 readback required')
    backup = Path(receipt['final_backup']).resolve()
    if backup.parent != (profile.OUTPUT/'private').resolve() or raw != backup.read_bytes():
        raise RuntimeError('Flash differs from verified A466/B463 baseline')
    data = profile.image()
    if raw[0x8000:0x8000+len(data)] != data: raise RuntimeError('Not the exact hard-OFF A image')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-reset-and-timeout', action='store_true')
    args = parser.parse_args()
    if not args.allow_reset_and_timeout: parser.error('One reset and timeout diagnostic permission required')
    run = str(time.time_ns()); target = profile.OUTPUT/f'timeout-{run}.json'
    row = dict(pass_=False, image_sha256=profile.SHA, motor_qualified=False,
        bridge_enabled=False, motor_commands=False, control_chain_started=False,
        host_flash_write=False, force_confirm=False, automatic_retry=False,
        resets_attempted=0, physical_power_state_not_inferred=True, steps=[])
    port = uart = None; before = None
    def cli(*tokens):
        if tokens == ('-rst',):
            if row['resets_attempted']: raise ValueError('Only one reset')
            row['resets_attempted'] = 1
        elif not tokens or tokens[0] not in ('-u','-r32'):
            raise ValueError('Read-only probe or one reset only')
        p = subprocess.run([profile.CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+profile.SN,
            *map(str,tokens)], capture_output=True,text=True,errors='replace',timeout=30)
        out = p.stdout+p.stderr
        row['steps'].append(dict(args=list(map(str,tokens)),code=p.returncode,output=out))
        if p.returncode or 'Error:' in out: raise RuntimeError('Probe failed; no retry')
        return out
    def capture(name):
        path = profile.OUTPUT/'private'/f'{run}-{name}.bin'
        cli('-u','0x08000000','0x80000',path); raw = path.read_bytes()
        row[name+'_backup'] = str(path)
        if len(raw) != 0x80000: raise RuntimeError('Incomplete Flash backup')
        return raw
    def outputs():
        return profile.require_registers(cli(*(v for a in profile.ADDRESSES for v in ('-r32',hex(a),'4'))),'A')
    try:
        before = capture('before'); verified_baseline(before)
        row['before_outputs'] = outputs()
        port = serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=Console(port)
        row['before_fw'] = require_a466(uart.query('FW STATUS'))
        profile.require_stopped(uart.query('BENCH STATUS'))
        if not profile.locked(profile.fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('Before latch missing')
        cli('-rst')
        until = time.monotonic()+45
        while time.monotonic()<until:
            try: fw = uart.query('FW STATUS',.5)
            except TimeoutError: continue
            row['after_reset_fw'] = require_a466(fw)
            row['startup_protection'] = p = profile.fields(uart.query('BENCH PROTECTION'))
            if p.get('STATE') == '2':
                row['startup_fault'] = fault_fields(uart.query('BENCH PROTECTION FAULT'))
                raise RuntimeError('Startup protection fault; no retry')
            if p.get('ARMED') == '1' and p.get('ZERO') == '1': break
            uart.poll(.1)
        else: raise TimeoutError('No healthy startup; do not clear/retry')
        row['zero'] = profile.require_zero(uart.query('BENCH ZERO'))
        row['before_protection'] = before_p = protection(uart.query('BENCH PROTECTION'),repair_budget=(6,4))
        row['before_timing'] = timing(uart.query('BENCH PROTECTION TIMING'))
        start = time.monotonic()
        while time.monotonic()-start < 1.0: uart.poll(.04)
        row['after_protection'] = after_p = protection(uart.query('BENCH PROTECTION'),repair_budget=(6,4))
        elapsed = time.monotonic()-start
        rate = (int(after_p['FEEDBACK_N'])-int(before_p['FEEDBACK_N']))/elapsed
        if not 18000 <= rate <= 22000 or int(after_p['IRQ']) <= int(before_p['IRQ']):
            raise RuntimeError('No healthy feedback/independent guard progress')
        row['diagnostic_feedback_rate_hz'] = rate
        row['before_injection_timing'] = timing(uart.query('BENCH PROTECTION TIMING'))
        row['timeout_injection'] = uart.query('BENCH PROTECTION TEST TIMEOUT')
        uart.poll(.03)
        row['timeout_result'] = timeout_result(uart.query('BENCH PROTECTION'),
            uart.query('BENCH PROTECTION FAULT'),uart.query('BENCH PROTECTION TIMING'))
        profile.require_stopped(uart.query('BENCH STATUS'))
        row['pass_'] = True
    except BaseException as error:
        row['failure'] = str(error); raise
    finally:
        if uart and row['resets_attempted']:
            try:
                row['final_fw'] = require_a466(uart.query('FW STATUS'))
                row['final_fault'] = fault_fields(uart.query('BENCH PROTECTION FAULT'))
                profile.require_stopped(uart.query('BENCH STOP'))
                if not profile.locked(profile.fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('Final latch absent')
                row['final_outputs'] = outputs()
                if capture('final') != before: raise RuntimeError('Flash changed during reset-only test')
                row['all_flash_unchanged'] = row['final_safe_locked'] = True
            except BaseException as error:
                row['pass_'] = False; row['cleanup_failure'] = str(error)
        if uart: row['uart'] = uart.lines
        if port: port.close()
        target.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(('TIMEOUT PASS' if row['pass_'] else 'TIMEOUT FAIL')+': hard-OFF diagnostic, no motor qualification.',flush=True)
        print('Evidence: '+str(target),flush=True)

if __name__ == '__main__': main()
