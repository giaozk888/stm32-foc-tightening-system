"""One hard-off zero qualifier on confirmed repaired A; no motor start.

No reset, Flash writes, PWM, bridge, fault clearing or automatic retry.
The firmware checks live analog supply before its single ZERO SAMPLE.
"""
import json
import subprocess
import time

from firmware_transfer_iap import fields
from switch_feedback_acceptance import Console, require_switch
from switch_feedback_timerfix_acceptance import OUTPUT, image
from zero_retest_deploy import CLI, SN, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers


class ZeroConsole(Console):
    def command(self, *args, **kwargs):
        raise ValueError('No transfer or reset in zero qualifier')

    def query(self, text, timeout=2):
        if text not in ('FW STATUS', 'ZERO STATUS', 'ZERO FILTER STATUS', 'ZERO SAMPLE',
                        'ANALOG VOLT', 'SWITCH STATUS'):
            raise ValueError('Only output-off zero qualification admitted')
        if text == 'ZERO SAMPLE':
            if text in self.starts:
                raise ValueError('Only one zero request; never resend')
            self.starts.add(text)
        return super().query(text, timeout)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-hard-off-zero-check', action='store_true')
    args = parser.parse_args()
    if not args.allow_hard_off_zero_check:
        parser.error('Explicit one-shot hard-off qualification required')
    image()
    record = dict(pass_=False, capture_completed=False, motion_commands=False,
                  bridge_enabled=False, pwm_enabled=False, resets=0,
                  flash_writes=0, automatic_retry=False)
    target = OUTPUT/f'zero-repaired-a-{time.time_ns()}.json'
    port = uart = None

    def outputs():
        tokens = []
        for address in ADDRESSES:
            tokens.extend(('-r32', hex(address), '4'))
        p = subprocess.run([CLI, '-c', 'port=SWD', 'mode=HOTPLUG', 'freq=1000',
                            'sn='+SN, *map(str, tokens)], capture_output=True,
                           text=True, errors='replace', timeout=30)
        if p.returncode or 'Error:' in p.stdout+p.stderr:
            raise RuntimeError('Read-only output check failed')
        return require_registers(p.stdout+p.stderr, 'A')

    try:
        record['before_outputs'] = outputs()
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=2)
        port.dtr = port.rts = False
        port.port = 'COM5'
        port.open()
        uart = ZeroConsole(port)
        fw = record['before_fw'] = require_confirmed(uart.query('FW STATUS'), 'A')
        if fw.get('GEN') != '423':
            raise RuntimeError('Exact known repaired A generation 423 required')
        zero = record['before_zero'] = require_service(uart.query('ZERO STATUS'))
        filtered = record['before_filter'] = fields(uart.query('ZERO FILTER STATUS'))
        record['before_switch'] = require_switch(uart.query('SWITCH STATUS'))
        if zero.get('STATE') != '0' or zero.get('N') != '0' or filtered.get('PAIRS') != '0':
            raise RuntimeError('Zero qualifier already attempted; no reset or repeat')
        record['analog_before'] = uart.query('ANALOG VOLT')
        record['start'] = uart.query('ZERO SAMPLE')
        # Existing qualifier has a 5 s timeout. Never poll/probe while acquiring.
        time.sleep(5.3)
        record['zero_line'] = uart.query('ZERO STATUS')
        record['filter_line'] = uart.query('ZERO FILTER STATUS')
        record['zero'] = zero = require_service(record['zero_line'])
        record['filter'] = filtered = fields(record['filter_line'])
        record['final_outputs'] = outputs()
        record['final_fw'] = require_confirmed(uart.query('FW STATUS'), 'A')
        record['capture_completed'] = True
        record['pass_'] = (zero.get('STATE') == '3' and zero.get('REASON') == '0'
                           and filtered.get('RAW_STATE') == '3'
                           and filtered.get('RAW_REASON') == '0' and filtered.get('OUT') == '0')
        print(record['zero_line'], flush=True)
        print(record['filter_line'], flush=True)
        print('ZERO '+('PASS' if record['pass_'] else 'NOT QUALIFIED')+
              ': outputs OFF; no PWM/bridge/motor command sent', flush=True)
    except BaseException as error:
        record['failure'] = str(error)
        raise
    finally:
        if uart:
            record['uart'] = uart.lines
        if port:
            port.close()
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print('Evidence: '+str(target), flush=True)


if __name__ == '__main__':
    main()
