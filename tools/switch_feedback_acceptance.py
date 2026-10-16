"""Pinned B open-load diagnostic deployment and strictly separate captures.

Deploy with drive power OFF only. Official pw_transfer stages inactive B;
normal bootloader/service health confirms it. Deployment tests TIM7 with
ALL outputs OFF, never enables PWM signals or the power stage. Capture is
a separate user-authorized operation. No motion, fault clearing, retries,
direct Flash metadata writes, or forced confirmation.
"""
import argparse
import hashlib
import json
import re
import subprocess
import struct
import time
from pathlib import Path
from firmware_transfer_iap import ROOT, Uart, image_info, stage, DEFAULT_CLIENT, fields
from zero_retest_deploy import CLI, SN, compare_flash, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers, observe_trial
from zero_async_clock_acceptance import locked_baseline

IMAGE=ROOT/'foc2_app_b/build/SwitchFeedback20261012/foc2.bin'
SHA='10451eb6f8344939cdeed33b573dab2050c908d84da26b0b407ae1e294417c0d'
OUTPUT=ROOT/'safety_backups/switch-feedback-20261012'
ORIGINAL_A='4ba450ebf3af17f32f418be57639ebfc6981268627066d5375f0d36d23f41bf1'
ORIGINAL_B='de086d613ee504e792ec67d7119afee0039306852776f7850c22818944cf6eff'

def image():
    data=IMAGE.read_bytes()
    if image_info(data)[0]!='B' or hashlib.sha256(data).hexdigest()!=SHA:
        raise RuntimeError('Exact offline-tested open-load B required')
    for marker in (b'OPEN_LOAD_ONLY',b'180ms capture/190ms TIM7 guard',b'MOTOR_READY=0'):
        if marker not in data: raise RuntimeError('Missing diagnostic marker')
    reset=struct.unpack_from('<I',data,4)[0]&~1
    if data[reset-0x08040000:reset-0x08040000+2]!=b'\x72\xb6':
        raise RuntimeError('Reset must mask inherited interrupts before CRT')
    guard=struct.unpack_from('<I',data,(16+55)*4)[0]
    if not guard&1 or not 0x08040000<=guard&~1<0x08040000+len(data):
        raise RuntimeError('TIM7/DAC vector missing')
    return data

def baseline(data):
    row=locked_baseline(data,known={'A':frozenset((ORIGINAL_A,)), 'B':frozenset((ORIGINAL_B,))})
    if row['current']!='A' or row['generation']!=417:
        raise RuntimeError('Only exact confirmed stopped A generation 417 admitted')
    return row

def require_switch(line, mode=None, complete=False):
    row=fields(line)
    if row.get('PROFILE')!='OPEN_LOAD_ONLY' or row.get('MOTOR_READY')!='0':
        raise RuntimeError('Not the isolated open-load diagnostic')
    if mode is not None and row.get('MODE')!=str(mode): raise RuntimeError('Wrong capture mode')
    if row.get('ACTIVE')=='0':
        for k in ('SD','MOE','CCER','CEN'):
            if row.get(k)!='0': raise RuntimeError('Output off proof missing: '+k)
    elif row.get('ACTIVE')!='1': raise RuntimeError('Missing active state')
    if complete:
        if row.get('ACTIVE')!='0' or row.get('REASON')!='1' or row.get('N')!='3600' or row.get('FN')!='3598':
            raise RuntimeError('Capture did not complete; no automatic repeat')
        if not 170000<=int(row['US'])<=190000: raise RuntimeError('Unexpected capture rate/deadline')
    return row

