"""Preserve A514 evidence; inspect or one normal powered hard-off reset.

No flash writes, image activation, fault clear, motor start or reset retry.
Full Flash stays in the existing restricted private backup directory.
"""
import argparse
import json
import subprocess
import time
import protected_adaptive_stage as profile
from protected_feedback_fast_baseline import Console, snapshot
from firmware_transfer_iap import fields
from zero_retest_deploy import require_confirmed

def identity(row,config=None):
    cfg=config or profile
    generation=str(getattr(cfg,'GENERATION',514))
    require_confirmed('OK '+' '.join(f'{k}={v}' for k,v in row['fw'].items()),'A')
    if row['fw'].get('GEN')!=generation or any(row['safe'].get(k)!=v for k,v in
        (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
        raise RuntimeError('Confirmed locked A'+generation+' required')

def main(config=None):
    cfg=config or profile
    generation=str(getattr(cfg,'GENERATION',514))
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--inspect',action='store_true')
    group.add_argument('--allow-one-reset',action='store_true')
    p.add_argument('--drive-12v-on-motor-disconnected',action='store_true')
    args=p.parse_args()
    if args.allow_one_reset and not args.drive_12v_on_motor_disconnected:
        p.error('User-confirmed powered, motor-disconnected state required')
    prefix=getattr(cfg,'BASELINE_PREFIX','adaptive-baseline')
    run=str(time.time_ns()); out=cfg.OUTPUT/f'{prefix}-{run}.json'
    row=dict(pass_=False,mode='inspect' if args.inspect else 'healthy-a'+generation,steps=[],
        original_receipt=str(cfg.ORIGINAL),motor_commands=0,resets=0,
        powered_motor_disconnected_user_confirmed=args.drive_12v_on_motor_disconnected)
    board=cfg.Board(row,run); port=uart=None; reset=False
    try:
        port=cfg.open_port(); uart=Console(port)
        row['before']=before=snapshot(uart); identity(before,cfg)
        row['before_outputs']=board.outputs('A',False)
        raw=board.capture('before_reset'); cfg.original_baseline(raw)
        if args.inspect:
            row['pass_']=True
            return
        if hasattr(cfg,'expected_fault'):
            cfg.expected_fault(before)
        elif (fields(before['status']).get('FLT')!='1' or
            before['protection'].get('FLAGS')!='8' or
            before['zero'].get('STATE')!='4' or before['zero'].get('REASON')!='2'):
            raise RuntimeError('Expected preserved zero-range failure absent; no reset')
        row['resets']=1; reset=True
        cli=cfg.board_profile
        proc=subprocess.run([cli.CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+cli.SN,'-rst'],
            capture_output=True,text=True,errors='replace',timeout=30)
        output=proc.stdout+proc.stderr
        row['steps'].append(dict(args=['-rst'],code=proc.returncode,output=output))
        if proc.returncode or 'Error:' in output: raise RuntimeError('One reset failed; no retry')
        end=time.monotonic()+90
        while time.monotonic()<end:
            try: fw=uart.query('FW STATUS',.5)
            except TimeoutError: continue
            row['fw']=require_confirmed(fw,'A')
            if row['fw'].get('GEN')!=generation: raise RuntimeError('Reset changed metadata')
            row['after_reset']=current=snapshot(uart)
            if fields(current['status']).get('FLT')!='0':
                raise RuntimeError('A startup/calculation fault; no retry or staging')
            if current['zero'].get('STATE')=='3' and current['zero'].get('N')=='4000':
                row['zero']=current['zero']; break
            uart.poll(.05)
        else: raise TimeoutError('Fresh healthy A calibration unavailable')
        row['shutdown']=uart.query('ANALOG SAFE')
        row['status']=uart.query('STATUS')
        row['safe']=fields(uart.query('ANALOG SAFE STATUS'))
        if fields(row['status']).get('FLT')!='0' or any(row['safe'].get(k)!=v for k,v in
            (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
            raise RuntimeError('A not healthy/locked after shutdown')
        row['outputs']=board.outputs('A',False)
        if board.capture('healthy')!=raw: raise RuntimeError('Reset changed Flash bytes')
        row['all_flash_unchanged']=True
        row['pass_']=True
    except BaseException as error:
        row['failure']=str(error); raise
    finally:
        if uart and reset and not row.get('shutdown'):
            try:
                row['shutdown']=uart.query('ANALOG SAFE')
                row['final_safe']=fields(uart.query('ANALOG SAFE STATUS'))
                row['final_outputs']=board.outputs('A',False)
            except BaseException as error: row['cleanup_failure']=str(error)
        if uart: row['uart']=uart.lines
        if port: port.close()
        out.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(('BASELINE PASS' if row['pass_'] else 'BASELINE FAIL')+'; no motor command',flush=True)
        print('Evidence: '+str(out),flush=True)

if __name__=='__main__': main()
