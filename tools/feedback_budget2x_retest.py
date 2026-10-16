"""One authorized reset of exact confirmed B457; hard-OFF retest only.

No Flash write, commit, force confirmation, bridge/motor start, fault clear
or automatic retry. A successful retest cannot erase the prior trial fault.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
import serial
import feedback_budget2x_acceptance as profile
from feedback_safety_commit import Console as GuardConsole, protection, timing, timeout_result, fault_fields
from median_control_acceptance import require_zero
from firmware_transfer_iap import fields
from zero_retest_deploy import CLI, SN, require_confirmed
from zero_span100_acceptance import ADDRESSES, require_registers
from tighten_synthetic_acceptance import locked, require_stopped

REFERENCE=profile.OUTPUT/'closeout-1791890974805019500.json'
STARTUP_SECONDS=45
OBSERVE_SECONDS=5

class Console(GuardConsole):
    def command(self,*args,**kwargs):
        raise ValueError('No firmware commit or write during retest')

def verified_baseline(raw):
    evidence=json.loads(REFERENCE.read_text('utf-8'))
    if (evidence.get('pass_') is not True or evidence.get('read_only_closeout') is not True or
            evidence.get('prior_trial_pass') is not False or evidence.get('image_sha256')!=profile.SHA or
            evidence.get('fw',{}).get('GEN')!='457'):
        raise RuntimeError('Exact prior locked B457 closeout required')
    backup=Path(evidence['closeout_backup']).resolve()
    if backup.parent!=(profile.OUTPUT/'private').resolve() or raw!=backup.read_bytes():
        raise RuntimeError('Flash differs from exact private B457 baseline')
    data=profile.image()
    if raw[0x40000:0x40000+len(data)]!=data:
        raise RuntimeError('Exact hard-off B required')

def require_b457(line):
    row=require_confirmed(line,'B')
    if row.get('GEN')!='457': raise RuntimeError('Not confirmed B457; no reset/retry')
    return row

def feedback_rate(before,after,elapsed):
    if elapsed<=0 or int(after['IRQ'])<=int(before['IRQ']):
        raise RuntimeError('No independent guard progress')
    rate=(int(after['FEEDBACK_N'])-int(before['FEEDBACK_N']))/elapsed
    if not 18000<=rate<=22000: raise RuntimeError('Feedback compute rate failed')
    return rate

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-reset',action='store_true')
    parser.add_argument('--powered-open-load-ready',action='store_true')
    args=parser.parse_args()
    if not (args.allow_reset and args.powered_open_load_ready):
        parser.error('One reset permission and powered sensing/disconnected motor required')
    run=str(time.time_ns()); target=profile.OUTPUT/f'retest-{run}.json'
    row=dict(pass_=False,prior_trial_pass=False,image_sha256=profile.SHA,
             motor_qualified=False,bridge_enabled=False,motion_commands=False,
             flash_write=False,force_confirm=False,host_retry=False,resets_attempted=0,steps=[])
    port=uart=None
    def cli(*tokens):
        if tokens==('-rst',):
            if row['resets_attempted']: raise ValueError('One reset only; no retry')
            row['resets_attempted']=1
        elif not tokens or tokens[0] not in ('-u','-r32'):
            raise ValueError('Only readback or one authorized reset')
        proc=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,*map(str,tokens)],
                            capture_output=True,text=True,errors='replace',timeout=30)
        out=proc.stdout+proc.stderr
        row['steps'].append(dict(args=list(map(str,tokens)),code=proc.returncode,output=out))
        if proc.returncode or 'Error:' in out: raise RuntimeError('Probe failed; no retry/reset')
        return out
    def capture(name):
        path=profile.OUTPUT/'private'/f'{run}-{name}.bin'
        cli('-u','0x08000000','0x80000',path)
        data=path.read_bytes()
        if len(data)!=0x80000: raise RuntimeError('Incomplete Flash capture')
        row[name+'_backup']=str(path); return data
    def outputs():
        return require_registers(cli(*(x for a in ADDRESSES for x in ('-r32',hex(a),'4'))),'B')
    def fault_capture():
        row['fault']=fault_fields(uart.query('BENCH PROTECTION FAULT'))
        row['fault_zero']=fields(uart.query('BENCH ZERO'))
        row['fault_timing']=fields(uart.query('BENCH PROTECTION TIMING'))
    try:
        before=capture('before'); verified_baseline(before)
        row['before_outputs']=outputs()
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=Console(port)
        row['before_fw']=require_b457(uart.query('FW STATUS'))
        require_stopped(uart.query('BENCH STATUS'))
        if not locked(fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('Before lock absent')
        cli('-rst')
        end=time.monotonic()+STARTUP_SECONDS
        while time.monotonic()<end:
            try: fw=uart.query('FW STATUS',.5)
            except TimeoutError: continue
            row['after_reset_fw']=require_b457(fw)
            if not locked(fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('Runtime lock absent')
            row['startup_protection']=p=fields(uart.query('BENCH PROTECTION'))
            if p.get('STATE')=='2':
                fault_capture(); raise RuntimeError('Startup guardian fault; no retry')
            if p.get('ZERO')=='1' and p.get('ARMED')=='1': break
            uart.poll(.2)
        else: raise TimeoutError('No healthy startup; no reset/retry')
        row['zero']=require_zero(uart.query('BENCH ZERO'))
        row['before_protection']=p=protection(uart.query('BENCH PROTECTION'),repair_budget=profile.REPAIR_BUDGET)
        start=time.monotonic(); row['before_timing']=timing(uart.query('BENCH PROTECTION TIMING'))
        observations=[]
        while time.monotonic()-start<OBSERVE_SECONDS:
            until=time.monotonic()+.25
            while time.monotonic()<until: uart.poll(.02)
            line=uart.query('BENCH PROTECTION')
            observations.append(fields(line)); row['observations']=observations
            if fields(line).get('STATE')=='2':
                fault_capture(); raise RuntimeError('Compute guardian fault; no retry')
            after=protection(line,repair_budget=profile.REPAIR_BUDGET)
        elapsed=time.monotonic()-start
        row['after_protection']=after; row['observe_seconds']=elapsed
        row['diagnostic_feedback_rate_hz']=feedback_rate(p,after,elapsed)
        row['after_timing']=timing(uart.query('BENCH PROTECTION TIMING'))
        row['stacks']=fields(uart.query('BENCH STACK'))
        if any(int(row['stacks'].get(k,'0'))<256 for k in ('MOTOR','ROUTER','PROTO','TRANSFER')):
            raise RuntimeError('Task stack margin failed')
        row['injection_reply']=uart.query('BENCH PROTECTION TEST TIMEOUT')
        until=time.monotonic()+.02
        while time.monotonic()<until: uart.poll(.002)
        row['timeout_result']=timeout_result(uart.query('BENCH PROTECTION'),
            uart.query('BENCH PROTECTION FAULT'),uart.query('BENCH PROTECTION TIMING'))
        require_stopped(uart.query('BENCH STATUS'))
        row['pass_']=True
    except BaseException as error:
        row['failure']=str(error); raise
    finally:
        if uart and row['resets_attempted']:
            try:
                row['final_fw']=require_b457(uart.query('FW STATUS'))
                row['final_fault']=fault_fields(uart.query('BENCH PROTECTION FAULT'))
                require_stopped(uart.query('BENCH STOP'))
                if not locked(fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('Final lock absent')
                row['final_outputs']=outputs()
                if capture('final')!=before: raise RuntimeError('Flash changed during reset-only retest')
                row['all_flash_unchanged']=row['final_safe_locked']=True
            except BaseException as error:
                row['pass_']=False; row['cleanup_failure']=str(error)
                print('Final state unverified; keep motor disconnected: '+str(error),flush=True)
        if uart: row['uart']=uart.lines
        if port: port.close()
        target.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(('HARD-OFF RETEST PASS' if row['pass_'] else 'HARD-OFF RETEST FAIL')+
              ': prior trial fault retained; no motor qualification.',flush=True)
        print('Evidence: '+str(target),flush=True)

if __name__=='__main__': main()
