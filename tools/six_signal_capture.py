"""One powered zero/OFF baseline then one SD-low six-signal capture on A460.

Motor disconnected; SD physically connected to CTRL_SD; power bridge compiled
out. A separate logic analyzer must be armed. No Flash write/reset, bridge,
motion, fault clear, repeated start or automatic retry. PWM lasts 180 ms;
independent TIM7 guard is 190 ms. Data reads happen only after outputs OFF.
"""
import argparse
import json
import re
import subprocess
import time
from pathlib import Path

import six_signal_acceptance as profile
from firmware_transfer_iap import fields
from switch_feedback_acceptance import Console as BaseConsole
from switch_trend_off_capture import Console as TrendConsole, require_trend
from switch_feedback_off_capture import analyze
from switch_trend_b_zero_check import qualification
from switch_feedback_timerfix_acceptance import guard_result
from zero_retest_deploy import require_confirmed, require_service
from switch_trend_pwm_capture import start_proof, common_reference

DEPLOY = profile.OUTPUT/'swd-deploy-1791893034037262400.json'
GEN = '460'


class Console(TrendConsole):
    def query(self,text,timeout=2):
        if text == 'SWITCH TREND STATUS': return super().query(text,timeout)
        if text not in ('FW STATUS','ZERO STATUS','ZERO FILTER STATUS','ZERO SAMPLE',
                        'ANALOG VOLT','SWITCH STATUS','SWITCH START OFF','SWITCH START PWM',
                        'SWITCH ABORT') and not re.fullmatch(r'SWITCH READ \d+',text):
            raise ValueError('Signal-only one-shot commands; no bridge/reset or clear')
        if text == 'ZERO SAMPLE':
            if text in self.starts: raise ValueError('One zero attempt only')
            self.starts.add(text)
        return BaseConsole.query(self,text,timeout)


def deployment():
    row = json.loads(DEPLOY.read_text('utf-8'))
    if (row.get('pass_') is not True or row.get('final_safe_locked') is not True or
            row.get('image_sha256') != profile.SHA or row.get('final_fw',{}).get('GEN') != GEN or
            row.get('final_fw',{}).get('CURRENT') != 'A' or row.get('guard',{}).get('BRIDGE_COMPILED') != '0'):
        raise RuntimeError('Exact A460 deployment/guard receipt required')
    guard_result(' '.join(f'{k}={v}' for k,v in row['guard'].items()))
    return row


def supply(line):
    row = fields(line)
    if (row.get('VALID') != '1' or not 10000 <= int(row.get('VBUS_EST_MV','0')) <= 14000 or
            not 3000 <= int(row.get('VDDA_BOOT_MV','0')) <= 3600):
        raise RuntimeError('Live sensing supply unavailable; no capture start sent')
    return row


