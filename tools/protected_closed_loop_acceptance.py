"""Exact staged B trial, then ONE fixed 20 rpm/400 ms local closed-loop attempt.

No flash programming, direct metadata writes, forced confirmation, clearing,
setpoint edits or START retry. Hardware limits and wiring must be known.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

import protected_closed_loop_stage as profile
from firmware_transfer_iap import Uart, fields
from powered_boot_probe import require_staged
from zero_retest_deploy import compare_flash, require_confirmed, latest_meta

def protected_state(line,ready=False):
    s=fields(line)
    for k,v in (('SD','0'),('MOE','0'),('CCER','0'),('FLAGS','0'),('FAULT','0'),('QUALIFIED','0')):
        if s.get(k)!=v: raise RuntimeError('Protected state not healthy/off: '+line)
    if ready and any(s.get(k)!=v for k,v in (('STATE','1'),('USED','0'),('QUEUED','0'),('ARMED','1'),('ZERO','3'))):
        raise RuntimeError('Not fresh READY: '+line)
    return s

def timing(line):
    t=fields(line)
    if (t.get('CLOCK_HZ')!='1000000' or t.get('LATE')!='0' or
        not 0<int(t.get('MAX_US','50'))<50 or int(t.get('WORK','0'))<1000 or
        int(t.get('OUTER','0'))<100 or int(t.get('IRQ','0'))<1000 or
        any(t.get(k)!=v for k,v in (('LEASE_US','400000'),('SAMPLE_US','100'),('OUTER_US','2000')))):
        raise RuntimeError('No healthy within-period compute/guard evidence: '+line)
    return t

def protection(line):
    p=fields(line)
    if any(p.get(k)!=v for k,v in (('FILTER','TREND4'),('OC','2_OF_3'),('TRIP_MA','4000'),
        ('STATE','0'),('REASON','0'),('FLAGS','0'),('BUDGET','6'),('STREAK','4'))):
        raise RuntimeError('Protected feedback unhealthy: '+line)
    return p

def register_off(output,slot,trigger=None):
    regs={int(a,16):int(v,16) for a,v in re.findall(r'(?im)^0x([0-9A-F]+)\s*:\s*([0-9A-F]{8})\s*$',output)}
    if (set(regs)!=set(profile.ADDRESSES) or regs[0xE000ED08]!=(0x08008000 if slot=='A' else 0x08040000)
        or regs[0x48000814]&0x40 or regs[0x40012C44]&0xC000 or regs[0x40012C20] or regs[0xE000ED28]
        or (trigger is not None and bool(regs[0x40012C00]&1)!=trigger)):
        raise RuntimeError('Output-off register proof failed')
    return {f'0x{a:08X}':f'{v:08X}' for a,v in regs.items()}

class Console(Uart):
    READ=frozenset(('FW STATUS','ANALOG SAFE STATUS','STATUS','MOTOR TEST STATUS',
        'MOTOR TEST ZERO','MOTOR TEST PROTECTION','MOTOR TEST TIMING','MOTOR TEST FAULT','ADC TIMING'))
    def __init__(self,port):
        super().__init__(port); self.lines=[]; self.ends=self.starts=0
    def dispatch(self,line):
        if line: self.lines.append(line)
        super().dispatch(line)
        if line and any(x in line for x in ('BOOT HEALTH:','PROTECTED MOTOR','FAILED','HardFault','CREATE FAILED')):
            print(line,flush=True)
    def query(self,text,timeout=2):
        if text=='FW END':
            if self.ends: raise ValueError('Single FW END, never retry')
            self.ends+=1
        elif text=='MOTOR TEST SPEED':
            if self.starts: raise ValueError('One motion command, never retry')
            self.starts+=1
        elif text not in self.READ and text not in ('MOTOR TEST STOP','ANALOG SAFE'):
            raise ValueError('No generic motion/reset/fault-clear')
        self.request+=1; request=self.request
        self.port.write(f'{request} {text}\r\n'.encode('ascii'))
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            line=self.read_line(.02)
            if line is None: continue
            self.dispatch(line)
            if line.startswith(f'{request} '):
                if not line.startswith(f'{request} OK '): raise RuntimeError(line)
                return line
        raise TimeoutError('No ACK, never resend: '+text)

def stage_evidence(path,data,source_profile=None):
    # Historical evidence must keep its own pinned profile even when the
    # running acceptance selects a separately built timing-fix image.
    pinned=source_profile or profile
    path=path.resolve()
    if path.parent!=pinned.OUTPUT.resolve(): raise ValueError('Exact stage directory required')
    receipt=json.loads(path.read_text('utf-8'))
    if (receipt.get('pass_') is not True or receipt.get('mode')!='stage' or
        receipt.get('image_sha256')!=pinned.SHA or not receipt.get('all_bytes_outside_b_unchanged')):
        raise RuntimeError('Successful exact stage receipt required')
    paths=[Path(receipt[k+'_backup']).resolve() for k in ('before','staged')]
    if any(p.parent!=(pinned.OUTPUT/'private').resolve() for p in paths): raise ValueError('Private path mismatch')
    before,staged=(p.read_bytes() for p in paths)
    key=getattr(pinned,'BASELINE_KEY','recovered_baseline')
    generation=pinned.verified_baseline(before,receipt.get(key))
    if receipt.get('before_fw',{}).get('GEN') != str(generation):
        raise RuntimeError('Stage requester generation differs from verified baseline')
    compare_flash(before,staged,data,'B',staged=True)
    return before,staged

def prestart_resume_evidence(path,stage_path,staged):
    """Resume only interrupted confirmation observation, never a motor attempt."""
    path=path.resolve()
    if path.parent!=profile.OUTPUT.resolve(): raise ValueError('Exact trial directory required')
    r=json.loads(path.read_text('utf-8'))
    if (r.get('image_sha256')!=profile.SHA or
        Path(r.get('stage','')).resolve()!=stage_path.resolve() or
        r.get('host_motor_commands')!=0 or r.get('host_trial_commits')!=1 or
        r.get('failure')!='No ACK, never resend: MOTOR TEST STATUS' or
        r.get('start_ack') or r.get('confirmed') or
        not any('CONFIRM REQUESTED SLOT=B -> RESETTING' in line for line in r.get('uart',[]))):
        raise RuntimeError('Only confirmation-reset observation interruption before any motor command may resume')
    backup=Path(r.get('before_trial_backup','')).resolve()
    if backup.parent!=(profile.OUTPUT/'private').resolve() or backup.read_bytes()!=staged:
        raise RuntimeError('Interrupted preparation did not start from exact staged Flash')
    return r

def main():
    global profile
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--allow-trial-and-single-short-speed',action='store_true')
    parser.add_argument('--drive-12v-on-no-alarm',action='store_true')
    parser.add_argument('--resume-prestart',type=Path,
                        help='Exact receipt interrupted by automatic confirmation reset; zero motor commands only')
    parser.add_argument('--timing-fix',action='store_true',
                        help='Explicit exact ProtectedTimingFix B profile; old receipts cannot activate it')
    args=parser.parse_args()
    if not(args.allow_trial_and_single_short_speed and args.drive_12v_on_no_alarm):
        parser.error('User-authorized trial/one short test and powered state required')
    if args.timing_fix:
        import protected_timing_fix_stage as timing_profile
        profile=timing_profile
    data=profile.pinned_image(); before,staged=stage_evidence(args.stage,data)
    if args.resume_prestart: prestart_resume_evidence(args.resume_prestart,args.stage,staged)
    run=str(time.time_ns()); out=profile.OUTPUT/f'trial-{run}.json'
    row=dict(pass_=False,stage=str(args.stage),image_sha256=profile.SHA,steps=[],samples=[],
        force_confirmation=False,fault_clearing=False,automatic_host_retry=False,
        industrial_speed_qualified=False,torque_accuracy_verified=False)
    if args.resume_prestart: row['resumed_prestart']=str(args.resume_prestart.resolve())
    port=uart=None; activated=False
    def cli(*tokens):
        if not tokens or tokens[0] not in ('-u','-r32'): raise ValueError('Read-only probe only')
        p=subprocess.run([profile.CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+profile.SN,
            *map(str,tokens)],capture_output=True,text=True,errors='replace',timeout=30)
        output=p.stdout+p.stderr
        row['steps'].append(dict(args=list(map(str,tokens)),code=p.returncode,output=output))
        if p.returncode or 'Error:' in output: raise RuntimeError('Read-only probe failed')
        return output
    def capture(name):
        path=profile.OUTPUT/'private'/f'{run}-{name}.bin'; cli('-u','0x08000000','0x80000',path)
        row[name+'_backup']=str(path); raw=path.read_bytes()
        if len(raw)!=0x80000: raise RuntimeError('Incomplete Flash capture')
        return raw
    def registers(slot,trigger=None):
        return register_off(cli(*(v for a in profile.ADDRESSES for v in ('-r32',hex(a),'4'))),slot,trigger)
    try:
        current=capture('before_trial')
        if args.resume_prestart:
            compare_flash(before,current,data,'B',staged=False)
            row['before_outputs']=registers('B',True)
        else:
            if current!=staged: raise RuntimeError('Flash changed since stage')
            row['before_outputs']=registers('A',False)
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.01,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=Console(port)
        fw=uart.query('FW STATUS')
        # Current A is stopped; its staged transaction may reject non-FW queries.
        if args.resume_prestart:
            row['confirmed']=require_confirmed(fw,'B')
            protected_state(uart.query('MOTOR TEST STATUS'),ready=True)
            activated=True
        else:
            require_staged(fw,'0 OK SAFE SOURCE=SWD SD=0 MOE=0 CEN=0',data)
            if fields(fw).get('GEN')!=str(latest_meta(before)[5]):
                raise RuntimeError('Exact verified locked-A requester required')
            activated=True
            try: row['commit_ack']=uart.query('FW END',5)
            except TimeoutError: row['commit_ack_uncertain']=True
        end=time.monotonic()+90; saw_b=False
        while time.monotonic()<end:
            try: line=uart.query('FW STATUS',.5)
            except TimeoutError: continue
            f=fields(line)
            if f.get('CURRENT')=='B':
                saw_b=True
                try: boot_state=fields(uart.query('MOTOR TEST STATUS'))
                except TimeoutError:
                    # A successful health gate resets through the bootloader.
                    # Read-only queries can straddle that expected transition;
                    # keep observing, but never resend FW END or motion.
                    continue
                if boot_state.get('STATE')=='4':
                    row['startup_state']=boot_state
                    row['startup_zero']=fields(uart.query('MOTOR TEST ZERO'))
                    row['startup_fault']=fields(uart.query('MOTOR TEST FAULT'))
                    raise RuntimeError('Startup latched fault; no motor command')
            if saw_b and f.get('CURRENT')=='A' and f.get('PENDING')=='-':
                raise RuntimeError('Bootloader rolled back; no motor command')
            if (f.get('CURRENT')=='B' and f.get('CONFIRMED')=='B' and f.get('PENDING')=='-' and f.get('ACTIVE')=='0'):
                row['confirmed']=require_confirmed(line,'B'); break
            uart.poll(.1)
        else: raise TimeoutError('No normal B health confirmation; never force or retry')
        # A remains exact, and only bootloader-owned metadata may change.
        confirmed=capture('confirmed'); compare_flash(before,confirmed,data,'B',staged=False)
        row['before_start_outputs']=registers('B',True)
        row['before_state']=protected_state(uart.query('MOTOR TEST STATUS'),ready=True)
        row['zero']=fields(uart.query('MOTOR TEST ZERO'))
        row['before_protection']=protection(uart.query('MOTOR TEST PROTECTION'))
        row['before_timing']=timing(uart.query('MOTOR TEST TIMING'))
        row['before_motor_status']=uart.query('STATUS')
        if fields(row['before_motor_status']).get('FLT')!='0': raise RuntimeError('Motor task fault')
        print('READY PASS: normally confirmed B, fresh zero and protection; one 20 rpm/400 ms attempt',flush=True)
        row['start_ack']=uart.query('MOTOR TEST SPEED')
        if 'QUEUED=1 RPM=20 MAX_US=400000' not in row['start_ack']: raise RuntimeError('No bounded admission')
        end=time.monotonic()+1.0
        while time.monotonic()<end:
            state=fields(uart.query('MOTOR TEST STATUS'))
            row['samples'].append(dict(state=state,status=uart.query('STATUS')))
            if state.get('STATE') in ('3','4'): break
            uart.poll(.01)
        final=protected_state(uart.query('MOTOR TEST STATUS'))
        row['after_state']=final
        row['after_protection']=protection(uart.query('MOTOR TEST PROTECTION'))
        row['after_timing']=timing(uart.query('MOTOR TEST TIMING'))
        row['fault']=fields(uart.query('MOTOR TEST FAULT'))
        if (final.get('STATE')!='3' or final.get('USED')!='1' or final.get('QUEUED')!='0' or
            not 400000<=int(final.get('US','0'))<=400100):
            raise RuntimeError('Lease completion not proved')
        row['bounded_trial_completed_without_fault']=True
        # A completed lease is not proof of reaching speed; keep raw STATUS
        # observations for the result analysis instead of claiming accuracy.
        row['speed_accuracy_verified']=False
        row['pass_']=True
    except BaseException as error:
        row['failure']=str(error); raise
    finally:
        if uart and activated:
            try:
                f=fields(uart.query('FW STATUS'))
                row['final_fw']=f
                if f.get('CURRENT')=='B':
                    row['stop_ack']=uart.query('MOTOR TEST STOP')
                    row['final_state']=fields(uart.query('MOTOR TEST STATUS'))
                    row['final_fault']=fields(uart.query('MOTOR TEST FAULT'))
                row['maintenance_off']=uart.query('ANALOG SAFE')
                row['final_safe']=s=fields(uart.query('ANALOG SAFE STATUS'))
                if any(s.get(k)!=v for k,v in (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
                    raise RuntimeError('Final safe state missing')
                slot=f.get('CURRENT')
                if slot not in ('A','B'): raise RuntimeError('Unknown final slot')
                row['final_outputs']=registers(slot,False)
                raw=capture('final')
                if row.get('confirmed'): compare_flash(before,raw,data,'B',staged=False)
                row['final_outputs_off']=True
            except BaseException as error:
                row['pass_']=False; row['cleanup_failure']=str(error)
                print('STOP/READBACK FAILED: physically switch off 12 V; do not retry',flush=True)
        if uart:
            row['uart']=uart.lines; row['host_trial_commits']=uart.ends; row['host_motor_commands']=uart.starts
        if port: port.close()
        out.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(('SHORT TRIAL PASS' if row['pass_'] else 'SHORT TRIAL FAIL')+': not industrial speed/torque qualification',flush=True)
        print('Evidence: '+str(out),flush=True)

if __name__=='__main__': main()
