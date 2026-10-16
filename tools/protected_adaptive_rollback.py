"""Read-only evidence after one failed adaptive trial; never reset or clear."""
import argparse
import json
from pathlib import Path
import time
import protected_adaptive_stage as profile
from protected_closed_loop_acceptance import stage_evidence
from protected_feedback_fast_baseline import Console,snapshot
from firmware_transfer_iap import fields
from zero_retest_deploy import latest_meta,require_confirmed

def main(config=None):
    cfg=config or profile
    generation=getattr(cfg,'GENERATION',514)
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--failure',type=Path,required=True)
    args=p.parse_args(); path=args.failure.resolve()
    if path.parent!=cfg.OUTPUT.resolve() or not path.name.startswith('irq-compute-'):
        raise ValueError('Exact compute evidence directory required')
    failed=json.loads(path.read_text('utf-8'))
    if (failed.get('pass_') is not False or failed.get('image_sha256')!=cfg.SHA or
        failed.get('host_trial_commits')!=1 or failed.get('host_motor_commands')!=0 or
        not failed.get('final_outputs_off') or failed.get('cleanup_failure') or failed.get('confirmed')):
        raise RuntimeError('Single stopped unconfirmed adaptive trial required')
    before,staged=stage_evidence(Path(failed['stage']),cfg.pinned_image(),source_profile=cfg)
    prefix=getattr(cfg,'ROLLBACK_PREFIX','adaptive-rollback')
    run=str(time.time_ns()); out=cfg.OUTPUT/f'{prefix}-{run}.json'
    row=dict(pass_=False,failure_receipt=str(path),image_sha256=cfg.SHA,
        resets=0,motor_commands=0,steps=[])
    board=cfg.Board(row,run); port=uart=None
    try:
        port=cfg.open_port(); uart=Console(port)
        row['fw']=require_confirmed(uart.query('FW STATUS'),'A')
        row['fallback']=current=snapshot(uart)
        if any(current['safe'].get(k)!=v for k,v in
            (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
            raise RuntimeError('Fallback not locked')
        row['fallback_healthy']=fields(current['status']).get('FLT')=='0'
        row['outputs']=board.outputs('A',False)
        raw=board.capture('rollback')
        if raw[:0x7e800]!=staged[:0x7e800] or raw[0x7f800:]!=staged[0x7f800:]:
            raise RuntimeError('Application/private bytes changed during automatic rollback')
        old,new=latest_meta(before),latest_meta(raw)
        if (old[2:6]!=(1,0,0,generation) or new[:2]!=old[:2] or new[2:6]!=(1,0,0,generation+4) or
            new[6:8]!=old[6:8] or new[8:10]!=(0,0) or row['fw'].get('GEN')!=str(generation+4)):
            raise RuntimeError('Expected automatic rollback metadata absent')
        row['all_app_and_private_bytes_unchanged']=True
        row['failed_b_not_bootable_without_new_staging']=True
        row['pass_']=True
    except BaseException as error:
        row['failure']=str(error); raise
    finally:
        if uart: row['uart']=uart.lines
        if port: port.close()
        out.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(('ROLLBACK PROOF PASS' if row['pass_'] else 'ROLLBACK PROOF FAIL')+'; read only',flush=True)
        print('Evidence: '+str(out),flush=True)

if __name__=='__main__': main()
