"""Disconnected-motor filtered bridge: deploy OFF, capture only after powered readiness.

Inactive B only, preserve A460/boot/parameters. Normal official Transfer and
bootloader health confirmation, no force-confirm, fault clear, reset retry or
motion. Deployment tests only the output-OFF guard. Capture is a separate
single attempt: fresh zero + OFF baseline + USER_ATTESTED waves, 50ms maximum
bridge session, then saved timed data/replay and independent output readback.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import time

from firmware_transfer_iap import ROOT, Uart, DEFAULT_CLIENT, fields, image_info, stage
from switch_feedback_acceptance import require_switch
from switch_feedback_timerfix_acceptance import guard_result
from zero_retest_deploy import CLI, SN, require_confirmed, require_service, compare_flash
from zero_span100_acceptance import ADDRESSES, require_registers
from zero_async_clock_acceptance import locked_baseline
from powered_boot_probe import require_staged
from tighten_synthetic_acceptance import locked, require_stopped
from six_signal_capture import supply

IMAGE=ROOT/'foc2_app_b/build/FilteredBridge20261013/foc2.bin'
SHA='eb13779af465650dc7a82ac99b0a494e1e0796bb783a2e76b5b10020d4779ca9'
OLD_A='8769374cec2038667aa505bbfbd909b5ddb2010d95dccbbb2294a498aad1fe45'
OLD_B='89f6e449c105bb4eb8ea4d5e52fecea8dc7443061abb1f175758a637e2a6de00'
REFERENCE=ROOT/'safety_backups/six-signal-live-20261013/swd-deploy-1791893034037262400.json'
OUTPUT=ROOT/'safety_backups/filtered-bridge-live-20261013'
MANIFEST=ROOT/'firmware_common/FILTERED_BRIDGE_B_MANIFEST.json'

def image():
    data=IMAGE.read_bytes(); m=json.loads(MANIFEST.read_text('utf-8'))
    if (len(data)!=m['bytes'] or m['sha256']!=SHA or hashlib.sha256(data).hexdigest()!=SHA or
            image_info(data)[0]!='B' or m['motor_qualified'] is not False):
        raise RuntimeError('Exact offline-tested disconnected B fixture required')
    pc=(struct.unpack_from('<I',data,4)[0]&~1)-0x08040000
    guard=struct.unpack_from('<I',data,(16+55)*4)[0]
    if data[pc:pc+2]!=b'\x72\xb6' or not guard&1 or not 0x08040000<=guard&~1<0x08040000+len(data):
        raise RuntimeError('Reset mask/guard vector missing')
    for marker in (b'DISCONNECTED_50MS',b'HARDWARE_TRIP_VERIFIED=0',b'RAW=VALIDITY_ONLY',
                   b'FILTERED=4A_2OF3',b'REPAIR_BUDGET=6/4',b'MOTOR_READY=0'):
        if marker not in data: raise RuntimeError('Fixture identity missing')
    return data

def baseline(raw):
    identity=locked_baseline(raw,known={'A':frozenset((OLD_A,)),'B':frozenset((OLD_B,))})
    receipt=json.loads(REFERENCE.read_text('utf-8'))
    path=Path(receipt['final_backup']).resolve()
    if (identity['current']!='A' or identity['generation']!=460 or
            receipt.get('pass_') is not True or receipt.get('final_safe_locked') is not True or
            path.parent!=(REFERENCE.parent/'private').resolve() or raw!=path.read_bytes()):
        raise RuntimeError('Exact A460 confirmed private Flash baseline required')
    return identity

class Console(Uart):
    def __init__(self,port,*,capture=False):
        super().__init__(port); self.lines=[]; self.starts=set(); self.ends=0; self.capture=capture
    def dispatch(self,line):
        if line: self.lines.append(line)
        super().dispatch(line)
        if 'ZERO SERVICE HEALTH' in line: print(line,flush=True)
        if 'HardFault' in line or 'CREATE FAILED' in line: raise RuntimeError('Startup fault; no retry')
    def query(self,text,timeout=2):
        allowed={'FW STATUS','ZERO STATUS','ZERO FILTER STATUS','ANALOG SAFE STATUS',
                 'BENCH STATUS','SWITCH STATUS','SWITCH ABORT','SWITCH START GUARD',
                 'SWITCH START FILTERED_GUARD'}
        if self.capture:
            allowed|={'ANALOG VOLT','ZERO SAMPLE','SWITCH START OFF',
                      'SWITCH WAVE VERIFIED','SWITCH START FILTERED_BRIDGE','SWITCH FEEDBACK STATUS'}
        if text not in allowed and not (self.capture and re.fullmatch(r'SWITCH (READ|FILTERED READ) \d+',text)):
            raise ValueError('No motion, legacy bridge, fault clear or reset command')
        if text.startswith('SWITCH START ') or text in ('ZERO SAMPLE','SWITCH WAVE VERIFIED'):
            if text in self.starts: raise ValueError('Single attempt; no resend after uncertain ACK')
            self.starts.add(text)
        self.request+=1; request=self.request
        self.port.write(f'{request} {text}\r\n'.encode('ascii'))
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            line=self.read_line(.05)
            if line is None: continue
            self.dispatch(line)
            if line.startswith(f'{request} '):
                if not line.startswith(f'{request} OK '): raise RuntimeError(line)
                return line
        raise TimeoutError('No ACK; no resend: '+text)
    def command(self,text,timeout=5):
        if self.capture: raise ValueError('Capture never writes Flash/metadata')
        if text=='FW END':
            if self.ends: raise ValueError('One commit only')
            self.ends+=1
        return super().command(text,timeout)

def observe(uart):
    deadline=time.monotonic()+90; seen=False
    while time.monotonic()<deadline:
        try: fw=fields(uart.query('FW STATUS',.5))
        except TimeoutError: continue
        if fw.get('CURRENT')!='B':
            if seen or fw.get('PENDING')=='-': raise RuntimeError('Trial fallback; no retry')
            uart.poll(.1); continue
        seen=True
        require_service(uart.query('ZERO STATUS'))
        require_switch(uart.query('SWITCH STATUS'))
        if fw.get('CONFIRMED')=='B' and fw.get('PENDING')=='-':
            return require_confirmed(' '.join(f'{k}={v}' for k,v in fw.items()),'B')
        uart.poll(.1)
    raise TimeoutError('Normal service did not confirm; no forced confirmation')

def feedback(line):
    row=fields(line)
    policy={'PROFILE':'DISCONNECTED_50MS','MOTOR_READY':'0','RAW':'VALIDITY_ONLY',
            'FILTERED':'4A_2OF3','REPAIR_BUDGET':'6/4','MAX_US':'50000',
            'DEADLINE_US':'100','GUARD_US':'25','WAVE_SOURCE':'USER_ATTESTED',
            'HARDWARE_TRIP_VERIFIED':'0'}
    if any(row.get(k)!=v for k,v in policy.items()): raise RuntimeError('Filtered policy mismatch')
    return row

def filtered_guard_result(line):
    row=require_switch(line,mode=6)
    if (row.get('ACTIVE')!='0' or row.get('REASON')!='2' or row.get('N')!='0' or
        row.get('IRQ')!='2000' or not 49500<=int(row.get('US','0'))<=50100 or
        int(row.get('DONE','0'))&80!=80 or int(row.get('IRQ_SR','0'))&1!=1):
        raise RuntimeError('Output-OFF 25us guard selftest missing/failed')
    return row

def replay(samples,zero,vdda,measured):
    exe=ROOT/'tests/foc_current_zero_build/bridge_feedback_replay.exe'
    subprocess.run([r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe','-std=c11','-O2','-Wall','-Wextra',
        '-Werror','-DFOC_PROTECTION_HOST_TEST=1','-I',str(ROOT/'firmware_common'),
        str(ROOT/'tests/bridge_feedback_replay_host.c'),'-o',str(exe)],check=True,capture_output=True)
    text=f'{zero[0]} {zero[1]} {vdda} {len(samples)}\n'+''.join(f'{u} {v} {t}\n' for u,v,t in samples)
    result=subprocess.run([str(exe)],input=text,capture_output=True,text=True,check=True)
    row=fields(result.stdout)
    for key in ('N','FN','REPAIRED','RESULT','REASON','LAST_US'):
        if row.get(key)!=measured.get(key): raise RuntimeError('Exact timestamp C replay differs: '+key)
    return row

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('deploy','capture'))
    parser.add_argument('--drive-12v-off',action='store_true')
    parser.add_argument('--motor-disconnected',action='store_true')
    parser.add_argument('--powered-open-load-ready',action='store_true')
    parser.add_argument('--sd-connected',action='store_true')
    parser.add_argument('--waves-user-attested',action='store_true')
    parser.add_argument('--deployment',type=Path)
    args=parser.parse_args()
    if not args.motor_disconnected: parser.error('Disconnected motor required')
    if args.mode=='deploy' and not args.drive_12v_off: parser.error('Physical drive OFF required')
    if args.mode=='capture' and not (args.powered_open_load_ready and args.sd_connected and
                                    args.waves_user_attested and args.deployment):
        parser.error('Powered readiness, SD connected and manually attested waves + deploy receipt required')
    import serial
    data=image(); OUTPUT.mkdir(parents=True,exist_ok=True)
    private=OUTPUT/'private'; private.mkdir(exist_ok=True)
    subprocess.run(['icacls',str(private),'/inheritance:r','/grant:r',
                    '*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F'],check=True,capture_output=True)
    run=str(time.time_ns()); target=OUTPUT/f'{args.mode}-{run}.json'
    row=dict(pass_=False,mode=args.mode,image_sha256=SHA,motor_qualified=False,motion_commands=False,
             force_confirm=False,direct_metadata_write=False,automatic_retry=False,
             bridge_start_sent=False,bridge_observed=False,waveform_automatically_measured=False,
             hardware_trip_timing_verified=False,physical_motor_disconnected_user_confirmed=True,steps=[])
    port=uart=None; before=None; started=False; stopped=True
    def cli(*tokens):
        if not tokens or tokens[0] not in ('-u','-r32'): raise ValueError('Read-only SWD')
        result=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,*map(str,tokens)],
            capture_output=True,text=True,errors='replace',timeout=30)
        out=result.stdout+result.stderr
        row['steps'].append(dict(args=list(map(str,tokens)),code=result.returncode,output=out))
        if result.returncode or 'Error:' in out: raise RuntimeError('Read-only probe failed; no retry')
        return out
    def capture_flash(name):
        path=private/f'{run}-{name}.bin'; cli('-u','0x08000000','0x80000',path)
        raw=path.read_bytes(); row[name+'_backup']=str(path)
        if len(raw)!=0x80000: raise RuntimeError('Incomplete protected backup')
        return raw
    def outputs(slot):
        return require_registers(cli(*(x for a in ADDRESSES for x in ('-r32',hex(a),'4'))),slot)
    try:
        before=capture_flash('before')
        if args.mode=='deploy': row['baseline']=baseline(before); current='A'
        else:
            deployed=json.loads(args.deployment.read_text('utf-8'))
            path=Path(deployed['final_backup']).resolve()
            if (args.deployment.resolve().parent!=OUTPUT.resolve() or not deployed.get('pass_') or
                not deployed.get('final_safe_locked') or deployed.get('image_sha256')!=SHA or
                path.parent!=private.resolve() or before!=path.read_bytes()):
                raise RuntimeError('Exact successful deployment receipt required')
            current='B'; row['deployment']=str(args.deployment); row['generation']=deployed['final_fw']['GEN']
        row['before_outputs']=outputs(current)
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open()
        uart=Console(port,capture=args.mode=='capture')
        row['before_fw']=require_confirmed(uart.query('FW STATUS'),current)
        expected='460' if args.mode=='deploy' else row['generation']
        if row['before_fw'].get('GEN')!=expected: raise RuntimeError('UART/Flash generation mismatch')
        require_service(uart.query('ZERO STATUS'))
        if args.mode=='deploy':
            if not locked(fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('Latch absent')
            # A460's standalone service deliberately excludes BENCH commands.
            # require_service + independent SWD prove FOC/power are stopped.
            row['stage_attempted']=True; stage(uart,IMAGE,DEFAULT_CLIENT,allow_reset=False)
            row['staged_flash']=compare_flash(before,capture_flash('staged'),data,'B',staged=True)
            row['staged_outputs']=outputs('A')
            require_staged(uart.query('FW STATUS'),'SOURCE=SWD SD=0 MOE=0 CEN=0',data)
            row['commit_attempted']=True
            try: uart.command('FW END',20)
            except TimeoutError: print('Commit ACK uncertain: observe, never resend',flush=True)
            row['confirmed']=observe(uart)
            fresh=require_switch(uart.query('SWITCH STATUS'))
            if fresh.get('ATTEMPTS')!='0' or fresh.get('N')!='0': raise RuntimeError('Not fresh fixture')
            row['guard_start']=uart.query('SWITCH START GUARD'); time.sleep(.25)
            row['guard_line']=uart.query('SWITCH STATUS'); row['guard']=guard_result(row['guard_line'])
            row['filtered_guard_start']=uart.query('SWITCH START FILTERED_GUARD'); time.sleep(.10)
            row['filtered_guard_line']=uart.query('SWITCH STATUS')
            row['filtered_guard']=filtered_guard_result(row['filtered_guard_line'])
            row['final_fw']=require_confirmed(uart.query('FW STATUS'),'B')
            row['final_outputs']=outputs('B'); require_service(uart.query('ZERO STATUS'))
            row['final_flash']=compare_flash(before,capture_flash('final'),data,'B')
            if row['final_flash']['generation']!=int(row['final_fw']['GEN']):
                raise RuntimeError('Confirmation generation mismatch')
        else:
            row['filtered_guard']=filtered_guard_result(uart.query('SWITCH STATUS'))
            zero=require_service(uart.query('ZERO STATUS'))
            if zero.get('STATE')!='0' or zero.get('N')!='0': raise RuntimeError('Zero already used; no reset')
            row['supply']=supply(uart.query('ANALOG VOLT'))
            row['zero_start']=uart.query('ZERO SAMPLE'); time.sleep(5.3)
            row['zero_line']=uart.query('ZERO STATUS'); row['zero']=zero=require_service(row['zero_line'])
            row['zero_filter']=fields(uart.query('ZERO FILTER STATUS'))
            if zero.get('STATE')!='3' or zero.get('N')!='4000' or zero.get('REASON')!='0':
                raise RuntimeError('Median zero failed; no bridge command sent')
            row['off_start']=uart.query('SWITCH START OFF'); time.sleep(.25)
            row['off_line']=uart.query('SWITCH STATUS'); row['off']=require_switch(row['off_line'],mode=1,complete=True)
            row['off_outputs']=outputs('B')
            row['wave_source']='USER_ATTESTED prior six-channel user confirmation; no new waveform PASS'
            row['wave_ack']=uart.query('SWITCH WAVE VERIFIED')
            row['bridge_supply']=supply(uart.query('ANALOG VOLT'))
            row['bridge_start_sent']=started=True; stopped=False
            row['bridge_start_line']=uart.query('SWITCH START FILTERED_BRIDGE')
            active=require_switch(row['bridge_start_line'],mode=5)
            row['bridge_observed']=active.get('ACTIVE')=='1' and active.get('SD')=='1'
            time.sleep(.15) # no UART/SWD interference during the single <=50ms session
            row['switch_line']=uart.query('SWITCH STATUS'); row['switch']=result=require_switch(row['switch_line'],mode=5)
            if result.get('ACTIVE')!='0': raise RuntimeError('Still active after cutoff')
            row['final_outputs']=outputs('B'); stopped=True
            row['feedback_line']=uart.query('SWITCH FEEDBACK STATUS'); row['feedback']=fp=feedback(row['feedback_line'])
            n=int(result['N'])
            if not 0<n<=1000: raise RuntimeError('No bounded saved samples')
            row['samples']=samples=[]
            for i in range(n):
                saved=fields(uart.query(f'SWITCH FILTERED READ {i}'))
                if saved.get('I')!=str(i): raise RuntimeError('Saved index mismatch')
                samples.append((int(saved['U']),int(saved['V']),int(saved['US'])))
                if (i+1)%250==0: print(f'Saved {i+1}/{n} timed pairs; outputs OFF',flush=True)
            row['replay']=replay(samples,tuple(map(int,result['ZERO'].split(','))),
                                 int(row['bridge_supply']['VDDA_BOOT_MV']),fp)
            row['final_fw']=require_confirmed(uart.query('FW STATUS'),'B')
            if capture_flash('final')!=before: raise RuntimeError('Flash changed during capture')
            row['all_flash_unchanged']=True; row['final_safe_locked']=True
            if (result.get('REASON')!='1' or n!=1000 or int(result['US'])>50100 or
                fp.get('FN')!='997' or fp.get('REASON')!='0' or fp.get('RESULT')!='0' or
                int(fp['WORK_MAX_US'])>=25):
                raise RuntimeError('Bridge capture stopped early/late or protection tripped; saved, no retry')
        row['final_safe_locked']=row['pass_']=True
        print(f'{args.mode.upper()} PASS: B fixture; SD/PWM OFF; motor NOT qualified',flush=True)
    except BaseException as error:
        row['failure']=str(error)
        if uart and (started and not stopped or row.get('commit_attempted')):
            try:
                actual=fields(uart.query('FW STATUS',2)).get('CURRENT')
                if actual in ('A','B'):
                    row['abort']=require_switch(uart.query('SWITCH ABORT'))
                    row['failure_outputs']=outputs(actual); row['failure_safe_locked']=True
            except BaseException as cleanup: row['cleanup_failure']=str(cleanup)
        raise
    finally:
        if uart: row['uart']=uart.lines
        if port: port.close()
        target.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)
if __name__=='__main__': main()
