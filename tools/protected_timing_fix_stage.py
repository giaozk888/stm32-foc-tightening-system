"""Select the preserved hard-OFF A, then stage exact timing-fix B separately.

Physically OFF drive supply; no motor command, FW END, fault clearing or direct
metadata programming. BOOT A selects only the previously verified original A.
Each operation writes a private full-Flash capture and a public evidence receipt.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

import protected_closed_loop_stage as old
import protected_closed_loop_acceptance as acceptance
import control_chain_reconnect_acceptance as locked
from firmware_transfer_iap import stage, DEFAULT_CLIENT, fields, image_info
from zero_retest_deploy import latest_meta, compare_flash, require_confirmed

OUTPUT = old.OUTPUT
IMAGE = old.ROOT/'foc2_app_b/build/ProtectedTimingFix/foc2.bin'
SHA = 'a0c55c4dc76fbd240a02a33d34a17e8b5dd687c67c6d921600c5df10a221815e'
FAULT = OUTPUT/'trial-1791944717018072100.json'
BASELINE_KEY = 'selection_baseline'
CLI, SN, ADDRESSES = old.CLI, old.SN, old.ADDRESSES

def private_capture(receipt, key):
    path = Path(receipt[key+'_backup']).resolve()
    if path.parent != (OUTPUT/'private').resolve():
        raise RuntimeError('Private capture path mismatch')
    raw = path.read_bytes()
    if len(raw) != 0x80000: raise RuntimeError('Complete Flash capture required')
    return raw

def failed_evidence():
    r = json.loads(FAULT.read_text('utf-8'))
    if (r.get('pass_') is not False or r.get('image_sha256') != old.SHA or
        r.get('host_motor_commands') != 1 or not r.get('final_outputs_off') or
        r.get('cleanup_failure') or r.get('final_fault',{}).get('FLAGS') != '4'):
        raise RuntimeError('Exact fault-locked attempted-B receipt required')
    before, _ = acceptance.stage_evidence(Path(r['stage']), old.pinned_image(),source_profile=old)
    raw = private_capture(r,'final')
    compare_flash(before, raw, old.pinned_image(),'B')
    if latest_meta(raw)[2:6] != (2,0,0,473):
        raise RuntimeError('Exact confirmed failed B473 required')
    original = locked.image()
    if raw[0x8000:0x8000+len(original)] != original:
        raise RuntimeError('Preserved original hard-OFF A differs')
    return raw

def check_selected(raw, failed):
    if (len(raw) != 0x80000 or raw[:0x7E800] != failed[:0x7E800] or
        raw[0x7F800:] != failed[0x7F800:]):
        raise RuntimeError('Selection changed an APP/private region')
    prior, meta = latest_meta(failed), latest_meta(raw)
    if (meta[:2] != prior[:2] or meta[2:6] != (1,0,0,prior[5]+1) or
        meta[6:11] != prior[6:11]):
        raise RuntimeError('Not one normal selection of preserved A')
    return meta[5]

def verified_baseline(raw, selection):
    path = Path(selection).resolve()
    if path.parent != OUTPUT.resolve(): raise RuntimeError('Selection receipt path mismatch')
    r = json.loads(path.read_text('utf-8'))
    if (r.get('pass_') is not True or r.get('mode') != 'select-original-a' or
        r.get('boot_a_commands') != 1 or r.get('motor_commands') != 0 or
        not r.get('no_app_or_private_region_changes') or
        raw != private_capture(r,'selected')):
        raise RuntimeError('Exact successful original-A selection required')
    return check_selected(raw, failed_evidence())

def pinned_image():
    raw = IMAGE.read_bytes()
    if len(raw) != 205200 or hashlib.sha256(raw).hexdigest() != SHA or image_info(raw)[0] != 'B':
        raise RuntimeError('Exact offline-tested timing-fix B required')
    for marker in (b'OK MOTOR TEST QUEUED=1 RPM=20 MAX_US=400000',
                   b'QUALIFIED=0',b'LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000',
                   b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000'):
        if marker not in raw: raise RuntimeError('Protection marker missing')
    return raw

class SelectionConsole(acceptance.Console):
    def __init__(self, port):
        super().__init__(port); self.selections=0
    def query(self, text, timeout=2):
        if text != 'BOOT A':
            if text not in self.READ and text != 'ANALOG SAFE':
                raise ValueError('No activation, motion or fault clearing during selection')
            return super().query(text,timeout)
        if self.selections: raise ValueError('One BOOT A only; never resend')
        self.selections += 1
        self.request += 1; request=self.request
        self.port.write(f'{request} BOOT A\r\n'.encode('ascii'))
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            line=self.read_line(.02)
            if line is None: continue
            self.dispatch(line)
            if line.startswith(f'{request} '):
                if line != f'{request} OK BOOT SLOT=A REQUESTED RESETTING':
                    raise RuntimeError('Unexpected selection ACK: '+line)
                return line
        raise TimeoutError('BOOT A outcome unknown; never resend')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    modes=p.add_mutually_exclusive_group(required=True)
    modes.add_argument('--select-original-a',action='store_true')
    modes.add_argument('--stage-from-selection',type=Path)
    p.add_argument('--drive-12v-off',action='store_true')
    p.add_argument('--allow-inactive-stage-and-selection',action='store_true')
    args=p.parse_args()
    if not(args.drive_12v_off and args.allow_inactive_stage_and_selection):
        p.error('Off supply and scoped deployment/selection authorization required')
    failed=failed_evidence(); data=pinned_image()
    run=str(time.time_ns()); mode='select-original-a' if args.select_original_a else 'stage'
    receipt=OUTPUT/f'timing-{mode}-{run}.json'
    row=dict(pass_=False,mode=mode,image_sha256=SHA,image_bytes=len(data),
        motor_commands=0,activation=False,steps=[],drive_12v_off_user_confirmed=True)
    port=uart=None
    def cli(*tokens):
        if not tokens or tokens[0] not in ('-u','-r32'): raise ValueError('Read-only SWD only')
        result=subprocess.run([old.CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+old.SN,
            *map(str,tokens)],capture_output=True,text=True,errors='replace',timeout=30)
        output=result.stdout+result.stderr
        row['steps'].append(dict(args=list(map(str,tokens)),code=result.returncode,output=output))
        if result.returncode or 'Error:' in output: raise RuntimeError('Probe failed; no retry/reset')
        return output
    def capture(name):
        path=OUTPUT/'private'/f'{run}-timing-{name}.bin'
        cli('-u','0x08000000','0x80000',path)
        row[name+'_backup']=str(path); raw=path.read_bytes()
        if len(raw)!=0x80000: raise RuntimeError('Full Flash required')
        return raw
    def outputs(slot):
        return acceptance.register_off(cli(*(v for a in old.ADDRESSES for v in ('-r32',hex(a),'4'))),slot,False)
    try:
        before=capture('before')
        if args.select_original_a:
            if before != failed: raise RuntimeError('Current Flash differs from exact fault capture')
            row['before_outputs']=outputs('B')
        else:
            generation=verified_baseline(before,args.stage_from_selection)
            row['selection_baseline']=str(args.stage_from_selection.resolve())
            row['before_outputs']=outputs('A')
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open()
        if args.select_original_a:
            uart=SelectionConsole(port)
            row['before_fw']=require_confirmed(uart.query('FW STATUS'),'B')
            state=fields(uart.query('MOTOR TEST STATUS'))
            if any(state.get(k)!=v for k,v in (('STATE','4'),('USED','1'),('ARMED','0'),
                ('FLAGS','4'),('FAULT','1'),('SD','0'),('MOE','0'),('CCER','0'))):
                raise RuntimeError('Not the expected locked fault; no selection')
            row['fault_state']=state
            row['boot_a_commands']=1
            row['selection_ack']=uart.query('BOOT A',5)
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                try: line=uart.query('FW STATUS',.5)
                except TimeoutError: continue
                if fields(line).get('CURRENT')=='A':
                    row['fw']=require_confirmed(line,'A'); break
            else: raise TimeoutError('Preserved A unavailable; never resend selection')
            row['safe_ack']=uart.query('ANALOG SAFE')
            safe=fields(uart.query('ANALOG SAFE STATUS')); row['safe']=safe
            if any(safe.get(k)!=v for k,v in (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
                raise RuntimeError('Original A is not locked off')
            selected=capture('selected'); generation=check_selected(selected,failed)
            if row['fw'].get('GEN')!=str(generation): raise RuntimeError('UART/Flash generation mismatch')
            row['no_app_or_private_region_changes']=True
        else:
            uart=old.Console(port)
            row['before_fw']=require_confirmed(uart.command('FW STATUS'),'A')
            if row['before_fw'].get('GEN')!=str(generation): raise RuntimeError('Generation mismatch')
            row['before_bench']=old.require_stopped(uart.command('BENCH STATUS'))
            stage(uart,IMAGE,DEFAULT_CLIENT,allow_reset=False)
            row['after_fw']=fw=fields(uart.command('FW STATUS'))
            if any(fw.get(k)!=v for k,v in (('CURRENT','A'),('CONFIRMED','A'),('GEN',str(generation)),
                ('PENDING','-'),('TARGET','B'),('ACTIVE','1'),('RX',str(len(data))))):
                raise RuntimeError('Unexpected staging state')
            actual=capture('staged'); compare_flash(before,actual,data,'B',staged=True)
            if actual[:0x40000]!=before[:0x40000] or actual[0x78000:]!=before[0x78000:]:
                raise RuntimeError('Bytes outside B changed')
            row['all_bytes_outside_b_unchanged']=True
        row['final_outputs']=outputs('A'); row['pass_']=True
    except BaseException as error:
        row['failure']=str(error); raise
    finally:
        if uart: row['uart']=uart.lines
        if port: port.close()
        receipt.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(('PASS' if row['pass_'] else 'FAIL')+': '+mode+'; no motor command or new-image activation',flush=True)
        print('Evidence: '+str(receipt),flush=True)

if __name__=='__main__': main()
