"""Manual hand-turn collection ONLY. Default is an offline plan.

No flashing, resets, PWM/Iq commands, or offset requests are implemented.
Use only after the separate diagnostic has been manually deployed/preflighted.
"""
import argparse
from pathlib import Path
import time
from firmware_transfer_iap import Uart,fields
from electrical_angle_report import hand_report

ROOT=Path(__file__).resolve().parents[1]


def allowed(command):
    if command in ('FW STATUS','MOTOR TEST STATUS','STOP','ANALOG SAFE',
        'MOTOR TEST ANGLE BEGIN','MOTOR TEST ANGLE END','MOTOR TEST ANGLE STATUS'): return True
    prefix='MOTOR TEST ANGLE READ '
    return command.startswith(prefix) and command[len(prefix):].isdigit()


class HandConsole(Uart):
    def __init__(self,port,log):
        super().__init__(port); self.log=log

    def dispatch(self,line):
        if ' OK ANGLE ' in line or ' ERR ' in line:
            self.log.write(line+'\n'); self.log.flush()
        super().dispatch(line)

    def query(self,command,timeout=.6):
        if not allowed(command): raise ValueError('Hand-only command whitelist')
        self.request+=1; request=self.request
        self.port.write(f'{request} {command}\r\n'.encode('ascii'))
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            line=self.read_line(.02)
            if line is None: continue
            self.dispatch(line)
            if line.startswith(f'{request} '):
                if not line.startswith(f'{request} OK '): raise RuntimeError(line)
                return line
        raise TimeoutError('Hand read not acknowledged; no automatic retry')


def collect(uart,seconds,*,clock=time.monotonic,pause=time.sleep):
    if not 5<=seconds<=60: raise ValueError('Hand window must be 5..60 seconds')
    fw=fields(uart.query('FW STATUS'))
    if fw.get('CURRENT')!='A' or fw.get('CONFIRMED')!='A' or fw.get('PENDING')!='-':
        raise RuntimeError('Already confirmed diagnostic A required; no activation here')
    state=fields(uart.query('MOTOR TEST STATUS'))
    if any(state.get(k)!=v for k,v in dict(STATE='1',USED='0',ZERO='3',FLAGS='0',FAULT='0',SD='0',MOE='0',CCER='0').items()):
        raise RuntimeError('Calibrated unused output-OFF READY required')
    next_seq=0; begun=False
    def drain(status):
        nonlocal next_seq
        if any(status.get(k)!=v for k,v in dict(OFF='1',ERR='0',PP='10',DIR='-1',ZERO='10507').items()):
            raise RuntimeError('Hand mapping/gate/data error; preserve log')
        n=int(status['N'])
        if n-next_seq>12: raise RuntimeError('Hand ring overrun; no fabricated missing rows')
        while next_seq<n:
            row=fields(uart.query(f'MOTOR TEST ANGLE READ {next_seq}'))
            if row.get('ROW')!=str(next_seq): raise RuntimeError('Wrong hand row sequence')
            next_seq+=1
    try:
        uart.query('MOTOR TEST ANGLE BEGIN'); begun=True; end=clock()+seconds
        while clock()<end:
            drain(fields(uart.query('MOTOR TEST ANGLE STATUS')))
            pause(.02)
    finally:
        if begun: uart.query('MOTOR TEST ANGLE END')
    status=fields(uart.query('MOTOR TEST ANGLE STATUS')); drain(status)
    if status.get('PASS')!='1': raise RuntimeError('No complete full turn and return, or angle check failed')
    return next_seq


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--collect',action='store_true'); p.add_argument('--outputs-off-confirmed',action='store_true')
    p.add_argument('--port',default='COM5'); p.add_argument('--seconds',type=float,default=20)
    a=p.parse_args()
    if not a.collect:
        print('OFFLINE PLAN: output-OFF hand turn + one revolution and return; no devices, no motor commands'); return 0
    if not a.outputs_off_confirmed: p.error('Explicit output-OFF confirmation required')
    if not 5<=a.seconds<=60: p.error('Window must be 5..60 seconds')
    import serial
    path=ROOT/'tmp'/('angle-hand-'+str(time.time_ns())+'.log')
    with path.open('x',encoding='utf-8') as log:
        print('Local hand record: '+str(path),flush=True)
        port=serial.Serial(a.port,2000000,timeout=.05)
        try: collect(HandConsole(port,log),a.seconds)
        finally: port.close()
    result=hand_report(path.read_text('utf-8'))
    print(str(path)); print('SOFTWARE_CHAIN_PASS='+str(result['software_chain_pass']))
    return 0 if result['software_chain_pass'] else 1


if __name__=='__main__': raise SystemExit(main())