class Console(Uart):
    def __init__(self,port):
        super().__init__(port); self.lines=[]; self.starts=set(); self.ends=0
    def dispatch(self,line):
        if line: self.lines.append(line)
        super().dispatch(line)
        if 'ZERO SERVICE HEALTH' in line: print(line,flush=True)
        if 'HardFault' in line or 'CREATE FAILED' in line: raise RuntimeError('Startup fault; no retry')
    def query(self,text,timeout=2):
        if text.startswith('SWITCH START '):
            if text not in ('SWITCH START GUARD','SWITCH START OFF','SWITCH START PWM','SWITCH START BRIDGE'):
                raise ValueError('Unknown capture')
            if text in self.starts: raise ValueError('No automatic repeat of start')
            self.starts.add(text)
        elif text not in ('FW STATUS','ZERO STATUS','ZERO FILTER STATUS','ANALOG SAFE STATUS',
                          'BENCH STATUS','SWITCH STATUS','SWITCH ABORT','SWITCH WAVE VERIFIED',
                          'ANALOG VOLT','ZERO SAMPLE') and not re.fullmatch(r'SWITCH READ \d+',text):
            raise ValueError('Unsupported diagnostic command')
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
        raise TimeoutError('No ACK; no resend: '+text)
    def command(self,text,timeout=5):
        if text=='FW END':
            if self.ends: raise ValueError('One commit only')
            self.ends+=1
        return super().command(text,timeout)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('deploy','off','pwm','bridge','inspect'))
    parser.add_argument('--drive-12v-off',action='store_true')
    parser.add_argument('--powered-open-load-ready',action='store_true')
    parser.add_argument('--waveform-evidence',type=Path)
    args=parser.parse_args()
    if args.mode=='deploy' and not args.drive_12v_off: parser.error('Drive power OFF required')
    if args.mode in ('off','pwm','bridge') and not args.powered_open_load_ready:
        parser.error('Powered current sensing and disconnected U/V/W required')
    if args.mode=='bridge':
        # A reviewed machine-readable all-six waveform report must be supplied.
        # Do not infer this from TIM registers or accept an arbitrary boolean.
        parser.error('Bridge execution not exposed until physical waveform report validator is implemented')
    data=image(); OUTPUT.mkdir(parents=True,exist_ok=True)
    private=OUTPUT/'private'; private.mkdir(exist_ok=True)
    subprocess.run(['icacls',str(private),'/inheritance:r','/grant:r',
                    '*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F'],check=True,capture_output=True)
    run=str(time.time_ns()); target=OUTPUT/f'{args.mode}-{run}.json'
    record=dict(mode=args.mode,pass_=False,image_sha256=SHA,steps=[],motion_commands=False,
                force_confirm=False,bridge_enabled=False,automatic_retry=False)
    port=uart=None
    def cli(*tokens):
        if tokens[0] not in ('-u','-r32'): raise ValueError('Read-only probe only')
        p=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,*map(str,tokens)],
                         capture_output=True,text=True,errors='replace',timeout=30)
        record['steps'].append(dict(args=list(map(str,tokens)),code=p.returncode,output=p.stdout+p.stderr))
        if p.returncode or 'Error:' in p.stdout+p.stderr: raise RuntimeError('SWD failed; no retry')
        return p.stdout+p.stderr
    def capture(name):
        path=private/f'{run}-{name}.bin'; cli('-u','0x08000000','0x80000',path)
        raw=path.read_bytes(); record[name+'_backup']=str(path)
        if len(raw)!=0x80000: raise RuntimeError('Incomplete capture')
        return raw
    def outputs(slot):
        tokens=[]
        for address in ADDRESSES: tokens.extend(('-r32',hex(address),'4'))
        return require_registers(cli(*tokens),slot)
    try:
        original=capture('before')
        if args.mode=='deploy':
            record['baseline']=base=baseline(original); record['before_outputs']=outputs('A')
        else:
            base=locked_baseline(original,known={'A':frozenset((ORIGINAL_A,)),'B':frozenset((SHA,))})
            if base['current']!='B': raise RuntimeError('Exact normally confirmed open-load B required')
            record['before_outputs']=outputs('B')
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=Console(port)
        record['before_fw']=fw=require_confirmed(uart.query('FW STATUS'),base['current'])
        if int(fw['GEN'])!=base['generation']: raise RuntimeError('Metadata mismatch')
        if args.mode=='deploy':
            safety=fields(uart.query('ANALOG SAFE STATUS'))
            if any(safety.get(k)!=v for k,v in (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
                raise RuntimeError('Original A not output locked')
            stage(uart,IMAGE,DEFAULT_CLIENT,allow_reset=False)
            record['staged_flash']=compare_flash(original,capture('staged'),data,'B',staged=True)
            record['staged_outputs']=outputs('A')
            try: uart.command('FW END',20)
            except TimeoutError: print('Commit ACK uncertain; observe once, no resend',flush=True)
            record['confirmed']=observe_trial(uart,'B')
            record['fresh']=require_switch(uart.query('SWITCH STATUS'))
            # This deliberately runs TIM7 without ANY TIM1/ADC/PWM activity.
            uart.query('SWITCH START GUARD')
            time.sleep(.25)
            guard=require_switch(uart.query('SWITCH STATUS'),mode=4)
            if (guard.get('ACTIVE')!='0' or guard.get('REASON')!='2' or guard.get('N')!='0' or
                not 185000<=int(guard['US'])<=195000 or not int(guard['DONE'])&16):
                raise RuntimeError('Independent TIM7 cutoff failed; no bridge admitted')
            record['independent_guard']=guard
            record['final_flash']=compare_flash(original,capture('final'),data,'B')
        elif args.mode in ('off','pwm'):
            mode=1 if args.mode=='off' else 2
            record['before_switch']=require_switch(uart.query('SWITCH STATUS'))
            record['start']=fields(uart.query('SWITCH START '+args.mode.upper()))
            time.sleep(.25) # Capture quietly, no polling and no SWD while active.
            row=require_switch(uart.query('SWITCH STATUS'),mode,complete=True)
            record['capture']=row
            samples=[]
            for index in range(int(row['N'])):
                pair=fields(uart.query(f'SWITCH READ {index}'))
                if pair.get('I')!=str(index): raise RuntimeError('Raw index mismatch')
                samples.append((int(pair['U']),int(pair['V'])))
            record['samples']=samples
            if sum(u for u,v in samples)!=int(row['SUM'].split(',')[0]) or sum(v for u,v in samples)!=int(row['SUM'].split(',')[1]):
                raise RuntimeError('Raw replay does not match ISR sums')
        else: record['status']=require_switch(uart.query('SWITCH STATUS'))
        record['final_outputs']=outputs('B')
        record['final_fw']=require_confirmed(uart.query('FW STATUS'),'B')
        record['pass_']=True
        print('SWITCH '+args.mode.upper()+' PASS: output OFF; motor NOT qualified; bridge NOT enabled',flush=True)
    except BaseException as error:
        record['failure']=str(error); raise
    finally:
        if uart: record['uart']=uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)

if __name__=='__main__': main()
