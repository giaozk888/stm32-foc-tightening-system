"""One staged Trend4 B trial, powered sense inputs and disconnected motor.

No START, fault clearing, forced confirmation, new flashing or retry.
Existing bootloader/APP own health confirmation. Stop arithmetic on completion
or failure; never call a motor or power-enable command.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path
import trend4_control_acceptance as pinned
from median_control_acceptance import Console, require_zero
from zero_retest_deploy import CLI, SN, compare_flash, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers
from powered_boot_probe import require_staged
from stable_zero_acceptance import fields, require_idle, require_running
from tighten_synthetic_acceptance import locked, confirmed, require_stopped

def require_filter(line):
    f=fields(line)
    for key,value in (('MEDIAN','0'),('SPIKE3','0'),('TREND4','1'),('DELAY_PAIRS','1'),
                      ('FILTER_REV','3'),('COMPUTE_ONLY','1'),('MOTOR_QUALIFIED','0'),('FILTER_STATE','3')):
        if f.get(key)!=value: raise RuntimeError('Wrong/failed four-point filter: '+line)
    for key in ('RAW_STATE','RAW_REASON','RAW_LAST','RAW_RANGE','OUT','CHANGED','PAIRS','RAW_WINDOW'):
        if key not in f: raise RuntimeError('Missing raw evidence: '+key)
    if not 0<=int(f['CHANGED'])<=int(f['PAIRS']) or not 0<=int(f['OUT'])<=int(f['RAW_WINDOW']):
        raise RuntimeError('Invalid raw/filter counters')
    return f

def evidence(path):
    path=path.resolve(); private=(pinned.OUTPUT/'private').resolve()
    if path.parent!=pinned.OUTPUT.resolve(): raise RuntimeError('Stage evidence outside pinned directory')
    record=json.loads(path.read_text('utf-8'))
    if not record.get('pass_') or record.get('mode')!='stage' or record.get('image_sha256')!=pinned.SHA:
        raise RuntimeError('Exact successful stage evidence required')
    before=Path(record['before_backup']).resolve()
    if before.parent!=private: raise RuntimeError('Private baseline outside pinned directory')
    original=before.read_bytes(); pinned.baseline(original)
    return original

def precommit_queries(uart,image):
    # The active upgrade transaction deliberately rejects ANALOG SAFE STATUS.
    # ZERO STATUS is handled by the locked diagnostic before that whitelist.
    # Caller MUST independently verify fresh A-slot registers via SWD first.
    zero=require_service(uart.query('ZERO STATUS'))
    require_staged(uart.query('FW STATUS'),'SOURCE=SWD SD=0 MOE=0 CEN=0',image)
    return zero

def capture_trial_fault(uart,record,shadow=False):
    """Capture the immutable trip BEFORE health confirmation/automatic reset.

    Legacy pinned images support SNAPSHOT/FILTER; shadow is explicitly opt-in
    for a separately verified newer image. Read only; never clear/restart.
    """
    fault=fields(uart.query('FAULT SNAPSHOT'))
    if fault.get('VALID')!='1': return False
    capture=dict(snapshot=fault)
    # Save partial evidence even if a later reply is interrupted by rollback.
    record.setdefault('trial_fault_captures',[]).append(capture)
    capture['filter']=fields(uart.query('FAULT FILTER'))
    if shadow:
        capture['shadow']=fields(uart.query('FAULT SHADOW'))
        capture['trend']=fields(uart.query('FAULT TREND'))
        capture['observer']=fields(uart.query('OC SHADOW STATUS'))
        capture['filter_counts']=fields(uart.query('OC FILTER STATUS'))
    return True

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage-evidence',type=Path,required=True)
    parser.add_argument('--powered-open-load-ready',action='store_true')
    args=parser.parse_args()
    if not args.powered_open_load_ready: parser.error('Powered inputs and disconnected U/V/W required')
    image=pinned.image(); original=evidence(args.stage_evidence)
    run=str(time.time_ns()); target=pinned.OUTPUT/f'commit-{run}.json'
    private=pinned.OUTPUT/'private'
    record=dict(pass_=False,image_sha256=pinned.SHA,mode='commit',steps=[],
                motor_qualified=False,motion_commands=False,force_confirm=False,automatic_retry=False)
    port=uart=None
    def cli(*tokens):
        if tokens[0] not in ('-u','-r32'): raise ValueError('Read-only SWD only')
        result=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,
                               *map(str,tokens)],capture_output=True,text=True,errors='replace',timeout=30)
        out=result.stdout+result.stderr
        record['steps'].append(dict(args=list(map(str,tokens)),code=result.returncode,output=out))
        if result.returncode or 'Error:' in out: raise RuntimeError('SWD read failed; no retry')
        return out
    def outputs(slot):
        return require_registers(cli(*(x for a in ADDRESSES for x in ('-r32',hex(a),'4'))),slot)
    def capture(name):
        path=private/f'{run}-{name}.bin'; cli('-u','0x08000000','0x80000',path)
        raw=path.read_bytes()
        if len(raw)!=0x80000: raise RuntimeError('Incomplete private Flash capture')
        record[name+'_backup']=str(path)
        return raw
    try:
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=Console(port,commit=True)
        record['precommit_outputs']=outputs('A')
        record['precommit_zero']=precommit_queries(uart,image)
        record['precommit_flash']=compare_flash(original,capture('precommit'),image,'B',staged=True)
        record['immediate_precommit_outputs']=outputs('A')
        record['commit_attempted']=True
        try: uart.command('FW END',20)
        except TimeoutError: print('Commit ACK uncertain; observe once, no resend',flush=True)
        deadline=time.monotonic()+45; seen=False
        while time.monotonic()<deadline:
            try: fw=fields(uart.query('FW STATUS',.6))
            except TimeoutError: continue
            if fw.get('CURRENT')=='B':
                seen=True
                if not locked(fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('B output lock missing')
                record['last_zero']=zero=fields(uart.query('BENCH ZERO'))
                if capture_trial_fault(uart,record):
                    raise RuntimeError('Current trip captured before health reset; no retry')
                if zero.get('STATE')=='4': raise RuntimeError('Four-point zero failed: '+str(zero))
                if confirmed(fw,'B'): break
            elif confirmed(fw,'A') and seen: raise RuntimeError('Bootloader rolled back; no retry')
            uart.poll(.1)
        else: raise TimeoutError('No normal B health confirmation')
        record['confirmed_fw']=require_confirmed(uart.query('FW STATUS'),'B')
        require_idle(uart.query('STATUS'))
        record['zero']=require_zero(uart.query('BENCH ZERO'))
        record['filter']=require_filter(uart.query('BENCH ZERO FILTER'))
        record['before']=before=require_running(uart.query('BENCH STATUS'))
        until=time.monotonic()+3
        while time.monotonic()<until: uart.poll(.05)
        record['after']=after=require_running(uart.query('BENCH STATUS'))
        ms=int(after['MS'])-int(before['MS'])
        if ms<2800 or after['RUNS']!=before['RUNS']: raise RuntimeError('Short/restarted observation')
        rates={k:(int(after[k])-int(before[k]))*1000/ms for k in ('ADC','FOC')}
        record['rates_hz']=rates
        if any(not 18000<=hz<=22000 for hz in rates.values()): raise RuntimeError('ADC/FOC rate failed')
        record['stacks']=fields(uart.query('BENCH STACK'))
        if any(int(record['stacks'].get(k,'0'))<256 for k in ('MOTOR','ROUTER','PROTO','TRANSFER')):
            raise RuntimeError('Insufficient task stack margin')
        record['fault']=fields(uart.query('FAULT SNAPSHOT'))
        if any(record['fault'].get(k)!=v for k,v in (('VALID','0'),('REASON','0'))):
            raise RuntimeError('New current fault; do not clear')
        require_stopped(uart.query('BENCH STOP')); record['final_outputs']=outputs('B')
        record['final_flash']=compare_flash(original,capture('final'),image,'B')
        record['final_fw']=require_confirmed(uart.query('FW STATUS'),'B')
        record['pass_']=True
        print('TREND4 COMPUTE PASS: normally confirmed B, ADC/FOC near 20kHz, outputs locked; NOT motor qualification.',flush=True)
    except BaseException as error:
        record['failure']=str(error)
        raise
    finally:
        if uart and record.get('commit_attempted'):
            try:
                fw=fields(uart.query('FW STATUS')); slot=fw.get('CURRENT')
                if slot=='B':
                    record['cleanup_zero']=uart.query('BENCH ZERO')
                    record['cleanup_filter']=uart.query('BENCH ZERO FILTER')
                    record['cleanup_fault']=uart.query('FAULT SNAPSHOT')
                    require_stopped(uart.query('BENCH STOP'))
                if not locked(fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('Final lock missing')
                record['cleanup_outputs']=outputs(slot); record['final_safe_locked']=True
            except BaseException as error:
                record['pass_']=False; record['cleanup_failure']=str(error)
                print('Final state unverified; keep power isolated: '+str(error),flush=True)
        if uart: record['uart']=uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)
    if not record['pass_']: raise RuntimeError('Acceptance/cleanup did not pass')

if __name__=='__main__': main()
