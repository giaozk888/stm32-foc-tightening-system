"""A443 -> inactive B, disconnected-motor diagnostic deployment only.

Drive 12 V OFF. Official Transfer stages B; normal trial health confirms B.
Only the independent all-outputs-off TIM7 selftest is started. No ADC capture,
PWM, bridge, motion, fault clear, forced confirmation or automatic retry.
"""
import argparse
import hashlib
import json
import subprocess
import time
from firmware_transfer_iap import ROOT, DEFAULT_CLIENT, image_info, stage, fields
from switch_feedback_acceptance import Console as BaseConsole, require_switch
from switch_feedback_timerfix_acceptance import guard_result
from zero_async_clock_acceptance import locked_baseline
from zero_retest_deploy import CLI, SN, compare_flash, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers, observe_trial

IMAGE = ROOT/'foc2_app_b/build/SwitchTrendCompare20261013/foc2.bin'
SHA = 'f725799506142c1cb55d47ce39069e14fc1fa3519508f0374528c628cf20fc0f'
OLD_A = '350408d649507d3b9a360b778bedd14be88c433fde27a811f35938888e5cf241'
OLD_B = 'eaf40163a8f8e957d170abb1f27f4ebe03384fb0b93ef09d33a48f7ede5b467b'
OUTPUT = ROOT/'safety_backups/switch-trend-compare-20261013'

def image():
    import struct
    data = IMAGE.read_bytes()
    if image_info(data)[0] != 'B' or hashlib.sha256(data).hexdigest() != SHA:
        raise RuntimeError('Exact tested B diagnostic required')
    reset = (struct.unpack_from('<I',data,4)[0]&~1)-0x08040000
    irq = struct.unpack_from('<I',data,(16+55)*4)[0]
    if data[reset:reset+2] != b'\x72\xb6' or not irq&1 or not 0x08040000<=irq&~1<0x08040000+len(data):
        raise RuntimeError('Reset mask or independent cutoff vector missing')
    for marker in (b'POLICY=OBSERVER_ONLY',b'MOTOR_READY=0',b'OPEN_LOAD_ONLY',b'IRQ_SR='):
        if marker not in data: raise RuntimeError('Missing diagnostic identity')
    return data

def baseline(data):
    row = locked_baseline(data,known={'A':frozenset((OLD_A,)), 'B':frozenset((OLD_B,))})
    if row['current'] != 'A' or row['generation'] != 443:
        raise RuntimeError('Exact stopped confirmed A443 required; no automatic adaptation')
    return row

class Console(BaseConsole):
    def query(self,text,timeout=2):
        if text not in ('FW STATUS','ANALOG SAFE STATUS','ZERO STATUS','SWITCH STATUS','SWITCH START GUARD'):
            raise ValueError('Deployment and guard-only console')
        return super().query(text,timeout)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-inactive-b',action='store_true')
    parser.add_argument('--drive-12v-off',action='store_true')
    args = parser.parse_args()
    if not args.allow_inactive_b or not args.drive_12v_off:
        parser.error('Explicit inactive-B deployment and drive 12 V OFF required')
    data = image()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    private = OUTPUT/'private'; private.mkdir(exist_ok=True)
    subprocess.run(['icacls',str(private),'/inheritance:r','/grant:r',
                    '*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F'],check=True,capture_output=True)
    run = str(time.time_ns()); target = OUTPUT/f'deploy-{run}.json'
    record = dict(pass_=False,image_sha256=SHA,target_slot='B',pwm_enabled=False,
                  bridge_enabled=False,motion_commands=False,automatic_retry=False,
                  force_confirm=False,adc_capture=False,steps=[])
    port = uart = None
    def cli(*tokens):
        if tokens[0] not in ('-u','-r32'): raise ValueError('Read-only SWD')
        p = subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,*map(str,tokens)],
                           capture_output=True,text=True,errors='replace',timeout=30)
        record['steps'].append(dict(args=list(map(str,tokens)),code=p.returncode,output=p.stdout+p.stderr))
        if p.returncode or 'Error:' in p.stdout+p.stderr: raise RuntimeError('SWD failed; no retry')
        return p.stdout+p.stderr
    def capture(name):
        path = private/f'{run}-{name}.bin'; cli('-u','0x08000000','0x80000',path)
        record[name+'_backup'] = str(path)
        raw = path.read_bytes()
        if len(raw) != 0x80000: raise RuntimeError('Incomplete private backup')
        return raw
    def outputs(slot):
        tokens = []
        for address in ADDRESSES: tokens.extend(('-r32',hex(address),'4'))
        return require_registers(cli(*tokens),slot)
    try:
        before = capture('before')
        record['baseline'] = baseline(before)
        record['before_outputs'] = outputs('A')
        import serial
        port = serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr = port.rts = False; port.port = 'COM5'; port.open(); uart = Console(port)
        record['before_fw'] = require_confirmed(uart.query('FW STATUS'),'A')
        if int(record['before_fw']['GEN']) != 443: raise RuntimeError('UART/Flash mismatch')
        safety = fields(uart.query('ANALOG SAFE STATUS'))
        if any(safety.get(k)!=v for k,v in (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
            raise RuntimeError('Current A must be stopped and output locked')
        print('BASELINE PASS: exact A443, outputs OFF, private backup retained',flush=True)
        stage(uart,IMAGE,DEFAULT_CLIENT,allow_reset=False)
        record['staged_flash'] = compare_flash(before,capture('staged'),data,'B',staged=True)
        record['staged_outputs'] = outputs('A')
        try: uart.command('FW END',20)
        except TimeoutError: print('Commit ACK uncertain; observe once, never resend',flush=True)
        record['confirmed'] = observe_trial(uart,'B')
        record['before_guard_zero'] = require_service(uart.query('ZERO STATUS'))
        record['fresh_switch'] = require_switch(uart.query('SWITCH STATUS'))
        record['start_guard'] = require_switch(uart.query('SWITCH START GUARD'),mode=4)
        time.sleep(.25)  # No polling/SWD while guard active.
        record['guard_line'] = uart.query('SWITCH STATUS')
        # Preserve readback and output state even if the guard validation fails.
        record['final_outputs'] = outputs('B')
        record['final_fw'] = require_confirmed(uart.query('FW STATUS'),'B')
        record['final_flash'] = compare_flash(before,capture('final'),data,'B')
        if record['final_flash']['generation'] != 446: raise RuntimeError('Unexpected confirmation generation')
        record['guard'] = guard_result(record['guard_line'])
        record['pass_'] = True
        print('DEPLOY AND GUARD PASS: confirmed B446; SD/PWM OFF; no switching or motor test',flush=True)
    except BaseException as error:
        record['failure'] = str(error); raise
    finally:
        if uart: record['uart'] = uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)

if __name__ == '__main__': main()
