"""Pinned inactive-A real-feedback FOC arithmetic fixture from locked B436.

Stage with physical drive OFF; a separate commit requires powered sensors
and disconnected motor U/V/W. Always SD/MOE/CCER hard off. No START, fault
clear, higher threshold or forced confirmation. Save raw/filtered first trip
before the existing bootloader's automatic trial resets.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import time
import zlib
import median_control_acceptance as core
from zero_async_clock_acceptance import locked_baseline
from zero_retest_deploy import latest_meta, compare_flash, require_service, require_confirmed
from zero_span100_acceptance import ADDRESSES, require_registers
from powered_boot_probe import require_staged
from trend4_control_commit import require_filter, capture_trial_fault
from tighten_synthetic_acceptance import locked, confirmed, require_stopped
from stable_zero_acceptance import fields, require_running, require_idle

ROOT=core.ROOT
IMAGE=ROOT/'foc2_app_a/build/Trend4FaultCapture20261013/foc2.bin'
SHA='2e34d398d22f7e4d86d449286623428b736716eedb865ccbbbee918048a6e453'
OLD_A='df82475772349bbe91765c1f18003a2ee6bc889927ec78f68e5bbea01a0098a0'
OLD_B='eaf40163a8f8e957d170abb1f27f4ebe03384fb0b93ef09d33a48f7ede5b467b'
OUTPUT=ROOT/'safety_backups/trend4-fault-capture-20261013'
GEN=436

def image():
    data=IMAGE.read_bytes()
    if core.image_info(data)[0]!='A' or hashlib.sha256(data).hexdigest()!=SHA:
        raise RuntimeError('Exact offline-tested hard-off A required')
    for marker in (b'COMPUTE_ONLY=1 MOTOR_QUALIFIED=0', b'SD=MOE=CCER=0',
                   b'MEDIAN=0 SPIKE3=0 TREND4=1 DELAY_PAIRS=1 FILTER_REV=3',
                   b'FAULT SHADOW VALID=1 MODE=OBSERVE SRC=',
                   b'OC SHADOW MODE=OBSERVE LIMIT_MA=4000'):
        if marker not in data: raise RuntimeError('Hard-off/capture marker missing')
    if b'OPEN_LOAD_ONLY' in data: raise RuntimeError('Bridge switching forbidden')
    pc=(struct.unpack_from('<I',data,4)[0]&~1)-0x08008000
    if data[pc:pc+2]!=b'\x72\xb6': raise RuntimeError('Reset IRQ mask missing')
    return data

def baseline(data):
    row=locked_baseline(data,known={'A':frozenset((OLD_A,)), 'B':frozenset((OLD_B,))})
    if row['current']!='B' or row['generation']!=GEN:
        raise RuntimeError('Require exact confirmed locked B436')
    return row

def validate_rollback(original,actual):
    baseline(original)
    if len(actual)!=0x80000: raise RuntimeError('Full rollback readback required')
    old,new=latest_meta(original),latest_meta(actual)
    if new[2:6]!=(2,0,0,GEN+4) or new[6:8]!=(0,0):
        raise RuntimeError('Expected exhausted-trial B440 rollback with A metadata invalidated')
    if new[8:10]!=old[8:10]: raise RuntimeError('Fallback B metadata changed')
    data=image()
    if actual[0x8000:0x8000+len(data)]!=data: raise RuntimeError('Staged A bytes changed')
    for start,end in ((0,0x8000),(0x40000,0x7e800),(0x7f800,0x80000)):
        if actual[start:end]!=original[start:end]: raise RuntimeError('Protected region changed')
    return dict(current='B',generation=new[5],all_protected_regions_unchanged=True,
                failed_A_metadata_invalidated=True)

def load_evidence(path):
    path=path.resolve()
    if path.parent!=OUTPUT.resolve(): raise RuntimeError('Evidence outside pinned directory')
    old=json.loads(path.read_text('utf-8'))
    if not old.get('pass_') or old.get('mode')!='stage' or old.get('image_sha256')!=SHA:
        raise RuntimeError('Exact successful stage evidence required')
    p=Path(old['before_backup']).resolve()
    if p.parent!=(OUTPUT/'private').resolve(): raise RuntimeError('Invalid private baseline path')
    original=p.read_bytes(); baseline(original)
    return original

def stage_main():
    # Same pinned stage/readback path as prior reviewed inactive-A deployments.
    core.SHA=SHA; core.IMAGE=IMAGE; core.OUTPUT=OUTPUT
    core.BASELINE_GENERATION=GEN; core.image=image; core.baseline=baseline
    core.main()  # argv mode=stage: NEVER FW END or reset

def commit_main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('commit',))
    parser.add_argument('--stage-evidence',type=Path,required=True)
    parser.add_argument('--powered-open-load-ready',action='store_true')
    args=parser.parse_args()
    if not args.powered_open_load_ready: parser.error('Powered sensors and disconnected U/V/W required')
    original=load_evidence(args.stage_evidence); data=image()
    run=str(time.time_ns()); target=OUTPUT/f'commit-{run}.json'
    record=dict(pass_=False,mode='commit',steps=[],image_sha256=SHA,
                motion_commands=False,force_confirm=False,motor_qualified=False,
                current_limit_A=4,host_retry=False,automatic_bootloader_attempts_possible=2)
    port=uart=None
    def cli(*tokens):
        if tokens[0] not in ('-u','-r32'): raise ValueError('Read-only SWD only')
        p=subprocess.run([core.CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+core.SN,
                          *map(str,tokens)],capture_output=True,text=True,errors='replace',timeout=30)
        out=p.stdout+p.stderr
        record['steps'].append(dict(args=list(map(str,tokens)),code=p.returncode,output=out))
        if p.returncode or 'Error:' in out: raise RuntimeError('Read failed; no blind reset')
        return out
    def outputs(slot):
        return require_registers(cli(*(x for a in ADDRESSES for x in ('-r32',hex(a),'4'))),slot)
    def capture(name):
        path=OUTPUT/'private'/f'{run}-{name}.bin'
        cli('-u','0x08000000','0x80000',path)
        content=path.read_bytes()
        if len(content)!=0x80000: raise RuntimeError('Incomplete private Flash capture')
        record[name+'_backup']=str(path); return content
    def capture_fault():
        found=capture_trial_fault(uart,record,shadow=True)
        if found:
            record['fault_observed']=True
            record['fault_bench']=fields(uart.query('BENCH STATUS'))
            print('FIRST TRIP CAPTURED: raw/filtered source and four chronological pairs saved; no clear/retry.',flush=True)
        return found
    try:
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=core.Console(port,commit=True)
        record['precommit_zero']=require_service(uart.query('ZERO STATUS'))
        require_staged(uart.query('FW STATUS'),'SOURCE=SWD SD=0 MOE=0 CEN=0',data)
        record['precommit_outputs']=outputs('B')
        record['precommit_flash']=compare_flash(original,capture('precommit'),data,'A',staged=True)
        record['immediate_outputs']=outputs('B')
        record['commit_attempted']=True
        try: record['commit_reply']=uart.command('FW END',20)
        except TimeoutError: record['commit_ack_uncertain']=True  # NEVER resend
        deadline=time.monotonic()+45; seen=False; captured_generations=set(); rolled_back=False
        while time.monotonic()<deadline:
            try: fw=fields(uart.query('FW STATUS',.6))
            except TimeoutError: continue
            if fw.get('CURRENT')=='A':
                seen=True
                if not locked(fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('A output lock absent')
                record['last_zero']=zero=fields(uart.query('BENCH ZERO'))
                generation=fw.get('GEN')
                if generation not in captured_generations and capture_fault():
                    captured_generations.add(generation)
                    record['stop_after_fault']=uart.query('BENCH STOP')
                    require_stopped(record['stop_after_fault'])
                if zero.get('STATE')=='4': record['zero_failed']=True
                if confirmed(fw,'A'): break
            elif confirmed(fw,'B') and (seen or int(fw.get('GEN','0'))>GEN):
                rolled_back=True; record['rollback_fw']=fw; break
            uart.poll(.1)
        else: raise TimeoutError('No confirmation/normal rollback; no forced confirmation')
        if rolled_back:
            record['final_outputs']=outputs('B')
            record['final_zero']=require_service(uart.query('ZERO STATUS'))
            record['rollback_flash']=validate_rollback(original,capture('final'))
            record['final_safe_locked']=True
            record['diagnostic_capture_complete']=bool(record.get('trial_fault_captures'))
            record['failure']='Real-feedback FOC rejected by health gate; normal rollback to B'
            print('FOC ACCEPTANCE FAIL: normally rolled back to locked B; evidence retained.',flush=True)
            return
        record['confirmed_fw']=require_confirmed(uart.query('FW STATUS'),'A')
        if record.get('fault_observed') or record.get('zero_failed'):
            raise RuntimeError('Cannot pass with an observed fault/zero failure')
        require_idle(uart.query('STATUS'))
        record['zero']=core.require_zero(uart.query('BENCH ZERO'))
        record['filter']=require_filter(uart.query('BENCH ZERO FILTER'))
        record['before']=before=require_running(uart.query('BENCH STATUS'))
        until=time.monotonic()+3
        while time.monotonic()<until:
            if capture_fault(): raise RuntimeError('Current trip during sustained observation')
            uart.poll(.1)
        record['after']=after=require_running(uart.query('BENCH STATUS'))
        elapsed=int(after['MS'])-int(before['MS'])
        if elapsed<2800 or after['RUNS']!=before['RUNS']: raise RuntimeError('Short/restarted observation')
        record['rates_hz']={k:(int(after[k])-int(before[k]))*1000/elapsed for k in ('ADC','FOC')}
        if any(not 18000<=v<=22000 for v in record['rates_hz'].values()): raise RuntimeError('ADC/FOC rate failed')
        record['stacks']=fields(uart.query('BENCH STACK'))
        if any(int(record['stacks'].get(k,'0'))<256 for k in ('MOTOR','ROUTER','PROTO','TRANSFER')):
            raise RuntimeError('Insufficient task stack margin')
        record['fault']=fields(uart.query('FAULT SNAPSHOT'))
        if any(record['fault'].get(k)!=v for k,v in (('VALID','0'),('REASON','0'))): raise RuntimeError('Current fault')
        require_stopped(uart.query('BENCH STOP'))
        record['final_outputs']=outputs('A')
        record['final_flash']=compare_flash(original,capture('final'),data,'A')
        record['final_fw']=require_confirmed(uart.query('FW STATUS'),'A')
        record['pass_']=True
        print('REAL-FEEDBACK FOC COMPUTE PASS: near 20kHz; SD/MOE/CCER off; NOT motor qualification.',flush=True)
    except BaseException as error:
        record['failure']=str(error); raise
    finally:
        if uart and record.get('commit_attempted'):
            try:
                fw=fields(uart.query('FW STATUS')); slot=fw.get('CURRENT')
                if slot=='A':
                    capture_fault()
                    require_stopped(uart.query('BENCH STOP'))
                if not locked(fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('Final lock absent')
                record['cleanup_outputs']=outputs(slot); record['final_safe_locked']=True
                record['cleanup_fw']=fw
            except BaseException as error:
                record['pass_']=False; record['cleanup_failure']=str(error)
                print('Final state unverified; keep power isolated: '+str(error),flush=True)
        if uart: record['uart']=uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)

def main():
    if len(sys.argv)>1 and sys.argv[1]=='stage': stage_main()
    else: commit_main()

if __name__=='__main__': main()
