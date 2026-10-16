"""Read-only proof of healthy A514 automatic rollback after one source trial."""
import argparse
import json
import time
from pathlib import Path
import protected_irq_source_stage as profile
from protected_feedback_fast_baseline import Console,snapshot
from firmware_transfer_iap import fields
from zero_retest_deploy import latest_meta,require_confirmed

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--failure',type=Path,required=True); args=p.parse_args()
    path=args.failure.resolve()
    if path.parent!=profile.OUTPUT.resolve() or not path.name.startswith('irq-compute-'):
        raise ValueError('Exact compute receipt directory required')
    failed=json.loads(path.read_text('utf-8'))
    if (failed.get('pass_') is not False or failed.get('image_sha256')!=profile.SHA or
        failed.get('host_trial_commits')!=1 or failed.get('host_motor_commands')!=0 or
        not failed.get('final_outputs_off') or failed.get('cleanup_failure') or failed.get('confirmed')):
        raise RuntimeError('Single stopped unconfirmed source trial required')
    run=str(time.time_ns()); out=profile.OUTPUT/f'irq-source-rollback-{run}.json'
    row=dict(pass_=False,image_sha256=profile.SHA,failure_receipt=str(path),steps=[],motor_commands=0,resets=0)
    board=profile.Board(row,run); port=uart=None
    try:
        port=profile.open_port(); uart=Console(port)
        row['fw']=require_confirmed(uart.query('FW STATUS'),'A')
        row['fallback']=current=snapshot(uart); row['status']=current['status']; row['safe']=current['safe']
        if any(row['safe'].get(k)!=v for k,v in (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
            raise RuntimeError('Fallback not maintenance locked')
        row['fallback_fault']=fields(row['status']).get('FLT')!='0'
        row['outputs']=board.outputs('A',False)
        before=profile.previous.board_profile.previous.private_capture(failed,'before_trial')
        actual=board.capture('rollback')
        if actual[:0x7E800]!=before[:0x7E800] or actual[0x7F800:]!=before[0x7F800:]:
            raise RuntimeError('Application/private bytes changed during rollback')
        old,new=latest_meta(before),latest_meta(actual)
        if (old[2:6]!=(1,0,0,510) or new[:2]!=old[:2] or new[2:6]!=(1,0,0,514) or
            new[6:8]!=old[6:8] or new[8:10]!=(0,0) or row['fw'].get('GEN')!='514'):
            raise RuntimeError('Expected automatic rollback metadata absent')
        row['all_app_and_private_bytes_unchanged']=True
        row['failed_b_not_bootable_without_new_staging']=True
        if row['fallback_fault']: raise RuntimeError('Fallback health failed; output/Flash evidence retained')
        row['pass_']=True
    except BaseException as error:
        row['failure']=str(error); raise
    finally:
        if uart: row['uart']=uart.lines
        if port: port.close()
        out.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(('ROLLBACK PASS' if row['pass_'] else 'ROLLBACK FAIL')+'; read only',flush=True)
        print('Evidence: '+str(out),flush=True)

if __name__=='__main__': main()
