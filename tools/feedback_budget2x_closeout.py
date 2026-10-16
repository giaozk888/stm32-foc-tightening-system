"""Read-only closeout of B457 after the recorded 6/4 trial fault. No retry."""
import json
from pathlib import Path
import subprocess
import time
import serial
import feedback_budget2x_acceptance as profile
from feedback_safety_commit import Console, stage_evidence
from firmware_transfer_iap import fields
from zero_retest_deploy import CLI, SN, compare_flash, require_confirmed
from zero_span100_acceptance import ADDRESSES, require_registers
from tighten_synthetic_acceptance import locked, require_stopped

def main():
    prior_path=profile.OUTPUT/'commit-1791890323441473800.json'
    prior=json.loads(prior_path.read_text('utf-8'))
    if (prior.get('pass_') is not False or prior.get('final_safe_locked') is not True or
            prior.get('confirmed_fw',{}).get('GEN')!='457' or
            prior.get('image_sha256')!=profile.SHA or not prior.get('trial_faults')):
        raise RuntimeError('Exact failed trial and locked B457 required')
    original=stage_evidence(profile.OUTPUT/'stage-1791889629135739100.json',profile)
    run=str(time.time_ns())
    row=dict(pass_=False,read_only_closeout=True,prior_trial_pass=False,
             motor_qualified=False,image_sha256=profile.SHA,steps=[])
    def cli(*tokens):
        if tokens[0] not in ('-u','-r32'): raise ValueError('Read only')
        proc=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000',
            'sn='+SN,*map(str,tokens)],capture_output=True,text=True,errors='replace',timeout=30)
        out=proc.stdout+proc.stderr
        row['steps'].append(dict(args=list(map(str,tokens)),code=proc.returncode,output=out))
        if proc.returncode or 'Error:' in out: raise RuntimeError('Read failed; no retry/reset')
        return out
    port=None
    try:
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=Console(port)
        row['fw']=require_confirmed(uart.query('FW STATUS'),'B')
        if row['fw']['GEN']!='457': raise RuntimeError('Not B457')
        row['bench']=fields(uart.query('BENCH STATUS'))
        require_stopped(' '.join(f'{k}={v}' for k,v in row['bench'].items()))
        row['safe']=fields(uart.query('ANALOG SAFE STATUS'))
        if not locked(row['safe']): raise RuntimeError('Lock missing')
        for key,cmd in (('zero','BENCH ZERO'),('protection','BENCH PROTECTION'),
                        ('timing','BENCH PROTECTION TIMING'),('stacks','BENCH STACK')):
            row[key]=fields(uart.query(cmd))
        row['outputs']=require_registers(cli(*(x for a in ADDRESSES for x in ('-r32',hex(a),'4'))),'B')
        backup=profile.OUTPUT/'private'/f'{run}-closeout.bin'
        cli('-u','0x08000000','0x80000',backup)
        row['closeout_backup']=str(backup)
        row['flash']=compare_flash(original,backup.read_bytes(),profile.image(),'B')
        row['pass_']=True
        print('READ-ONLY CLOSEOUT PASS: exact B457, protected Flash unchanged, stopped and locked; prior trial FAIL.')
    finally:
        if port: port.close()
        target=profile.OUTPUT/f'closeout-{run}.json'
        target.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target))

if __name__=='__main__': main()
