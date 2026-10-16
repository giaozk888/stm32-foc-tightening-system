"""Exact protected compact A from confirmed locked B533; stage ONLY.

No FW END, activation, reset, motion, clearing or baseline selection. Full
captures remain in the existing private ACL directory and are not printed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import protected_irq_compact_stage as previous
from protected_irq_dma_trace_stage import StageConsole
from firmware_transfer_iap import ROOT, image_info, stage, DEFAULT_CLIENT, fields
from zero_retest_deploy import latest_meta, compare_flash, require_confirmed

OUTPUT=previous.OUTPUT
IMAGE=ROOT/'foc2_app_a/build/ProtectedCompactClosedLoop/foc2.bin'
SHA='493ff25e02feacd886f8f97f2eb91c7b64338fdea3cb517313035f3e6f52b875'
ORIGINAL=OUTPUT/'irq-compute-1792043572006064700.json'
GENERATION=533
Board,open_port=previous.Board,previous.open_port

def pinned_image():
    data=IMAGE.read_bytes()
    if len(data)!=207972 or hashlib.sha256(data).hexdigest()!=SHA or image_info(data)[0]!='A':
        raise RuntimeError('Exact offline-tested protected compact A required')
    for marker in (b'NAME=COMPACT_CLOSED_LOOP HARD_OFF=0 ADAPT=0 ZERO=BOUNDED',
        b'LOCAL=1 RPM=20 LEASE_US=400000 QUALIFIED=0',
        b'MOTOR TEST RAM ENABLED=1 HARD_OFF=0 DEADLINE_US=50',
        b'MOTOR TEST COMPACT ENABLED=1 HARD_OFF=0 FIXED_OPS=1 GUARD_US=25 DEADLINE_US=50',
        b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000',
        b'LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000',
        b'BUDGET=6 STREAK=4',b'OK MOTOR TEST QUEUED=1 RPM=20 MAX_US=400000'):
        if marker not in data: raise RuntimeError('Protected compact identity/protection absent')
    if b'HARD_OFF=1' in data or b'MAX=OFF SEG_MAX=OFF' in data:
        raise RuntimeError('Experiment or no-quota image cannot be used for motor profile')
    return data

def verified_baseline(raw, evidence=ORIGINAL):
    path=Path(evidence).resolve()
    if path!=ORIGINAL.resolve(): raise RuntimeError('Exact successful B533 compute receipt required')
    r=json.loads(path.read_text('utf-8'))
    if (r.get('pass_') is not True or r.get('image_sha256')!=previous.SHA or
        r.get('host_trial_commits')!=1 or r.get('host_motor_commands')!=0 or
        r.get('final_outputs_off') is not True or r.get('cleanup_failure') or
        r.get('final_fw',{}).get('GEN')!=str(GENERATION) or
        r.get('final_fw',{}).get('CURRENT')!='B' or
        r.get('protected_regions',{}).get('all_protected_regions_unchanged') is not True or
        any(r.get('final_safe',{}).get(k)!=v for k,v in
            (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0')))):
        raise RuntimeError('Successful locked B533 receipt invalid')
    backup=Path(r.get('final_backup','')).resolve()
    if backup.parent!=(OUTPUT/'private').resolve():
        raise RuntimeError('Baseline backup path differs from private directory')
    if len(raw)!=0x80000 or raw!=backup.read_bytes() or latest_meta(raw)[2:6]!=(2,0,0,GENERATION):
        raise RuntimeError('Current complete Flash differs from proved B533')
    # Also verify the exact fallback BIN, not only the receipt or metadata.
    fallback=previous.pinned_image()
    if raw[0x40000:0x40000+len(fallback)]!=fallback:
        raise RuntimeError('B533 fallback image mismatch')
    return GENERATION

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--drive-12v-off',action='store_true')
    p.add_argument('--motor-leads-disconnected',action='store_true')
    p.add_argument('--allow-inactive-stage',action='store_true')
    args=p.parse_args()
    if not(args.drive_12v_off and args.motor_leads_disconnected and args.allow_inactive_stage):
        p.error('Drive off, motor disconnected and scoped inactive-stage authorization required')
    data=pinned_image()
    run=str(time.time_ns()); out=OUTPUT/f'compact-closed-loop-stage-{run}.json'
    row=dict(pass_=False,mode='stage',target_slot='A',fallback_slot='B',
        image_sha256=SHA,image_bytes=len(data),baseline_receipt=str(ORIGINAL.resolve()),
        motor_commands=0,resets=0,activation=False,steps=[],drive_12v_off_user_confirmed=True)
    board=Board(row,run); port=uart=None
    try:
        before=board.capture('before'); verified_baseline(before)
        row['before_outputs']=board.outputs('B',False)
        port=open_port(); uart=StageConsole(port)
        row['before_fw']=require_confirmed(uart.query('FW STATUS'),'B')
        if row['before_fw'].get('GEN')!=str(GENERATION):
            raise RuntimeError('UART/Flash generation differs')
        status=fields(uart.query('STATUS'))
        if status.get('FLT')!='0' or status.get('MODE')!='IDLE':
            raise RuntimeError('B fault or non-idle mode; no staging')
        safe=fields(uart.query('ANALOG SAFE STATUS'))
        if any(safe.get(k)!=v for k,v in (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
            raise RuntimeError('B maintenance lock absent')
        stage(uart,IMAGE,DEFAULT_CLIENT,allow_reset=False)
        row['after_fw']=fw=fields(uart.query('FW STATUS'))
        if any(fw.get(k)!=v for k,v in (('CURRENT','B'),('CONFIRMED','B'),
                ('GEN',str(GENERATION)),('PENDING','-'),('TARGET','A'),
                ('ACTIVE','1'),('RX',str(len(data))))):
            raise RuntimeError('Staged A metadata differs')
        actual=board.capture('staged')
        row['protected_regions']=compare_flash(before,actual,data,'A',staged=True)
        if actual[:0x8000]!=before[:0x8000] or actual[0x40000:]!=before[0x40000:]:
            raise RuntimeError('Bytes outside A changed')
        row['all_bytes_outside_a_unchanged']=True
        row['final_outputs']=board.outputs('B',False)
        row['pass_']=True
    except BaseException as error:
        row['failure']=str(error); raise
    finally:
        if uart: row['uart']=uart.lines
        if port: port.close()
        out.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(('PASS' if row['pass_'] else 'FAIL')+': pinned inactive A stage; no activation',flush=True)
        print('Evidence: '+str(out),flush=True)

if __name__=='__main__': main()
