"""Pinned output-locked B spike diagnostic. No motor or bridge commands.

Inspect/deploy/sample are separate. Deploy needs physically OFF drive power;
only official UART pw_transfer may write inactive B. Sample is one-shot,
must be separately authorized with powered sensing and disconnected U/V/W.
"""
import argparse
import hashlib
import json
import re
import struct
import subprocess
import time
from firmware_transfer_iap import ROOT, DEFAULT_CLIENT, image_info, stage
from switch_feedback_acceptance import Console
from zero_async_clock_acceptance import locked_baseline
from zero_retest_deploy import CLI, SN, compare_flash, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers, observe_trial

IMAGE = ROOT/'foc2_app_b/build/IsolatedSpike20261012/foc2.bin'
SHA = '97f9b23bfe9acec0c35246f149cc4a57bde9d539e163f0ce49f989c1527f4b11'
OLD_A = 'd196d66986a3c3de6befa1ab44be9feb10493f288cc6795bae678c97d97a89f1'
OLD_B = '10451eb6f8344939cdeed33b573dab2050c908d84da26b0b407ae1e294417c0d'
OUTPUT = ROOT/'safety_backups/isolated-spike-20261012'
TARGET_SLOT, BASELINE_SLOT, BASELINE_GENERATION = 'B', 'A', '423'
CAPTURE_EXTRA = None

def fields(line):
    # Legacy parser permits letters/underscores only and silently drops
    # SPIKE3, U0 and V0. Keep the new diagnostic evidence intact.
    return dict(re.findall(r'\b([A-Z][A-Z0-9_]*)=([^\s]+)',line))

def image():
    data = IMAGE.read_bytes()
    if image_info(data)[0] != TARGET_SLOT or hashlib.sha256(data).hexdigest() != SHA:
        raise RuntimeError('Exact offline-tested locked target required')
    for marker in (b'SPIKE3=1 DELAY_PAIRS=1', b'LOCKED_DIAGNOSTIC', b'MOTOR_READY=0'):
        if marker not in data:
            raise RuntimeError('Missing locked spike marker')
    if b'OPEN_LOAD_ONLY' in data:
        raise RuntimeError('No switching diagnostic allowed')
    pc = (struct.unpack_from('<I',data,4)[0] & ~1) - dict(A=0x08008000,B=0x08040000)[TARGET_SLOT]
    if data[pc:pc+2] != b'\x72\xb6':
        raise RuntimeError('Reset interrupt mask missing')
    return data

def baseline(data):
    row = locked_baseline(data, known={'A':frozenset((OLD_A,)), 'B':frozenset((OLD_B,))})
    if row['current'] != BASELINE_SLOT or row['generation'] != int(BASELINE_GENERATION):
        raise RuntimeError('Require exact confirmed locked baseline generation '+BASELINE_GENERATION)
    return row

def require_spike(line, fresh=False):
    row = require_service(line)
    row.update(fields(line))
    for key,value in (('MEDIAN','0'),('SPIKE3','1'),('DELAY_PAIRS','1'),('ADC_OWNER','1'),
                      ('SPAN','100'),('ADC_READY','1')):
        if row.get(key) != value:
            raise RuntimeError('Unexpected spike service: '+line)
    if fresh and any(row.get(k) != '0' for k in ('STATE','REASON','N','SET','ADC')):
        raise RuntimeError('Fresh unsampled diagnostic required')
    return row