def before_pwm(line):
    row = profile.signal_status(line,mode=1,complete=True)
    if int(row.get('DONE','0')) & 18 != 18 or int(row.get('ATTEMPTS','0')) & 4 or row.get('WAVE') != '0':
        raise RuntimeError('Fresh completed guard/OFF prerequisite required')
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--powered-open-load-ready',action='store_true')
    parser.add_argument('--sd-connected',action='store_true')
    parser.add_argument('--logic-analyzer-armed',action='store_true')
    args = parser.parse_args()
    if not (args.powered_open_load_ready and args.sd_connected and args.logic_analyzer_armed):
        parser.error('Powered disconnected motor, connected SD and armed logic analyzer required')
    import serial
    profile.image(); deployed = deployment()
    private = profile.OUTPUT/'private'
    run = str(time.time_ns()); target = profile.OUTPUT/f'capture-{run}.json'
    row = dict(pass_=False,mode='SD_LOW_SIX_SIGNALS',image_sha256=profile.SHA,generation=GEN,
               resets=0,flash_writes=0,bridge_enabled=False,motor_qualified=False,motion_commands=False,
               automatic_retry=False,waveform_physically_verified=False,
               sd_connection_user_confirmed=True,logic_analyzer_armed_user_confirmed=True,steps=[])
    port = uart = None
    start_sent = stopped = False
    before = None
    def cli(*tokens):
        if not tokens or tokens[0] not in ('-u','-r32'): raise ValueError('Read-only SWD')
        proc = subprocess.run([profile.CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+profile.SN,
                               *map(str,tokens)],capture_output=True,text=True,errors='replace',timeout=30)
        out = proc.stdout+proc.stderr
        row['steps'].append(dict(args=list(map(str,tokens)),code=proc.returncode,output=out))
        if proc.returncode or 'Error:' in out: raise RuntimeError('SWD failed; no retry')
        return out
    def capture_flash(name):
        path = private/f'{run}-{name}.bin'; cli('-u','0x08000000','0x80000',path)
        raw = path.read_bytes(); row[name+'_backup'] = str(path)
        if len(raw) != 0x80000: raise RuntimeError('Incomplete private readback')
        return raw
    def outputs():
        return profile.require_registers(cli(*(x for a in profile.ADDRESSES for x in ('-r32',hex(a),'4'))),'A')
    def fw():
        result = require_confirmed(uart.query('FW STATUS'),'A')
        if result.get('GEN') != GEN: raise RuntimeError('Exact A460 required; no implicit reset')
        return result
    def capture_mode(name,mode):
        nonlocal start_sent,stopped
        row[name] = part = dict()
        start_sent = True; stopped = False
        part['start_line'] = uart.query('SWITCH START '+name.upper())
        profile.signal_status(part['start_line'],mode=mode)
        if mode == 2: start_proof(part['start_line'])
        time.sleep(.25)  # No host polling/debug access during the capture.
        part['capture_line'] = uart.query('SWITCH STATUS')
        part['capture'] = measured = profile.signal_status(part['capture_line'],mode=mode)
        if measured.get('ACTIVE') != '0':
            row['abort'] = uart.query('SWITCH ABORT')
            raise RuntimeError('Active past cutoff; aborted, never restarted')
        part['outputs'] = outputs(); stopped = True
        n = int(measured.get('N','0'))
        if not 0 < n <= 3600: raise RuntimeError('No bounded saved samples')
        part['samples'] = samples = []
        for i in range(n):
            pair = fields(uart.query(f'SWITCH READ {i}'))
            if pair.get('I') != str(i): raise RuntimeError('Saved index mismatch')
            samples.append((int(pair['U']),int(pair['V'])))
            if (i+1)%900 == 0: print(f'{name.upper()} saved pairs {i+1}/{n}; outputs already OFF',flush=True)
        part['analysis'] = analyze(samples,measured)
        part['trend_line'] = uart.query('SWITCH TREND STATUS')
        part['trend'] = require_trend(part['trend_line'],samples)
        profile.signal_status(part['capture_line'],mode=mode,complete=True)
        part['complete'] = True
        return measured
    try:
        before = capture_flash('before')
        path = Path(deployed['final_backup']).resolve()
        if path.parent != private.resolve() or before != path.read_bytes():
            raise RuntimeError('Flash differs from exact A460 deployment')
        row['before_outputs'] = outputs()
        port = serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr = port.rts = False; port.port = 'COM5'; port.open(); uart = Console(port)
        row['before_fw'] = fw()
        row['before_zero'] = zero = require_service(uart.query('ZERO STATUS'))
        row['before_filter'] = filt = fields(uart.query('ZERO FILTER STATUS'))
        row['before_switch'] = guard_result(uart.query('SWITCH STATUS'))
        profile.signal_status(' '.join(f'{k}={v}' for k,v in row['before_switch'].items()),mode=4)
        if zero.get('STATE') != '0' or zero.get('N') != '0' or filt.get('PAIRS') != '0':
            raise RuntimeError('Zero already attempted; no repeat/reset')
        row['analog_before'] = supply(uart.query('ANALOG VOLT'))
        row['zero_start'] = uart.query('ZERO SAMPLE')
        time.sleep(5.3)  # Full existing timeout; do not interfere with acquisition.
        row['zero_line'] = uart.query('ZERO STATUS')
        row['filter_line'] = uart.query('ZERO FILTER STATUS')
        row['zero'] = require_service(row['zero_line'])
        row['filter'] = fields(row['filter_line'])
        row['zero_qualification'] = qualification(row['zero'],row['filter'])
        row['zero_outputs'] = outputs()
        # Shape-only SD-low fixture admission is independent of current-zero
        # qualification. Preserve failed raw/median qualifiers; NEVER bridge.
        print('ZERO qualifiers: '+json.dumps(row['zero_qualification'])+'; no motor qualification',flush=True)
        capture_mode('off',1)
        before_pwm(uart.query('SWITCH STATUS'))
        row['analog_before_pwm'] = supply(uart.query('ANALOG VOLT'))
        print('OFF baseline verified; sending ONE SD-low PWM capture now',flush=True)
        row['capture'] = capture_mode('pwm',2)
        if int(row['capture'].get('DONE','0')) & 22 != 22: raise RuntimeError('Missing complete signal capture')
        reference = tuple(map(int,row['capture']['ZERO'].split(',')))
        row['comparison'] = dict(reference=list(reference),
            off=common_reference(row['off']['samples'],reference),
            pwm=common_reference(row['pwm']['samples'],reference),
            single_non_simultaneous_comparison_not_causal_proof=True)
        row['final_fw'] = fw()
        row['final_zero'] = require_service(uart.query('ZERO STATUS'))
        row['final_outputs'] = outputs()
        if capture_flash('final') != before: raise RuntimeError('Flash changed during signal capture')
        row['all_flash_unchanged'] = True
        row['final_safe_locked'] = row['pass_'] = True
        print('SD-LOW CAPTURE PASS: saved ADC replay checked; physical six-wave .sr still required',flush=True)
    except BaseException as error:
        row['failure'] = str(error); raise
    finally:
        if start_sent and not stopped and uart:
            try:
                row['emergency_abort'] = profile.signal_status(uart.query('SWITCH ABORT'))
                row['cleanup_outputs'] = outputs()
                row['final_safe_locked'] = True
            except BaseException as error: row['cleanup_failure'] = str(error)
        if uart: row['uart'] = uart.lines
        if port: port.close()
        target.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)


if __name__ == '__main__': main()
