"""Pinned inactive-A staging and one hard-off FOC arithmetic trial.

Stage requires physical 12 V OFF and never resets/commits. Commit is a
separate operation after powered current-sense inputs are ready. Neither
mode permits START, fault clearing, forced confirmation, BENCH RUN or retries.
"""
import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from firmware_transfer_iap import ROOT, Uart, DEFAULT_CLIENT, image_info, stage
from zero_retest_deploy import CLI, SN, compare_flash, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers
from zero_async_clock_acceptance import locked_baseline
from zero_median_contrast import PINNED as FALLBACK
from stable_zero_acceptance import fields, require_idle, require_running
from tighten_synthetic_acceptance import locked, confirmed, require_stopped
from powered_boot_probe import require_staged

SHA = '60136a4462f024bc2f2d53635f8934298e17bd77caf02f4620c96283aff376a1'
BASELINE_GENERATION = 408
OUTPUT = ROOT/'safety_backups/median-control-compute-20261012'
# Preserve the original staged binary after later startup-fix rebuilds.
# This historical tool cannot deploy from the current confirmed-A state:
# baseline() still requires the exact original confirmed B generation 408.
IMAGE = OUTPUT/'artifacts/failed-compute-a-original.bin'
READ = frozenset(('FW STATUS', 'ZERO STATUS', 'ANALOG SAFE STATUS', 'STATUS',
                 'SELFTEST STATUS', 'FAULT SNAPSHOT', 'FAULT FILTER', 'ENC DIAG',
                 'BENCH STATUS', 'BENCH ZERO', 'BENCH ZERO FILTER', 'BENCH STACK',
                 'FAULT SHADOW', 'FAULT TREND', 'OC SHADOW STATUS','OC FILTER STATUS'))

def image():
    data = IMAGE.read_bytes()
    if image_info(data)[0] != 'A' or hashlib.sha256(data).hexdigest() != SHA:
        raise RuntimeError('Exact offline-verified compute-only A required')
    for marker in (b'COMPUTE_ONLY=1 MOTOR_QUALIFIED=0', b'SD=MOE=CCER=0'):
        if marker not in data: raise RuntimeError('Missing hard-off image markers')
    return data

def baseline(data):
    result = locked_baseline(data, known={s: frozenset((FALLBACK[s],)) for s in 'AB'})
    if result['current'] != 'B' or result['generation'] != BASELINE_GENERATION:
        raise RuntimeError('Only exact confirmed B generation 408 without trial admitted')
    return result

def require_filter(line):
    row = fields(line)
    for k, v in (('MEDIAN','1'), ('COMPUTE_ONLY','1'), ('MOTOR_QUALIFIED','0'), ('FILTER_STATE','3')):
        if row.get(k) != v: raise RuntimeError('Wrong/failed compute-only filter evidence')
    for k in ('RAW_STATE','RAW_REASON','RAW_LAST','RAW_RANGE','OUT','CHANGED','PAIRS'):
        if k not in row: raise RuntimeError('Missing raw evidence: '+k)
    if int(row['OUT']) > int(row['PAIRS']) or int(row['CHANGED']) > int(row['PAIRS']):
        raise RuntimeError('Invalid filter counters')
    return row

def require_zero(line):
    row = fields(line)
    for k, v in (('STATE','3'),('REASON','0'),('N','4000'),('SET','20000')):
        if row.get(k) != v: raise RuntimeError('Median zero did not complete')
    nominal = int(row['NOM'])
    if not 1000 <= nominal <= 2200 or any(abs(int(row[k])-nominal)>100 for k in ('U0','V0')):
        raise RuntimeError('Median offset outside unchanged nominal gate')
    match = re.fullmatch(r'(\d+):(\d+),(\d+):(\d+)', row.get('RNG',''))
    if not match: raise RuntimeError('Missing filtered window ranges')
    a,b,c,d = map(int, match.groups())
    if not 0 <= b-a <= 100 or not 0 <= d-c <= 100 or not 0 <= int(row['RET']) < 8:
        raise RuntimeError('Filtered window failed existing quality gate')
    return row

