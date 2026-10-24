"""One supervised 240rpm synchronized-window acquisition. FILES ONLY by default."""
import argparse
import json
from pathlib import Path
import time
import ka_sync_board as sync

base=sync.base
gain=sync.gain
TMP=sync.TMP
ROOT_RESTORE=TMP/'ka-sync-restore-1792655544439211500.json'
PRECHECK=TMP/'ka-sync-run-1792655465337102800.json'


def motion(board,row):
    # Reuse the exact original protected FSM START owner, not the no-START
    # preflight callback. Ka=0/FRIC=.105/BEMF OFF are independently read back.
    sync.previous.motion(board,row)


def setup(path):
    pre=json.loads(PRECHECK.read_text())
    if (pre.get('image_sha256')!=sync.SHA or pre.get('elf_sha256')!=sync.ELF_SHA or not pre.get('pass_')):
        raise ValueError('Exact same-image no-START preflight required')
    sync.accept(pre)
    data=sync.setup(path)
    base.motion=motion;gain.fitted.motion=motion
    return data


def classify(row):
    metrics=gain.prior.metrics(row) # All original protection/timing/closure checks.
    captured=row.get('sync_saved',{})
    if not captured.get('complete_short_window') or len(captured.get('points',[]))!=64:
        raise RuntimeError('64-point capture incomplete; keep evidence, no retry')
    metrics.update(ka_compile_time=0.0,short_window_points=64,
        source_alignment_data_valid=captured['all_observations_valid'],
        current_minus_encoder_time_us=captured['current_minus_encoder_time_us'],
        publisher_max_us=captured['publisher_max_us'],short_window_span_us=captured['span_us'])
    return metrics


def execute(row,name,plan,data):
    try:base.execute(row,name,plan,data)
    except RuntimeError as error:
        if str(error)!=gain.EXPECTED_TERMINAL:raise
        row['natural_terminal_note']=str(error)
    row['metrics']=classify(row)
    row.update(pass_=True,acquisition_complete=True,tightening_success=False)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--prepare-off',action='store_true');m.add_argument('--execute-powered',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path);p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-drive-on-no-alarm-05a',action='store_true');a=p.parse_args(argv)
    if (a.prepare_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:p.error('Fresh OFF required')
    if a.execute_powered and not a.operator_present_drive_on_no_alarm_05a:p.error('Fresh supervised powered confirmation required')
    source=a.execute_powered or a.restore_b_drive_off
    selected=a.baseline_restore or (Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE)
    data=setup(selected)
    if not (a.prepare_off or source):print('OFFLINE PASS: one same-image synchronized acquisition; no devices');return 0
    mode='stage' if a.prepare_off else 'restore' if a.restore_b_drive_off else 'run'
    name='ka-sync-motion-'+mode+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],postflight={},
        image_sha256=sync.SHA,elf_sha256=sync.ELF_SHA,baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),
        start_attempts=0,automatic_retry=False,automatic_parameter_write=False,precheck_receipt=str(PRECHECK),
        physical_power_off=a.drive_off_unlocked_no_load_fixed,powered_no_alarm=a.operator_present_drive_on_no_alarm_05a,
        friction_enabled=True,bemf_enabled=False,gain_percent=0,speed_target_rpm=240,
        speed_iq_limit_A=.50,overspeed_trip_rpm=300,host_max_seconds=base.HOST_MAX_SECONDS)
    gain.prior.checkpoint(row,'prepared')
    try:
        if a.prepare_off:base.stage(row,name,data)
        elif a.restore_b_drive_off:base.restore(row,name,source,data)
        else:execute(row,name,source,data)
    except BaseException as error:
        row['failure']=str(error)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    gain.prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
