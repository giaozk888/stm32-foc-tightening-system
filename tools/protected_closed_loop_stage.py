"""Stage exact protected motor trial in inactive B only; NEVER activate/reset/start.

Requires physically off drive supply. Preserve exact confirmed A466 and all
bytes outside B. Full-flash captures may contain settings: private ACL only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from firmware_transfer_iap import ROOT, Uart, image_info, stage, DEFAULT_CLIENT, fields
from control_chain_timeout_acceptance import verified_baseline as original_baseline
from control_chain_reconnect_acceptance import require_stopped, require_confirmed
from zero_retest_deploy import CLI, SN, compare_flash
from zero_span100_acceptance import ADDRESSES, require_registers

IMAGE = ROOT/'foc2_app_b/build/ProtectedClosedLoop/foc2.bin'
SHA = 'c5bb72af17b8a9b486aab0af53aeeba1cce4435476176fbbacffa547adfb191a'
OUTPUT = ROOT/'safety_backups/protected-closed-loop-20261014'

def verified_baseline(raw, recovery=None):
    if recovery is None:
        original_baseline(raw)
        return 466
    from protected_closed_loop_recover import verified_recovery
    return verified_recovery(raw,recovery)

def pinned_image():
    raw = IMAGE.read_bytes()
    if len(raw) != 205152 or hashlib.sha256(raw).hexdigest() != SHA or image_info(raw)[0] != 'B':
        raise RuntimeError('Exact offline-tested B required')
    for marker in (b'OK MOTOR TEST QUEUED=1 RPM=20 MAX_US=400000',
                   b'QUALIFIED=0', b'LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000',
                   b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000'):
        if marker not in raw: raise RuntimeError('Missing protected trial marker')
    return raw

class Console(Uart):
    def __init__(self, port):
        super().__init__(port); self.lines=[]
    def dispatch(self, line):
        # Do not persist thousands of chunk payloads, only counters/status.
        if line and not line.startswith('0 EVT FWTRANSFER RPC '): self.lines.append(line)
        super().dispatch(line)
    def command(self, text, timeout=5):
        if text == 'FW END': raise ValueError('Stage ONLY; activation forbidden')
        if text == 'BENCH STATUS':
            self.request+=1
            request=self.request
            self.port.write(f'{request} {text}\r\n'.encode('ascii'))
            end=time.monotonic()+timeout
            while time.monotonic()<end:
                line=self.read_line(.05)
                if line is None: continue
                self.dispatch(line)
                if line.startswith(f'{request} '):
                    if not line.startswith(f'{request} OK '): raise RuntimeError(line)
                    return line
            raise TimeoutError('Read-only status timeout')
        return super().command(text,timeout)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--allow-inactive-stage',action='store_true')
    p.add_argument('--drive-12v-off',action='store_true')
    p.add_argument('--recovered-baseline',type=Path,
                   help='Exact successful bounded rollback receipt; no baseline bypass')
    args=p.parse_args()
    if not (args.allow_inactive_stage and args.drive_12v_off):
        p.error('Inactive staging authorization and off supply required')
    data=pinned_image()
    OUTPUT.mkdir(exist_ok=True)
    private=OUTPUT/'private'; private.mkdir(exist_ok=True)
    subprocess.run(['icacls',str(private),'/inheritance:r','/grant:r',
                    'Administrator:(OI)(CI)F','SYSTEM:(OI)(CI)F'],check=True,capture_output=True)
    run=str(time.time_ns()); receipt=OUTPUT/f'stage-{run}.json'
    row=dict(pass_=False,mode='stage',image_sha256=SHA,image_bytes=len(data),
        motor_qualified=False,resets=0,motion_commands=False,activation=False,
        drive_12v_off_user_confirmed=True,steps=[])
    if args.recovered_baseline: row['recovered_baseline']=str(args.recovered_baseline.resolve())
    port=uart=None
    def cli(*tokens):
        if not tokens or tokens[0] not in ('-u','-r32'):
            raise ValueError('Read-only SWD only')
        result=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,
            *map(str,tokens)],capture_output=True,text=True,errors='replace',timeout=30)
        output=result.stdout+result.stderr
        row['steps'].append(dict(args=list(map(str,tokens)),code=result.returncode,output=output))
        if result.returncode or 'Error:' in output: raise RuntimeError('Probe failure; no retry/reset')
        return output
    def capture(name):
        path=private/f'{run}-{name}.bin'
        cli('-u','0x08000000','0x80000',path)
        raw=path.read_bytes()
        if len(raw)!=0x80000: raise RuntimeError('Full capture required')
        row[name+'_backup']=str(path)
        return raw
    def outputs():
        return require_registers(cli(*(v for a in ADDRESSES for v in ('-r32',hex(a),'4'))),'A')
    try:
        before=capture('before'); generation=verified_baseline(before,args.recovered_baseline)
        row['before_outputs']=outputs()
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=Console(port)
        row['before_fw']=require_confirmed(uart.command('FW STATUS'),'A')
        if row['before_fw'].get('GEN') != str(generation):
            raise RuntimeError('Exact recovered/original generation required')
        row['before_bench']=require_stopped(uart.command('BENCH STATUS'))
        stage(uart,IMAGE,DEFAULT_CLIENT,allow_reset=False)
        row['after_fw']=fw=fields(uart.command('FW STATUS'))
        if any(fw.get(k)!=v for k,v in (('CURRENT','A'),('CONFIRMED','A'),('GEN',str(generation)),
                                       ('PENDING','-'),('TARGET','B'),('ACTIVE','1'))):
            raise RuntimeError('Staging state changed unexpectedly')
        actual=capture('staged'); compare_flash(before,actual,data,'B',staged=True)
        if actual[:0x40000]!=before[:0x40000] or actual[0x78000:]!=before[0x78000:]:
            raise RuntimeError('Bytes outside B changed')
        row['all_bytes_outside_b_unchanged']=True
        row['after_outputs']=outputs()
        row['pass_']=True
    except BaseException as error:
        row['failure']=str(error)
        raise
    finally:
        if uart: row['uart']=uart.lines
        if port: port.close()
        receipt.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(('STAGE PASS' if row['pass_'] else 'STAGE FAIL')+': no reset/activation/motion',flush=True)
        print('Evidence: '+str(receipt),flush=True)

if __name__=='__main__': main()
