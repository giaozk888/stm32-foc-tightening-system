"""Read-only, exact single feedback-inline trial rollback/off/Flash proof."""
import argparse
import json
import time

import protected_feedback_fast_stage as profile
from protected_feedback_fast_baseline import Console, snapshot
from firmware_transfer_iap import fields
from zero_retest_deploy import latest_meta, require_confirmed


def validate_failure(r):
    if (r.get('pass_') is not False or r.get('image_sha256')!=profile.SHA or
        r.get('host_trial_commits')!=1 or r.get('host_motor_commands')!=0 or
        not r.get('final_outputs_off') or r.get('cleanup_failure') or
        r.get('confirmed') or not r.get('failure')):
        raise RuntimeError('Exact stopped unconfirmed feedback-inline failure required')


def validate_flash(before,actual,fw):
    if actual[:0x7E800]!=before[:0x7E800] or actual[0x7F800:]!=before[0x7F800:]:
        raise RuntimeError('Application/private Flash bytes changed')
    prior,current=latest_meta(before),latest_meta(actual)
    if (prior[2:6]!=(1,0,0,506) or current[:2]!=prior[:2] or
        current[2:6]!=(1,0,0,510) or current[6:8]!=prior[6:8] or
        current[8:10]!=(0,0) or fw.get('GEN')!='510'):
        raise RuntimeError('Expected automatic A510 rollback metadata absent')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--failure',type=profile.Path,required=True)
    args=p.parse_args(); failure=args.failure.resolve()
    if failure.parent!=profile.OUTPUT.resolve() or not failure.name.startswith('irq-compute-'):
        p.error('Exact trial receipt directory required')
    failed=json.loads(failure.read_text('utf-8')); validate_failure(failed)
    run=str(time.time_ns()); out=profile.OUTPUT/f'feedback-fast-rollback-{run}.json'
    row=dict(pass_=False,failure_receipt=str(failure),image_sha256=profile.SHA,
             steps=[],motor_commands=0,resets=0)
    board=profile.Board(row,run); port=uart=None
    try:
        port=profile.open_port(); uart=Console(port)
        row['fw']=require_confirmed(uart.query('FW STATUS'),'A')
        row['fallback']=current=snapshot(uart)
        row['safe']=safe=current['safe']; row['status']=current['status']
        if any(safe.get(k)!=v for k,v in
               (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
            raise RuntimeError('Fallback not output-locked')
        row['fallback_fault']=fields(row['status']).get('FLT')!='0'
        row['outputs']=board.outputs('A',False)
        before=profile.board_profile.previous.private_capture(failed,'before_trial')
        actual=board.capture('rollback'); validate_flash(before,actual,row['fw'])
        row['all_app_and_private_bytes_unchanged']=True
        row['failed_b_not_bootable_without_new_staging']=True
        if row['fallback_fault']: raise RuntimeError('Fallback health failed; off/bytes proof retained')
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
