"""Preserve current fault evidence; one powered hard-off A506 reset, no retry.

Normal calibration must pass before staging. Never clear, alter protection,
select slots, force confirmation or send a motor/bridge command.
"""
import argparse
import json
import subprocess
import time

import protected_feedback_fast_stage as profile
from firmware_transfer_iap import fields
from protected_irq_timing_acceptance import TimingConsole
from zero_retest_deploy import require_confirmed


class Console(TimingConsole):
    READ=TimingConsole.READ | frozenset(('BENCH STATUS','BENCH ZERO','BENCH ZERO FILTER',
        'BENCH PROTECTION','BENCH PROTECTION TIMING','BENCH PROTECTION FAULT'))
    def query(self,text,timeout=2):
        if text not in self.READ and text!='ANALOG SAFE':
            raise ValueError('Baseline permits queries and output shutdown only')
        return super().query(text,timeout)


def snapshot(uart):
    r={}
    for key,cmd in (('fw','FW STATUS'),('status','STATUS'),('safe','ANALOG SAFE STATUS'),
                    ('bench','BENCH STATUS'),('zero','BENCH ZERO'),
                    ('filter','BENCH ZERO FILTER'),('protection','BENCH PROTECTION'),
                    ('timing','BENCH PROTECTION TIMING'),('fault','BENCH PROTECTION FAULT'),
                    ('adc','ADC TIMING')):
        line=uart.query(cmd)
        r[key]=line if key=='status' else fields(line)
    r['encoder']=uart.encoder_diag()
    return r


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inspect',action='store_true')
    p.add_argument('--allow-one-reset',action='store_true')
    p.add_argument('--drive-12v-on-motor-disconnected',action='store_true')
    args=p.parse_args()
    if args.inspect == args.allow_one_reset:
        p.error('Choose inspect or one authorized reset')
    if args.allow_one_reset and not args.drive_12v_on_motor_disconnected:
        p.error('Powered, motor-disconnected state required for normal zero calibration')
    run=str(time.time_ns()); out=profile.OUTPUT/f'feedback-fast-baseline-{run}.json'
    row=dict(pass_=False,mode='inspect' if args.inspect else 'healthy-a506',
        original_receipt=str(profile.ORIGINAL),steps=[],motor_commands=0,resets=0,
        powered_motor_disconnected_user_confirmed=args.drive_12v_on_motor_disconnected)
    board=profile.Board(row,run); port=uart=None; reset=False
    try:
        port=profile.open_port(); uart=Console(port)
        row['before']=before=snapshot(uart)
        require_confirmed('OK '+' '.join(f'{k}={v}' for k,v in before['fw'].items()),'A')
        if before['fw'].get('GEN')!='506': raise RuntimeError('Not original A506')
        row['before_outputs']=board.outputs('A',False)
        if args.inspect:
            row['pass_']=True
            return
        raw=board.capture('before_reset'); profile.original_baseline(raw)
        # Bind recovery to the captured zero failure, not a generic fault clear.
        if (fields(before['status']).get('FLT')!='1' or
            before['protection'].get('FLAGS')!='8' or before['fault'].get('REASON')!='3' or
            before['zero'].get('STATE')!='4' or before['zero'].get('REASON')!='2'):
            raise RuntimeError('Expected preserved A zero-range failure absent')
        row['resets']=1; reset=True
        proc=subprocess.run([profile.board_profile.CLI,'-c','port=SWD','mode=HOTPLUG',
            'freq=1000','sn='+profile.board_profile.SN,'-rst'],
            capture_output=True,text=True,errors='replace',timeout=30)
        output=proc.stdout+proc.stderr
        row['steps'].append(dict(args=['-rst'],code=proc.returncode,output=output))
        if proc.returncode or 'Error:' in output: raise RuntimeError('One reset failed; no retry')
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            try: fw=uart.query('FW STATUS',.5)
            except TimeoutError: continue
            row['fw']=require_confirmed(fw,'A')
            if row['fw'].get('GEN')!='506': raise RuntimeError('Reset changed metadata')
            current=snapshot(uart); row['after_reset']=current
            if fields(current['status']).get('FLT')!='0':
                raise RuntimeError('A calibration/computation fault; no staging or reset retry')
            if current['zero'].get('STATE')=='3' and current['zero'].get('N')=='4000':
                row['zero']=current['zero']
                break
            uart.poll(.05)
        else: raise TimeoutError('Healthy A calibration unavailable; no retry')
        row['shutdown']=uart.query('ANALOG SAFE')
        row['status']=uart.query('STATUS')
        row['safe']=fields(uart.query('ANALOG SAFE STATUS'))
        if (fields(row['status']).get('FLT')!='0' or
            any(row['safe'].get(k)!=v for k,v in
                (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0')))):
            raise RuntimeError('A not healthy/output-locked after shutdown')
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