class SpikeConsole(Console):
    def query(self,text,timeout=2):
        if text not in ('FW STATUS','ZERO STATUS','ZERO FILTER STATUS','ANALOG VOLT',
                        'ANALOG SAFE STATUS','ZERO SAMPLE'):
            raise ValueError('Read-only/one hard-off zero command only')
        if text == 'ZERO SAMPLE':
            if text in self.starts:
                raise ValueError('Never resend one-shot capture')
            self.starts.add(text)
        return super().query(text,timeout)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('inspect','deploy','sample'))
    parser.add_argument('--drive-12v-off',action='store_true')
    parser.add_argument('--powered-open-load-ready',action='store_true')
    args = parser.parse_args()
    if args.mode == 'deploy' and not args.drive_12v_off:
        parser.error('Drive 12 V physically OFF required')
    if args.mode == 'sample' and not args.powered_open_load_ready:
        parser.error('Powered sensing, disconnected U/V/W required')
    data = image()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    run = str(time.time_ns())
    target = OUTPUT/f'{args.mode}-{run}.json'
    record = dict(pass_=False, mode=args.mode, image_sha256=SHA,
                  motion_commands=False, pwm_enabled=False, bridge_enabled=False,
                  force_confirm=False, automatic_retry=False, steps=[])
    private = OUTPUT/'private'
    port = uart = None

    def cli(*tokens):
        if tokens[0] not in ('-u','-r32'):
            raise ValueError('Read-only SWD only')
        p = subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,
                            *map(str,tokens)],capture_output=True,text=True,
                           errors='replace',timeout=30)
        record['steps'].append(dict(args=list(map(str,tokens)),code=p.returncode,output=p.stdout+p.stderr))
        if p.returncode or 'Error:' in p.stdout+p.stderr:
            raise RuntimeError('SWD read failed; no retry')
        return p.stdout+p.stderr

    def outputs(slot):
        return require_registers(cli(*(x for a in ADDRESSES for x in ('-r32',hex(a),'4'))),slot)

    def capture(name):
        path = private/f'{run}-{name}.bin'
        cli('-u','0x08000000','0x80000',path)
        raw = path.read_bytes()
        if len(raw) != 0x80000:
            raise RuntimeError('Incomplete Flash backup')
        record[name+'_backup'] = str(path)
        return raw

    try:
        import serial
        port = serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr = port.rts = False
        port.port = 'COM5'; port.open()
        uart = SpikeConsole(port)
        fw = record['before_fw'] = fields(uart.query('FW STATUS'))
        slot = fw.get('CURRENT')
        if slot not in ('A','B'):
            raise RuntimeError('Unknown current slot')
        require_confirmed(' '.join(f'{k}={v}' for k,v in fw.items()),slot)
        record['before_zero'] = require_service(uart.query('ZERO STATUS'))
        record['before_outputs'] = outputs(slot)
        if args.mode == 'inspect':
            print(json.dumps(dict(fw=fw,zero=record['before_zero'],outputs=record['before_outputs'])),flush=True)
            record['pass_'] = True
            return
        if args.mode == 'deploy':
            if slot != BASELINE_SLOT or fw.get('GEN') != BASELINE_GENERATION:
                raise RuntimeError('Only known inactive target admitted')
            private.mkdir(exist_ok=True)
            subprocess.run(['icacls',str(private),'/inheritance:r','/grant:r',
                            '*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F'],
                           capture_output=True,check=True)
            before = capture('before')
            record['baseline'] = baseline(before)
            stage(uart,IMAGE,DEFAULT_CLIENT,allow_reset=False)
            record['staged_flash'] = compare_flash(before,capture('staged'),data,TARGET_SLOT,staged=True)
            record['staged_outputs'] = outputs(BASELINE_SLOT)
            try:
                uart.command('FW END',20)
            except TimeoutError:
                print('Commit ACK uncertain: observe once; never resend',flush=True)
            record['confirmed'] = observe_trial(uart,TARGET_SLOT)
            record['fresh_spike'] = require_spike(uart.query('ZERO STATUS'),fresh=True)
            record['final_outputs'] = outputs(TARGET_SLOT)
            record['final_flash'] = compare_flash(before,capture('final'),data,TARGET_SLOT)
            record['pass_'] = True
            print('DEPLOY PASS: '+TARGET_SLOT+' confirmed; fallback/bootloader/KVS/parameters preserved; no sampling or motor',flush=True)
            return
        if slot != TARGET_SLOT:
            raise RuntimeError('Pinned target service required')
        record['before_spike'] = require_spike(uart.query('ZERO STATUS'),fresh=True)
        filt = fields(uart.query('ZERO FILTER STATUS'))
        if filt.get('PAIRS') != '0' or filt.get('SPIKE3') != '1':
            raise RuntimeError('Capture already used or wrong filter; no reset/retry')
        # No full private Flash reads while powered: read only active APP bytes.
        proof = OUTPUT/f'{run}-active-app.bin'
        cli('-u',hex(dict(A=0x08008000,B=0x08040000)[TARGET_SLOT]),len(data),proof)
        if proof.read_bytes() != data:
            raise RuntimeError('Actual APP differs from pinned image')
        record['analog_before'] = uart.query('ANALOG VOLT')
        record['start'] = uart.query('ZERO SAMPLE')
        time.sleep(5.3)  # firmware timeout; no polling/probing during capture
        record['zero_line'] = uart.query('ZERO STATUS')
        record['filter_line'] = uart.query('ZERO FILTER STATUS')
        record['zero'] = z = require_spike(record['zero_line'])
        record['filter'] = f = fields(record['filter_line'])
        if CAPTURE_EXTRA:
            CAPTURE_EXTRA(uart,record,target)
        record['final_outputs'] = outputs(TARGET_SLOT)
        record['final_fw'] = require_confirmed(uart.query('FW STATUS'),TARGET_SLOT)
        record['capture_completed'] = True
        record['filtered_zero_ready'] = z.get('STATE') == '3' and z.get('REASON') == '0'
        record['raw_zero_ready'] = f.get('RAW_STATE') == '3' and f.get('RAW_REASON') == '0'
        record['motor_qualified'] = False
        record['pass_'] = True  # capture/evidence only, not feedback qualification
        print(record['zero_line'],flush=True); print(record['filter_line'],flush=True)
        print('CAPTURE COMPLETE: filtered/raw judged separately; MOTOR NOT QUALIFIED',flush=True)
    except BaseException as error:
        record['failure'] = str(error)
        raise
    finally:
        if uart: record['uart'] = uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)

if __name__ == '__main__':
    main()