class Console(Uart):
    def __init__(self, port, commit=False):
        super().__init__(port)
        self.request = 92000
        self.commit = commit
        self.ends = 0
        self.lines = []
    def dispatch(self, line):
        if line: self.lines.append(line)
        super().dispatch(line)
        if any(s in line for s in ('BOOT HEALTH:', 'ISOLATED ZERO', 'ISOLATED CONCURRENCY:')):
            print(line, flush=True)
        if any(s in line for s in ('HardFault', 'CREATE FAILED', 'AS5047P STARTUP CHECK FAILED')):
            raise RuntimeError('Startup fault; no retry: '+line)
    def command(self, text, timeout=5):
        if text == 'FW END':
            if not self.commit or self.ends: raise ValueError('One explicit commit only')
            self.ends += 1
        elif self.commit or not re.fullmatch(
                r'FW (STATUS|BEGIN [0-9]+ [0-9A-F]{8})|ANALOG SAFE STATUS|XFER ENGINE (STATUS|CLOSE|[0-9A-F]{2,192})',text):
            raise ValueError('No motion/reset/fault clearing or repeated stage')
        return super().command(text, timeout)
    def query(self, text, timeout=2):
        if text not in READ and not (self.commit and text == 'BENCH STOP'):
            raise ValueError('Out-of-scope compute-only command')
        self.request += 1
        self.port.write(f'{self.request} {text}\r\n'.encode('ascii'))
        deadline = time.monotonic()+timeout
        while time.monotonic()<deadline:
            line = self.read_line(.05)
            if line is None: continue
            self.dispatch(line)
            if line.startswith(f'{self.request} '):
                if not line.startswith(f'{self.request} OK '): raise RuntimeError(line)
                print(line, flush=True)
                return line
        raise TimeoutError('No reply; no resend: '+text)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('stage','commit'))
    parser.add_argument('--drive-12v-off',action='store_true')
    parser.add_argument('--powered-inputs-ready',action='store_true')
    parser.add_argument('--stage-evidence',type=Path)
    args = parser.parse_args()
    if args.mode=='stage' and not args.drive_12v_off: parser.error('Drive power OFF required')
    if args.mode=='commit' and (not args.powered_inputs_ready or not args.stage_evidence):
        parser.error('Powered sense inputs and exact stage evidence required')
    data = image()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    private = OUTPUT/'private'
    private.mkdir(exist_ok=True)
    subprocess.run(['icacls',str(private),'/inheritance:r','/grant:r',
                    '*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F'],check=True,capture_output=True)
    run = str(time.time_ns())
    record = dict(pass_=False,mode=args.mode,image_sha256=SHA,steps=[],motion_commands=False,
                  force_confirm=False,motor_qualified=False,zero_qualified=False,automatic_retry=False)
    target = OUTPUT/f'{args.mode}-{run}.json'
    port = uart = None
    def cli(*tokens):
        if tokens[0] not in ('-u','-r32'): raise ValueError('Read-only probe only')
        p = subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,
                            *map(str,tokens)],capture_output=True,text=True,errors='replace',timeout=30)
        out = p.stdout+p.stderr
        record['steps'].append(dict(args=list(map(str,tokens)),code=p.returncode,output=out))
        if p.returncode or 'Error:' in out: raise RuntimeError('SWD failed; no automatic retry')
        return out
    def capture(name):
        path = private/f'{run}-{name}.bin'
        cli('-u','0x08000000','0x80000',path)
        result = path.read_bytes()
        if len(result)!=0x80000: raise RuntimeError('Incomplete private backup')
        record[name+'_backup']=str(path)
        return result
    def outputs(slot):
        tokens=[]
        for address in ADDRESSES: tokens.extend(('-r32',hex(address),'4'))
        return require_registers(cli(*tokens),slot)
    try:
        original = capture('before')
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False
        port.port='COM5'; port.open()
        uart=Console(port,commit=args.mode=='commit')
        if args.mode=='stage':
            record['baseline']=base=baseline(original)
            record['before_outputs']=outputs('B')
            fw=require_confirmed(uart.query('FW STATUS'),'B')
            if int(fw['GEN'])!=base['generation']: raise RuntimeError('Metadata mismatch')
            record['before_zero']=require_service(uart.query('ZERO STATUS'))
            stage(uart,IMAGE,DEFAULT_CLIENT,allow_reset=False)
            staged=capture('staged')
            record['protected_flash']=compare_flash(original,staged,data,'A',staged=True)
            if original[:0x8000]!=staged[:0x8000] or original[0x40000:]!=staged[0x40000:]:
                raise RuntimeError('Bytes outside inactive A changed')
            record['after_outputs']=outputs('B')
            record['staged_fw']=fields(uart.query('FW STATUS'))
            require_staged(' '.join(f'{k}={v}' for k,v in record['staged_fw'].items()),
                           'SOURCE=SWD SD=0 MOE=0 CEN=0',data)
            if record['staged_fw'].get('GEN')!=str(BASELINE_GENERATION): raise RuntimeError('Staging changed generation')
            print('MEDIAN CONTROL STAGE PASS: exact inactive A; B/bootloader/KVS/metadata preserved; NO RESET.',flush=True)
        else:
            evidence=args.stage_evidence.resolve()
            if evidence.parent!=OUTPUT.resolve(): raise RuntimeError('Stage evidence outside exact directory')
            old=json.loads(evidence.read_text(encoding='utf-8'))
            if not old.get('pass_') or old.get('mode')!='stage' or old.get('image_sha256')!=SHA:
                raise RuntimeError('Exact successful stage evidence required')
            before_path=Path(old['before_backup']).resolve()
            if before_path.parent!=private.resolve(): raise RuntimeError('Private baseline outside exact directory')
            baseline_before=before_path.read_bytes(); baseline(baseline_before)
            record['precommit_flash']=compare_flash(baseline_before,original,data,'A',staged=True)
            record['precommit_outputs']=outputs('B')
            require_staged(uart.query('FW STATUS'),'SOURCE=SWD SD=0 MOE=0 CEN=0',data)
            record['commit_attempted']=True
            try: uart.command('FW END',20)
            except TimeoutError: print('END ACK uncertain: observing once, no resend',flush=True)
            deadline=time.monotonic()+45
            seen=False
            while time.monotonic()<deadline:
                try: fw=fields(uart.query('FW STATUS',.6))
                except TimeoutError: continue
                if fw.get('CURRENT')=='A':
                    seen=True
                    if not locked(fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('Output lock missing')
                    zero=fields(uart.query('BENCH ZERO'))
                    if zero.get('STATE')=='4': raise RuntimeError('Zero failed; do not clear or retry')
                    if confirmed(fw,'A'): break
                elif confirmed(fw,'B') and seen: raise RuntimeError('Existing bootloader rolled back')
                uart.poll(.1)
            else: raise TimeoutError('No normal health confirmation; no force confirm')
            require_idle(uart.query('STATUS'))
            record['zero']=require_zero(uart.query('BENCH ZERO'))
            record['filter']=require_filter(uart.query('BENCH ZERO FILTER'))
            before=require_running(uart.query('BENCH STATUS'))
            until=time.monotonic()+3
            while time.monotonic()<until: uart.poll(.05)
            after=require_running(uart.query('BENCH STATUS'))
            elapsed=int(after['MS'])-int(before['MS'])
            if elapsed<2800 or after['RUNS']!=before['RUNS']: raise RuntimeError('Short or restarted observation')
            rates={k:(int(after[k])-int(before[k]))*1000/elapsed for k in ('ADC','FOC')}
            if any(not 18000<=hz<=22000 for hz in rates.values()): raise RuntimeError('Rate failure: '+str(rates))
            record.update(before=before,after=after,rates_hz=rates)
            record['stacks']=fields(uart.query('BENCH STACK'))
            if any(int(record['stacks'].get(k,'0'))<256 for k in ('MOTOR','ROUTER','PROTO','TRANSFER')):
                raise RuntimeError('Task stack margin insufficient')
            if any(fields(uart.query('FAULT SNAPSHOT')).get(k)!=v for k,v in (('VALID','0'),('REASON','0'))):
                raise RuntimeError('New current fault snapshot')
            require_stopped(uart.query('BENCH STOP'))
            record['final_outputs']=outputs('A')
            final=capture('final')
            record['final_flash']=compare_flash(baseline_before,final,data,'A')
            record['final_fw']=require_confirmed(uart.query('FW STATUS'),'A')
            print('MEDIAN CONTROL COMPUTE PASS: normal health confirmation, 20kHz ADC/FOC, outputs locked. NOT motor qualification.',flush=True)
        record['pass_']=True
    except BaseException as error:
        record['failure']=str(error)
        raise
    finally:
        if uart and args.mode=='commit' and record.get('commit_attempted'):
            try:
                fw=fields(uart.query('FW STATUS'))
                if fw.get('CURRENT')=='A': require_stopped(uart.query('BENCH STOP'))
                if not locked(fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('Final lock missing')
                record['cleanup_outputs']=outputs(fw['CURRENT'])
                record['final_safe_locked']=True
            except BaseException as error:
                record['pass_']=False; record['cleanup_failure']=str(error)
                print('Final state unverified; keep power isolated: '+str(error),flush=True)
        if uart: record['uart']=uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)
    if not record['pass_']: raise RuntimeError('Acceptance did not pass')

if __name__=='__main__': main()
