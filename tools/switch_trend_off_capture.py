"""One output-OFF capture on confirmed B446. No reset, write, PWM or bridge."""
import argparse
import json
import re
import subprocess
import time
from firmware_transfer_iap import fields, ROOT
from switch_feedback_acceptance import Console as BaseConsole, require_switch
from switch_feedback_off_capture import analyze
from switch_feedback_timerfix_acceptance import guard_result
from switch_trend_compare_deploy import SHA, OLD_A, OUTPUT, image
from zero_async_clock_acceptance import locked_baseline
from zero_retest_deploy import CLI, SN, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers

def trend_replay(samples):
    exe=ROOT/'tests/foc_current_zero_build/switch_trend_saved_replay.exe'
    exe.parent.mkdir(exist_ok=True)
    subprocess.run([r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe','-std=c11','-O2','-Wall','-Wextra',
                    '-Werror','-pedantic','-I',str(ROOT/'firmware_common'),
                    str(ROOT/'tests/switch_trend_saved_replay.c'),'-o',str(exe)],check=True)
    p=subprocess.run([str(exe)],input=''.join(f'{u} {v}\n' for u,v in samples),
                     text=True,capture_output=True,check=True)
    return json.loads(p.stdout)

def require_trend(line,samples):
    row=fields(line)
    if any(row.get(k)!=v for k,v in (('POLICY','OBSERVER_ONLY'),('MOTOR_READY','0'),('DELAY_PAIRS','1'))):
        raise RuntimeError('Not the fixed observer')
    replay=trend_replay(samples)
    measured=dict(N=int(row['N']),SUM=list(map(int,row['SUM'].split(','))),
                  RANGE=[list(map(int,x.split(':'))) for x in row['RANGE'].split(',')],
                  REPAIR=list(map(int,row['REPAIR'].split(','))))
    if measured!=replay: raise RuntimeError('Board Trend4 observer differs from actual shared-C replay')
    return replay

class Console(BaseConsole):
    def command(self,*args,**kwargs): raise ValueError('No reset/transfer in capture')
    def query(self,text,timeout=2):
        if text=='SWITCH TREND STATUS':
            self.request+=1; request=self.request
            self.port.write(f'{request} {text}\r\n'.encode('ascii'))
            until=time.monotonic()+timeout
            while time.monotonic()<until:
                line=self.read_line(.05)
                if line is None: continue
                self.dispatch(line)
                if line.startswith(f'{request} '):
                    if not line.startswith(f'{request} OK '): raise RuntimeError(line)
                    return line
            raise TimeoutError('No trend observer ACK')
        if text not in ('FW STATUS','ZERO STATUS','SWITCH STATUS','SWITCH START OFF',
                        'SWITCH ABORT','ANALOG VOLT') and not re.fullmatch(r'SWITCH READ \d+',text):
            raise ValueError('Only one output-OFF capture and saved-data queries')
        return super().query(text,timeout)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--powered-open-load-ready',action='store_true')
    args=parser.parse_args()
    if not args.powered_open_load_ready: parser.error('Powered sensing and disconnected U/V/W required')
    image()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    private=OUTPUT/'private'; private.mkdir(exist_ok=True)
    subprocess.run(['icacls',str(private),'/inheritance:r','/grant:r','*S-1-5-18:(OI)(CI)F',
                    '*S-1-5-32-544:(OI)(CI)F'],check=True,capture_output=True)
    run=str(time.time_ns()); target=OUTPUT/f'off-{run}.json'
    record=dict(pass_=False,image_sha256=SHA,mode='OUTPUT_OFF',resets=0,flash_writes=0,
                pwm_enabled=False,bridge_enabled=False,motion_commands=False,steps=[])
    port=uart=None
    def cli(*tokens):
        if tokens[0] not in ('-u','-r32'): raise ValueError('Read-only SWD')
        p=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,*map(str,tokens)],
                         capture_output=True,text=True,errors='replace',timeout=30)
        record['steps'].append(dict(args=list(map(str,tokens)),code=p.returncode,output=p.stdout+p.stderr))
        if p.returncode or 'Error:' in p.stdout+p.stderr: raise RuntimeError('SWD failed; no retry')
        return p.stdout+p.stderr
    def outputs():
        tokens=[]
        for a in ADDRESSES: tokens.extend(('-r32',hex(a),'4'))
        return require_registers(cli(*tokens),'B')
    try:
        record['before_outputs']=outputs()
        backup=private/f'{run}-off-identity.bin'; cli('-u','0x08000000','0x80000',backup)
        record['identity_backup']=str(backup)
        base=locked_baseline(backup.read_bytes(),known={'A':frozenset((OLD_A,)),'B':frozenset((SHA,))})
        if base['current']!='B' or base['generation']!=446: raise RuntimeError('Exact B446 required')
        record['baseline']=base
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=Console(port)
        record['before_fw']=require_confirmed(uart.query('FW STATUS'),'B')
        if record['before_fw']['GEN']!='446': raise RuntimeError('UART/Flash mismatch')
        record['before_zero']=require_service(uart.query('ZERO STATUS'))
        record['before_guard']=guard_result(uart.query('SWITCH STATUS'))
        record['analog_before']=uart.query('ANALOG VOLT')
        record['start']=uart.query('SWITCH START OFF')
        time.sleep(.25)  # Quiet capture, no polling or SWD while active.
        record['capture_line']=uart.query('SWITCH STATUS')
        row=require_switch(record['capture_line'],mode=1)
        if row.get('ACTIVE')!='0':
            uart.query('SWITCH ABORT'); raise RuntimeError('Still active past cutoff; aborted without retry')
        record['capture']=row; record['final_outputs']=outputs()
        n=int(row['N'])
        if not 0<=n<=3600: raise RuntimeError('Sample bound violated')
        record['samples']=samples=[]
        for i in range(n):
            pair=fields(uart.query(f'SWITCH READ {i}'))
            if pair.get('I')!=str(i): raise RuntimeError('Raw index mismatch')
            samples.append((int(pair['U']),int(pair['V'])))
            if (i+1)%900==0: print(f'Read saved pairs {i+1}/{n}; no active capture',flush=True)
        record['analysis']=analyze(samples,row)
        record['trend_line']=uart.query('SWITCH TREND STATUS')
        record['trend']=require_trend(record['trend_line'],samples)
        record['final_fw']=require_confirmed(uart.query('FW STATUS'),'B')
        require_switch(record['capture_line'],mode=1,complete=True)
        record['pass_']=True
        print('OFF CAPTURE PASS: actual C replay matches median and Trend4; no PWM/bridge/motor',flush=True)
    except BaseException as error:
        record['failure']=str(error); raise
    finally:
        if uart: record['uart']=uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)

if __name__=='__main__': main()
