"""Read-only evidence for the one guardian-fast trial's automatic rollback."""
import json
import time

import protected_guard_fast_stage as profile
from protected_irq_timing_acceptance import TimingConsole
from firmware_transfer_iap import fields
from zero_retest_deploy import latest_meta, require_confirmed

FAILURE=profile.OUTPUT/'irq-compute-1791977292041516100.json'


def validate_failure(failed):
    sample=failed.get('startup_sample',{})
    if (failed.get('pass_') is not False or failed.get('image_sha256')!=profile.SHA or
            failed.get('host_trial_commits')!=1 or failed.get('host_motor_commands')!=0 or
            not failed.get('final_outputs_off') or failed.get('cleanup_failure') or
            sample.get('state',{}).get('FLAGS')!='256' or
            sample.get('timing',{}).get('MAX_US')!='53' or
            sample.get('late_frame',{}).get('VALID')!='1'):
        raise RuntimeError('Exact stopped guardian-fast failure receipt required')


def validate_flash(before,actual,fw):
    if actual[:0x7E800]!=before[:0x7E800] or actual[0x7F800:]!=before[0x7F800:]:
        raise RuntimeError('Application/private Flash bytes changed')
    prior,current=latest_meta(before),latest_meta(actual)
    if (prior[2:6]!=(1,0,0,502) or current[:2]!=prior[:2] or
            current[2:6]!=(1,0,0,506) or current[6:8]!=prior[6:8] or
            current[8:10]!=(0,0) or fw.get('GEN')!='506'):
        raise RuntimeError('Failed-B invalidation/rollback metadata differs')


def main():
    failed=json.loads(FAILURE.read_text('utf-8'))
    validate_failure(failed)
    run=str(time.time_ns()); out=profile.OUTPUT/f'guard-fast-rollback-{run}.json'
    row=dict(pass_=False,failure_receipt=str(FAILURE),image_sha256=profile.SHA,
             steps=[],motor_commands=0,resets=0)
    board=profile.Board(row,run); port=uart=None
    try:
        port=profile.open_port(); uart=TimingConsole(port)
        row['fw']=require_confirmed(uart.query('FW STATUS'),'A')
        row['safe']=safe=fields(uart.query('ANALOG SAFE STATUS'))
        if any(safe.get(k)!=v for k,v in
               (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
            raise RuntimeError('Fallback not output-locked')
        row['status']=uart.query('STATUS')
        row['fallback_fault']=fields(row['status']).get('FLT')!='0'
        if row['fallback_fault']:
            # Preserve evidence even though a healthy-fallback verdict fails.
            for key,cmd in (('fallback_state','MOTOR TEST STATUS'),
                            ('fallback_zero','MOTOR TEST ZERO'),
                            ('fallback_timing','MOTOR TEST TIMING'),
                            ('fallback_fault_snapshot','MOTOR TEST FAULT')):
                try: row[key]=fields(uart.query(cmd))
                except RuntimeError as error:
                    if 'ERR 100 UNKNOWN_COMMAND' not in str(error): raise
                    row['fallback_diagnostics_unavailable']=str(error)
                    break # Older locked A lacks the protected-test commands.
            row['fallback_adc']=fields(uart.query('ADC TIMING'))
        row['outputs']=board.outputs('A',False)
        before=profile.board_profile.previous.private_capture(failed,'before_trial')
        actual=board.capture('rollback')
        validate_flash(before,actual,row['fw'])
        row['all_app_and_private_bytes_unchanged']=True
        row['failed_b_not_bootable_without_new_staging']=True
        if row['fallback_fault']: raise RuntimeError('Fallback has a fault; rollback bytes/off proved, health failed')
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
