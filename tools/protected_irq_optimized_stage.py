"""Exact optimized B staging from preserved A; no FW END or motion command.

Select only the verified original hard-off A from the exact B477 fault receipt.
Full Flash captures stay in the existing restricted private directory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import protected_timing_fix_stage as previous
import protected_closed_loop_acceptance as acceptance
from firmware_transfer_iap import ROOT, stage, DEFAULT_CLIENT, fields, image_info
from zero_retest_deploy import latest_meta, compare_flash, require_confirmed

OUTPUT=previous.OUTPUT
IMAGE=ROOT/'foc2_app_b/build/ProtectedIrqOptimized/foc2.bin'
SHA='bbfe7b3df6c721792e5b01ac694c19ab7bc9af54fedc2d43ec9f47342e741758'
FAULT=OUTPUT/'trial-1791946470411344800.json'
BASELINE_KEY='selection_baseline'
ROLLBACK=OUTPUT/'irq-rollback-1791949754896383300.json'
COMPUTE_FAILURE=OUTPUT/'irq-compute-1791949547413268000.json'
CLI,SN,ADDRESSES=previous.CLI,previous.SN,previous.ADDRESSES

def pinned_image():
    data=IMAGE.read_bytes()
    if len(data)!=205592 or hashlib.sha256(data).hexdigest()!=SHA or image_info(data)[0]!='B':
        raise RuntimeError('Exact offline-tested optimized B required')
    for marker in (b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000',
                   b'LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000',b'QUALIFIED=0'):
        if marker not in data: raise RuntimeError('Protection marker missing')
    return data

def failed_evidence():
    r=json.loads(FAULT.read_text('utf-8'))
    if (r.get('pass_') is not False or r.get('image_sha256')!=previous.SHA or
        r.get('host_motor_commands')!=1 or r.get('host_trial_commits')!=1 or
        not r.get('final_outputs_off') or r.get('cleanup_failure') or
        r.get('final_fault',{}).get('FLAGS')!='4'):
        raise RuntimeError('Exact failed B477 receipt required')
    prior,_=acceptance.stage_evidence(Path(r['stage']),previous.pinned_image(),source_profile=previous)
    raw=previous.private_capture(r,'final')
    compare_flash(prior,raw,previous.pinned_image(),'B')
    if latest_meta(raw)[2:6]!=(2,0,0,477): raise RuntimeError('Exact confirmed B477 required')
    original=previous.locked.image()
    if raw[0x8000:0x8000+len(original)]!=original: raise RuntimeError('Original fallback A changed')
    return raw

def verified_baseline(raw,selection):
    path=Path(selection).resolve()
    if path.parent!=OUTPUT.resolve(): raise RuntimeError('Selection receipt directory mismatch')
    if path==ROLLBACK.resolve():
        r=json.loads(path.read_text('utf-8'))
        if (r.get('pass_') is not True or Path(r.get('failure_receipt','')).resolve()!=COMPUTE_FAILURE.resolve() or
            r.get('motor_commands')!=0 or r.get('resets')!=0 or
            not r.get('all_app_and_private_bytes_unchanged') or
            not r.get('failed_b_not_bootable_without_new_staging') or
            r.get('fw',{}).get('GEN')!='482' or raw!=previous.private_capture(r,'rollback')):
            raise RuntimeError('Exact automatically rolled-back A482 required')
        failed=json.loads(COMPUTE_FAILURE.read_text('utf-8'))
        if (failed.get('pass_') is not False or failed.get('image_sha256')!=SHA or
            failed.get('host_trial_commits')!=1 or failed.get('host_motor_commands')!=0 or
            not failed.get('final_outputs_off') or failed.get('cleanup_failure')):
            raise RuntimeError('Exact stopped compute-only trial required')
        _,staged=acceptance.stage_evidence(Path(failed['stage']),pinned_image(),source_profile=sys.modules[__name__])
        if (raw[:0x7E800]!=staged[:0x7E800] or raw[0x7F800:]!=staged[0x7F800:] or
            latest_meta(raw)[2:6]!=(1,0,0,482) or latest_meta(raw)[8:10]!=(0,0)):
            raise RuntimeError('Rolled-back application/private region or metadata differs')
        return 482
    r=json.loads(path.read_text('utf-8'))
    if (r.get('pass_') is not True or r.get('mode')!='select-original-a' or
        r.get('image_sha256')!=SHA or r.get('boot_a_commands')!=1 or
        r.get('motor_commands')!=0 or not r.get('no_app_or_private_region_changes') or
        raw!=previous.private_capture(r,'selected')):
        raise RuntimeError('Exact optimized-profile A selection required')
    return previous.check_selected(raw,failed_evidence())

class Board:
    def __init__(self,row,run): self.row,self.run=row,run
    def cli(self,*tokens):
        if not tokens or tokens[0] not in ('-u','-r32'): raise ValueError('Read-only SWD only')
        p=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,
                          *map(str,tokens)],capture_output=True,text=True,errors='replace',timeout=30)
        out=p.stdout+p.stderr
        self.row['steps'].append(dict(args=list(map(str,tokens)),code=p.returncode,output=out))
        if p.returncode or 'Error:' in out: raise RuntimeError('Probe failure; no retry/reset')
        return out
    def capture(self,name):
        path=OUTPUT/'private'/f'{self.run}-irq-{name}.bin'
        self.cli('-u','0x08000000','0x80000',path)
        raw=path.read_bytes()
        if len(raw)!=0x80000: raise RuntimeError('Full Flash capture required')
        self.row[name+'_backup']=str(path)
        return raw
    def outputs(self,slot,trigger=None):
        return acceptance.register_off(self.cli(*(v for a in ADDRESSES for v in ('-r32',hex(a),'4'))),slot,trigger)

def open_port():
    import serial
    port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
    port.dtr=port.rts=False; port.port='COM5'; port.open()
    return port

def reset_after_rejected_selection(board, uart, rejected, failed):
    """One physically-off reset, only after the recorded stale-speed refusal."""
    path=Path(rejected).resolve()
    if path.parent!=OUTPUT.resolve(): raise RuntimeError('Refusal receipt directory mismatch')
    r=json.loads(path.read_text('utf-8'))
    if (r.get('pass_') is not False or r.get('mode')!='select-original-a' or
        r.get('image_sha256')!=SHA or r.get('motor_commands')!=0 or
        r.get('boot_a_commands')!=1 or r.get('selection_ack') or
        r.get('failure')!='Unexpected selection ACK: 15003 ERR 106 ROTOR_MOVING' or
        previous.private_capture(r,'before')!=failed):
        raise RuntimeError('Exact rejected stale-speed selection required')
    board.row['rejected_selection']=str(path)
    board.row['off_supply_resets']=1
    result=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,'-rst'],
                          capture_output=True,text=True,errors='replace',timeout=30)
    output=result.stdout+result.stderr
    board.row['steps'].append(dict(args=['-rst'],code=result.returncode,output=output))
    if result.returncode or 'Error:' in output: raise RuntimeError('Reset failed; never retry')
    deadline=time.monotonic()+35
    while time.monotonic()<deadline:
        try: line=uart.query('FW STATUS',.5)
        except TimeoutError: continue
        board.row['reset_fw']=f=require_confirmed(line,'B')
        if f.get('GEN')!='477': raise RuntimeError('Reset changed confirmed generation')
        break
    else: raise TimeoutError('No console after reset; no further operation')
    board.row['reset_safe_ack']=uart.query('ANALOG SAFE')
    board.row['reset_state']=s=fields(uart.query('MOTOR TEST STATUS'))
    if any(s.get(k)!=v for k,v in (('ARMED','0'),('SD','0'),('MOE','0'),('CCER','0'))):
        raise RuntimeError('Reset did not leave output locked')
    board.row['reset_status']=uart.query('STATUS')
    # A fresh reset never authorizes movement or an interlock override. BOOT A
    # below still executes the firmware's normal idle/rotation safety gates.
    board.row['reset_outputs']=board.outputs('B',False)
    if board.capture('reset')!=failed: raise RuntimeError('Reset changed Flash; stop')
    board.row['reset_all_flash_unchanged']=True

def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--select-original-a',action='store_true')
    mode.add_argument('--stage-from-selection',type=Path)
    p.add_argument('--drive-12v-off',action='store_true')
    p.add_argument('--allow-inactive-stage-and-selection',action='store_true')
    p.add_argument('--after-rejected-selection',type=Path,
                   help='Exact refusal receipt; one off-supply normal reset, no interlock override')
    args=p.parse_args()
    if not(args.drive_12v_off and args.allow_inactive_stage_and_selection):
        p.error('Physically off drive supply and scoped staging/selection authorization required')
    if args.after_rejected_selection and not args.select_original_a:
        p.error('Reset recovery belongs only to original-A selection')
    failed=failed_evidence(); data=pinned_image()
    run=str(time.time_ns()); operation='select-original-a' if args.select_original_a else 'stage'
    out=OUTPUT/f'irq-{operation}-{run}.json'
    row=dict(pass_=False,mode=operation,image_sha256=SHA,image_bytes=len(data),
             motor_commands=0,activation=False,steps=[],drive_12v_off_user_confirmed=True)
    board=Board(row,run); port=uart=None
    try:
        before=board.capture('before')
        if args.select_original_a:
            if before!=failed: raise RuntimeError('Current Flash differs from B477 fault capture')
            row['before_outputs']=board.outputs('B',False)
            port=open_port(); uart=previous.SelectionConsole(port)
            row['before_fw']=require_confirmed(uart.query('FW STATUS'),'B')
            s=fields(uart.query('MOTOR TEST STATUS'))
            if any(s.get(k)!=v for k,v in (('STATE','4'),('USED','1'),('ARMED','0'),
                      ('FLAGS','4'),('FAULT','1'),('SD','0'),('MOE','0'),('CCER','0'))):
                raise RuntimeError('Not expected fault-locked B477')
            if args.after_rejected_selection:
                reset_after_rejected_selection(board,uart,args.after_rejected_selection,failed)
            row['boot_a_commands']=1; row['selection_ack']=uart.query('BOOT A',5)
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                try: line=uart.query('FW STATUS',.5)
                except TimeoutError: continue
                if fields(line).get('CURRENT')=='A':
                    row['fw']=require_confirmed(line,'A'); break
            else: raise TimeoutError('Original A unavailable; never resend BOOT A')
            row['safe_ack']=uart.query('ANALOG SAFE')
            row['safe']=s=fields(uart.query('ANALOG SAFE STATUS'))
            if any(s.get(k)!=v for k,v in (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
                raise RuntimeError('Original A not maintenance locked')
            selected=board.capture('selected'); generation=previous.check_selected(selected,failed)
            if row['fw'].get('GEN')!=str(generation): raise RuntimeError('UART/Flash generation differs')
            row['no_app_or_private_region_changes']=True
        else:
            generation=verified_baseline(before,args.stage_from_selection)
            row['selection_baseline']=str(args.stage_from_selection.resolve())
            row['before_outputs']=board.outputs('A',False)
            port=open_port(); uart=previous.old.Console(port)
            row['before_fw']=require_confirmed(uart.command('FW STATUS'),'A')
            if row['before_fw'].get('GEN')!=str(generation): raise RuntimeError('Generation differs')
            row['before_bench']=previous.old.require_stopped(uart.command('BENCH STATUS'))
            stage(uart,IMAGE,DEFAULT_CLIENT,allow_reset=False)
            row['after_fw']=fw=fields(uart.command('FW STATUS'))
            if any(fw.get(k)!=v for k,v in (('CURRENT','A'),('CONFIRMED','A'),('GEN',str(generation)),
                     ('PENDING','-'),('TARGET','B'),('ACTIVE','1'),('RX',str(len(data))))):
                raise RuntimeError('Staging state differs')
            actual=board.capture('staged'); compare_flash(before,actual,data,'B',staged=True)
            if actual[:0x40000]!=before[:0x40000] or actual[0x78000:]!=before[0x78000:]:
                raise RuntimeError('Bytes outside B changed')
            row['all_bytes_outside_b_unchanged']=True
        row['final_outputs']=board.outputs('A',False); row['pass_']=True
    except BaseException as error:
        row['failure']=str(error); raise
    finally:
        if uart: row['uart']=uart.lines
        if port: port.close()
        out.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(('PASS' if row['pass_'] else 'FAIL')+': '+operation+'; no motion/new-image activation',flush=True)
        print('Evidence: '+str(out),flush=True)

if __name__=='__main__': main()
