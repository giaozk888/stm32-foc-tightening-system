"""Read-only proof of automatic rollback after exact compute-only failure."""
import argparse
import json
import time
from pathlib import Path
import protected_irq_optimized_stage as profile
import protected_irq_timing_acceptance as compute
from firmware_transfer_iap import fields
from zero_retest_deploy import latest_meta, require_confirmed

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--failure',type=Path,required=True); args=p.parse_args()
    path=args.failure.resolve()
    if path.parent!=profile.OUTPUT.resolve(): raise ValueError('Exact evidence directory required')
    failed=json.loads(path.read_text('utf-8'))
    if (failed.get('pass_') is not False or failed.get('image_sha256')!=profile.SHA or
        failed.get('host_trial_commits')!=1 or failed.get('host_motor_commands')!=0 or
        not failed.get('final_outputs_off') or failed.get('cleanup_failure')):
        raise RuntimeError('Exact stopped compute-only attempt required')
    run=str(time.time_ns()); out=profile.OUTPUT/f'irq-rollback-{run}.json'
    row=dict(pass_=False,failure_receipt=str(path),steps=[],motor_commands=0,resets=0)
    board=profile.Board(row,run); port=None
    try:
        port=profile.open_port(); uart=compute.TimingConsole(port)
        row['fw']=require_confirmed(uart.query('FW STATUS'),'A')
        row['safe']=s=fields(uart.query('ANALOG SAFE STATUS'))
        if any(s.get(k)!=v for k,v in (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
            raise RuntimeError('Fallback not locked')
        row['outputs']=board.outputs('A',False)
        before=profile.previous.private_capture(failed,'before_trial')
        actual=board.capture('rollback')
        if actual[:0x7E800]!=before[:0x7E800] or actual[0x7F800:]!=before[0x7F800:]:
            raise RuntimeError('Automatic rollback changed application/private regions')
        old,new=latest_meta(before),latest_meta(actual)
        if (new[:2]!=old[:2] or new[2:6]!=(1,0,0,482) or
            new[6:8]!=old[6:8] or new[8:10]!=(0,0) or row['fw'].get('GEN')!='482'):
            raise RuntimeError('Normal failed-B invalidation/rollback metadata differs')
        row['all_app_and_private_bytes_unchanged']=True
        row['failed_b_not_bootable_without_new_staging']=True
        row['uart']=uart.lines; row['pass_']=True
    except BaseException as error:
        row['failure']=str(error); raise
    finally:
        if port: port.close()
        out.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(('ROLLBACK OBSERVE PASS' if row['pass_'] else 'ROLLBACK OBSERVE FAIL')+'; read only',flush=True)
        print('Evidence: '+str(out),flush=True)

if __name__=='__main__': main()
