"""Read-only snapshot capture for a separately deployed hard-off shadow image.

Does not flash, commit, reset, sample, clear faults, stop or start a fixture.
An existing fixture must already be running. No credentials are accessed.
"""
import argparse
import json
import time
from pathlib import Path
from median_control_acceptance import Console
from stable_zero_acceptance import fields
from trend4_control_commit import capture_trial_fault

ROOT=Path(__file__).resolve().parents[1]
READ=frozenset(('FW STATUS','FAULT SNAPSHOT','FAULT FILTER','FAULT SHADOW',
                'FAULT TREND','OC SHADOW STATUS','OC FILTER STATUS'))

class ObserverConsole(Console):
    def __init__(self,port): super().__init__(port,commit=False)
    def command(self,*args,**kwargs): raise ValueError('Only read-only observer queries')
    def query(self,text,timeout=1):
        if text not in READ: raise ValueError('Only read-only observer queries')
        return super().query(text,timeout)

def capture_once(uart,record):
    observer=fields(uart.query('OC SHADOW STATUS'))
    if observer.get('MODE')!='OBSERVE' or observer.get('LIMIT_MA')!='4000':
        raise RuntimeError('Hard-off four-point observer image required')
    record['observer']=observer
    record['filter_counts']=fields(uart.query('OC FILTER STATUS'))
    return capture_trial_fault(uart,record,shadow=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',action='store_true')
    parser.add_argument('--seconds',type=float,default=5)
    args=parser.parse_args()
    if not args.capture: parser.error('Select explicit read-only --capture; nothing started')
    if not 0<args.seconds<=15: parser.error('Read-only observation window must be 0..15 s')
    record=dict(pass_=False,read_only=True,flash=False,reset=False,sample=False,motion=False,
                motor_qualified=False,protection_qualified=False)
    directory=ROOT/'safety_backups/overcurrent-shadow-20261013'; directory.mkdir(exist_ok=True)
    target=directory/f'capture-{time.time_ns()}.json'
    port=uart=None
    try:
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=ObserverConsole(port)
        initial=fields(uart.query('FW STATUS')); record['initial_fw']=initial
        # This script never switches APPs; exact APP selection belongs to a
        # separately authorized, pinned deployment, not to this observer.
        deadline=time.monotonic()+args.seconds
        while True:
            fw=fields(uart.query('FW STATUS'))
            if (fw.get('CURRENT'),fw.get('GEN'))!=(initial.get('CURRENT'),initial.get('GEN')):
                raise RuntimeError('APP changed/reset; retain partial evidence, no retry')
            if capture_once(uart,record):
                record['pass_']=True; print('SNAPSHOT CAPTURED; no reset, fault clear or motion.',flush=True); break
            if time.monotonic()>=deadline:
                record['no_snapshot_observed']=True
                print('No snapshot during this window; this is NOT control qualification.',flush=True); break
            uart.poll(.1)
    except BaseException as error:
        record['failure']=str(error); raise
    finally:
        if uart: record['uart']=uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)

if __name__=='__main__': main()
