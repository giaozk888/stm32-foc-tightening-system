"""Bounded normal bootloader rollback of the exact failed initial B to locked A.

Drive supply OFF. No APP/metadata/mailbox programming, confirmation override,
motor command or fault clearing. At most two resets consume the existing trial
and roll back; no new trial is requested. Preserve private full Flash evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import zlib

from firmware_transfer_iap import fields
import control_chain_reconnect_acceptance as locked
from control_chain_timeout_acceptance import verified_baseline as original_baseline
from zero_retest_deploy import latest_meta
from protected_closed_loop_acceptance import Console, register_off

OUTPUT = locked.ROOT/'safety_backups/protected-closed-loop-20261014'
INITIAL = OUTPUT/'stage-1791942124393828900.json'
INITIAL_SHA = '7c9489418d8a28c6fbd3a52e519e3bca80cf1242477fb75369d3ccb29933101c'

def initial_evidence():
    r = json.loads(INITIAL.read_text('utf-8'))
    if not r.get('pass_') or r.get('image_sha256') != INITIAL_SHA:
        raise RuntimeError('Pinned initial successful stage required')
    paths = [Path(r[k+'_backup']).resolve() for k in ('before','staged')]
    if any(p.parent != (OUTPUT/'private').resolve() for p in paths):
        raise RuntimeError('Initial private paths mismatch')
    before, staged = (p.read_bytes() for p in paths)
    original_baseline(before)
    image = (OUTPUT/'initial-trial-image/foc2.bin').read_bytes()
    if len(image) != 204936 or hashlib.sha256(image).hexdigest() != INITIAL_SHA:
        raise RuntimeError('Exact initial failed image required')
    if staged[:0x40000] != before[:0x40000] or staged[0x78000:] != before[0x78000:]:
        raise RuntimeError('Initial stage protected bytes changed')
    if staged[0x40000:0x40000+len(image)] != image:
        raise RuntimeError('Initial stage image mismatch')
    return before, staged, image

def check_failed_chain(raw, before, staged, image, recovered=False):
    if len(raw) != 0x80000 or raw[:0x7E800] != staged[:0x7E800] or raw[0x7F800:] != staged[0x7F800:]:
        raise RuntimeError('Bytes outside bootloader metadata changed')
    old, meta = latest_meta(before), latest_meta(raw)
    # Boot_CommitPendingClearV3(..., invalidate_pending=1) deliberately
    # invalidates the failed slot metadata while preserving its Flash bytes.
    expected_b=(0,0) if recovered else (len(image),zlib.crc32(image))
    if (meta[2] != 1 or meta[6:8] != old[6:8] or
        meta[8:10] != expected_b or
        not old[5]+2 <= meta[5] <= old[5]+4):
        raise RuntimeError('Unexpected failed-trial metadata chain')
    if recovered:
        if meta[3:5] != (0,0): raise RuntimeError('Rollback not durably completed')
    elif meta[3] != 2 or meta[4] not in (0,1):
        raise RuntimeError('Only existing failed B trial may be consumed')
    return meta

def verified_recovery(raw, receipt_path):
    path = Path(receipt_path).resolve()
    if path.parent != OUTPUT.resolve(): raise RuntimeError('Recovery receipt location mismatch')
    r = json.loads(path.read_text('utf-8'))
    if (r.get('pass_') is not True or r.get('mode') != 'rollback' or
        not r.get('no_app_or_private_region_changes') or r.get('resets',99) > 2):
        raise RuntimeError('Completed bounded rollback receipt required')
    backup = Path(r['recovered_backup']).resolve()
    if backup.parent != (OUTPUT/'private').resolve() or raw != backup.read_bytes():
        raise RuntimeError('Not exact recovered Flash')
    before, staged, image = initial_evidence()
    meta = check_failed_chain(raw,before,staged,image,recovered=True)
    if r.get('fw',{}).get('GEN') != str(meta[5]):
        raise RuntimeError('Recovery generation mismatch')
    return meta[5]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--allow-bounded-rollback',action='store_true')
    p.add_argument('--drive-12v-off',action='store_true')
    p.add_argument('--verify-completed-rollback',type=Path,
                   help='Read-only completion of a captured rollback; no further reset')
    args=p.parse_args()
    if not(args.allow_bounded_rollback and args.drive_12v_off):
        p.error('Authorized rollback and physically off drive supply required')
    before, staged, image = initial_evidence()
    run=str(time.time_ns()); receipt=OUTPUT/f'rollback-{run}.json'
    row=dict(pass_=False,mode='rollback',resets=0,motor_commands=0,
        direct_metadata_write=False,force_confirm=False,drive_12v_off_user_confirmed=True,steps=[])
    port=uart=None
    def cli(*tokens):
        if tokens == ('-rst',):
            if row['resets'] >= 2: raise RuntimeError('Reset budget exhausted')
            row['resets'] += 1
        elif not tokens or tokens[0] not in ('-u','-r32'):
            raise ValueError('Read-only SWD or bounded existing-trial reset only')
        result=subprocess.run([locked.CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+locked.SN,
            *map(str,tokens)],capture_output=True,text=True,errors='replace',timeout=30)
        out=result.stdout+result.stderr
        row['steps'].append(dict(args=list(map(str,tokens)),code=result.returncode,output=out))
        if result.returncode or 'Error:' in out: raise RuntimeError('Probe failed; no blind retry')
        return out
    def capture(name):
        path=OUTPUT/'private'/f'{run}-{name}.bin'
        cli('-u','0x08000000','0x80000',path)
        raw=path.read_bytes();row[name+'_backup']=str(path)
        return raw
    def outputs(slot):
        return register_off(cli(*(v for a in locked.ADDRESSES for v in ('-r32',hex(a),'4'))),slot,False)
    try:
        raw=capture('failed')
        if args.verify_completed_rollback:
            prior_path=args.verify_completed_rollback.resolve()
            if prior_path.parent != OUTPUT.resolve(): raise RuntimeError('Prior receipt location mismatch')
            prior=json.loads(prior_path.read_text('utf-8'))
            prior_capture=Path(prior.get('reset2_backup','')).resolve()
            if (prior.get('mode')!='rollback' or prior.get('resets')!=2 or
                prior_capture.parent!=(OUTPUT/'private').resolve() or raw!=prior_capture.read_bytes()):
                raise RuntimeError('Exact already-completed rollback capture required')
            meta=check_failed_chain(raw,before,staged,image,recovered=True)
            row['previous_rollback']=str(prior_path)
            row['failed_outputs']=outputs('A')
        else:
            meta=check_failed_chain(raw,before,staged,image)
            row['failed_outputs']=outputs('B')
        row['failed_meta']=list(meta)
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False;port.port='COM5';port.open();uart=Console(port)
        while meta[3]:
            cli('-rst')
            # Let existing bootloader CRC/metadata transaction complete, without
            # issuing activation or motion. A failed B has no automatic start.
            deadline=time.monotonic()+8
            while time.monotonic()<deadline: uart.poll(.05)
            raw=capture('reset'+str(row['resets']))
            done=latest_meta(raw)[3:5]==(0,0)
            meta=check_failed_chain(raw,before,staged,image,recovered=done)
            row.setdefault('reset_meta',[]).append(list(meta))
            if done: break
            row['pending_outputs']=outputs('B')
        row['recovered_outputs']=outputs('A')
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            try:
                fw=locked.require_confirmed(uart.query('FW STATUS',.5),'A')
                if fw.get('GEN') != str(meta[5]): raise RuntimeError('UART/Flash generation mismatch')
                row['fw']=fw;break
            except TimeoutError: continue
        else: raise TimeoutError('Locked A console unavailable; do not flash')
        row['safe_ack']=uart.query('ANALOG SAFE')
        row['safe']=safe=fields(uart.query('ANALOG SAFE STATUS'))
        if any(safe.get(k)!=v for k,v in (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
            raise RuntimeError('Locked A latch not established')
        raw=capture('recovered');check_failed_chain(raw,before,staged,image,recovered=True)
        row['final_outputs']=outputs('A')
        row['no_app_or_private_region_changes']=True;row['pass_']=True
    except BaseException as error:
        row['failure']=str(error);raise
    finally:
        if uart: row['uart']=uart.lines
        if port: port.close()
        receipt.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(('ROLLBACK PASS' if row['pass_'] else 'ROLLBACK FAIL')+': no image/metadata programming or motor command',flush=True)
        print('Evidence: '+str(receipt),flush=True)

if __name__=='__main__':main()
