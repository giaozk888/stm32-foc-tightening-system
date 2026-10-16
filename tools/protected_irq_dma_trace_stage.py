"""Stage the exact DMA-timeout trace image in inactive B; never activate it.

The only accepted baseline is the automatic A486 rollback from the one
compute-only attempt that recorded a 200 us encoder transaction timeout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import sys

import protected_irq_optimized_stage as old
import protected_closed_loop_acceptance as acceptance
from firmware_transfer_iap import DEFAULT_CLIENT, fields, image_info, stage
from zero_retest_deploy import compare_flash, latest_meta, require_confirmed

OUTPUT=old.OUTPUT
IMAGE=old.ROOT/'foc2_app_b/build/ProtectedIrqDmaTrace/foc2.bin'
SHA='b348f3a24d1d215160e6edf9575410060c401eb6775924fa3bfcc3735ff19ee4'
FAILURE=OUTPUT/'irq-compute-1791958211358269600.json'
BASELINE_KEY='rollback_evidence'
Board=old.Board
open_port=old.open_port


def pinned_image():
    raw=IMAGE.read_bytes()
    if len(raw)!=206224 or hashlib.sha256(raw).hexdigest()!=SHA or image_info(raw)[0]!='B':
        raise RuntimeError('Exact offline-tested DMA trace B required')
    for marker in (b'ENC SNAP VALID=',b'ENC DMAHW ISR=',
                   b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000',
                   b'LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000'):
        if marker not in raw: raise RuntimeError('Trace or protection marker missing')
    return raw


def verified_baseline(raw,evidence):
    path=Path(evidence).resolve()
    if path!=FAILURE.resolve(): raise RuntimeError('Exact prior timeout failure required')
    failed=json.loads(path.read_text('utf-8'))
    if (failed.get('pass_') is not False or failed.get('image_sha256')!=old.SHA or
        failed.get('host_trial_commits')!=1 or failed.get('host_motor_commands')!=0 or
        failed.get('failure')!='Startup fault; no reset/activation retry' or
        failed.get('startup_encoder_dma',{}).get('TIMEOUT')!='1' or
        failed.get('startup_encoder_dma',{}).get('ST')!='2' or
        not failed.get('final_outputs_off') or failed.get('cleanup_failure')):
        raise RuntimeError('Prior exact timeout receipt invalid')
    staged_before=old.previous.private_capture(failed,'before_trial')
    if (raw[:0x7E800]!=staged_before[:0x7E800] or
        raw[0x7F800:]!=staged_before[0x7F800:] or
        latest_meta(raw)[2:6]!=(1,0,0,486) or latest_meta(raw)[8:10]!=(0,0)):
        raise RuntimeError('Current A486 rollback/application/private bytes differ')
    return 486


class StageConsole(acceptance.Console):
    READ=acceptance.Console.READ | frozenset(('BENCH STATUS',))
    def query(self,text,timeout=2):
        if text not in self.READ:
            raise ValueError('Inactive staging permits read-only query commands')
        return super().query(text,timeout)
    def command(self,text,timeout=5):
        if text in ('FW STATUS','ANALOG SAFE STATUS','BENCH STATUS','STATUS'):
            return self.query(text,timeout)
        if text=='FW END': raise ValueError('Stage never activates image')
        return super().command(text,timeout)


def main(config=None):
    # Keep each image and rollback receipt pinned in its own profile.
    cfg=config or sys.modules[__name__]
    pinned_image,verified_baseline=cfg.pinned_image,cfg.verified_baseline
    OUTPUT,IMAGE,SHA,FAILURE=cfg.OUTPUT,cfg.IMAGE,cfg.SHA,cfg.FAILURE
    Board,open_port=cfg.Board,cfg.open_port
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--drive-12v-off',action='store_true')
    p.add_argument('--motor-leads-disconnected',action='store_true')
    p.add_argument('--allow-inactive-stage',action='store_true')
    args=p.parse_args()
    if not (args.drive_12v_off and args.motor_leads_disconnected and args.allow_inactive_stage):
        p.error('Drive off, motor disconnected and scoped stage authorization required')
    data=pinned_image()
    run=str(time.time_ns()); out=OUTPUT/f'{getattr(cfg,"STAGE_PREFIX","irq-dma-trace-stage")}-{run}.json'
    row=dict(pass_=False,mode='stage',image_sha256=SHA,image_bytes=len(data),
             rollback_evidence=str(FAILURE.resolve()),motor_commands=0,
             activation=False,steps=[],drive_12v_off_user_confirmed=True)
    board=Board(row,run); port=uart=None
    try:
        before=board.capture('before')
        generation=verified_baseline(before,FAILURE)
        row['before_outputs']=board.outputs('A',False)
        port=open_port(); uart=StageConsole(port)
        row['before_fw']=require_confirmed(uart.query('FW STATUS'),'A')
        if row['before_fw'].get('GEN')!=str(generation):
            raise RuntimeError('UART/Flash generation differs')
        row['before_bench']=old.previous.old.require_stopped(uart.query('BENCH STATUS'))
        status=fields(uart.query('STATUS'))
        if status.get('FLT')!='0' or status.get('MODE')!='IDLE':
            raise RuntimeError('A fault or non-idle mode; no staging')
        safe=fields(uart.query('ANALOG SAFE STATUS'))
        if any(safe.get(k)!=v for k,v in (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
            raise RuntimeError('A maintenance lock absent')
        stage(uart,IMAGE,DEFAULT_CLIENT,allow_reset=False)
        row['after_fw']=fw=fields(uart.query('FW STATUS'))
        if any(fw.get(k)!=v for k,v in (('CURRENT','A'),('CONFIRMED','A'),
                ('GEN',str(generation)),('PENDING','-'),('TARGET','B'),
                ('ACTIVE','1'),('RX',str(len(data))))):
            raise RuntimeError('Staged metadata differs')
        actual=board.capture('staged'); compare_flash(before,actual,data,'B',staged=True)
        if actual[:0x40000]!=before[:0x40000] or actual[0x78000:]!=before[0x78000:]:
            raise RuntimeError('Bytes outside B changed')
        row['all_bytes_outside_b_unchanged']=True
        row['final_outputs']=board.outputs('A',False)
        row['pass_']=True
    except BaseException as error:
        row['failure']=str(error); raise
    finally:
        if uart: row['uart']=uart.lines
        if port: port.close()
        out.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(('PASS' if row['pass_'] else 'FAIL')+': pinned inactive B stage; no activation',flush=True)
        print('Evidence: '+str(out),flush=True)


if __name__=='__main__': main()
