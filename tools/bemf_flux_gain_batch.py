"""Exactly 15 supervised same-image flux-gain observations; files-only default."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import struct
import time
import ka025_bemf_board as previous

base=previous.base;gain=previous.gain;prior=gain.prior;fitted=gain.fitted
TMP=previous.TMP
ROOT_RESTORE=TMP/'ka025-bemf-restore-1792665244381199400.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/BemfFluxGainDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='c644472b27d6a9dbc74c95a9219b06e165aafd146ea411bdd77a520fc9b3fcf7'
ELF_SHA='40f1492e9dd19fa197e0272eb1ee744a017ddfc03ac93a8078a25a5c85738e6b'
SIZE=212288
PSI=.00069732
ORDER=(0,25,50,75,100,100,75,50,25,0,0,25,50,75,100)
ORIGINAL_DECODE=gain.ORIGINAL_DECODE


def image():
    data=IMAGE.read_bytes()
    cmd=next(x['command'] for x in json.loads((IMAGE.parent/'compile_commands.json').read_text())
             if x['file'].endswith('/Core/Src/main.c'))
    required=('FOC_BEMF_GAIN_DIAG=1','FOC_BEMF_CANDIDATE=1','FOC_BEMF_ENABLED_DEFAULT=0',
        'FOC_BEMF_PSI_WB=0.00069732f','SPEED_ACCEL_FF_KA_A_PER_RPM_S=0.000046875f',
        'FOC_PROTECTED_CLOSED_LOOP=1','FOC_CURRENT_PI_IDENTIFIED_ENABLE=1',
        'FOC_ONE_CYCLE_PWM_PIPELINE=1','FOC_PWM_PIPELINE_CLOSED_LOOP=1',
        'FOC_INTENT_FSM_CANDIDATE=1','FOC_SPEED_PI_ANTI_WINDUP=1',
        'AS5047P_DMA_FOC_FIRST=1','SPEED_FRICTION_I_A=0.105f',
        'FOC_ACCEL_FF_ENABLED_DEFAULT=1','FOC_FRICTION_ENABLED_DEFAULT=1')
    if (len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or
        hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        any('-D'+x+' ' not in cmd for x in required) or
        any('-D'+x in cmd for x in ('FOC_KA_FULL_DIAG','FOC_KA_SYNC_DIAG','FOC_KA_IDENT_DIAG',
            'FOC_ACCEL_FF_AUDIT','FOC_PSI_IDENT_DIAG','FOC_DQ_DECOUPLING_CANDIDATE',
            'FOC_CURRENT_STEP_AB_DIAG','FOC_FAST_REJECT_COMPUTE_ONLY')) or
        base.symbols(ELF).get('bemf_gain_percent',(0,0))[1]!=4):
        raise ValueError('Exact offline-tested flux-gain diagnostic image required')
    for marker in (b'ERR BEMF GAIN_RANGE',b'TRIP_MA=4000',b'METHOD=TWO_SAMPLE',
                   b'TRAVEL=20000deg RAM only',b'RUNDOWN240: RAM=240rpm TRIP=300rpm SAVE=OFF'):
        if marker not in data:raise ValueError('Diagnostic/protection marker missing')
    base.support.support.require_baud(cmd)
    return data


def selected_psi(row):
    percent=row.get('bemf_gain_percent')
    if (type(percent) is not int or percent not in ORDER or
        row.get('manual_ka')!=previous.KA or not row.get('friction_enabled') or
        row.get('bemf_enabled') is not bool(percent)):
        raise ValueError('Exact flux gain, fixed Ka/friction and explicit ON/OFF required')
    return PSI*percent/100


def gain_status(line,percent,on):
    v=fitted.status(line,on)
    if v.get('GAIN_PCT')!=str(percent) or abs(int(v.get('EFFECTIVE_PSI_NWB','-999'))-PSI*percent*1e7)>2:
        raise RuntimeError('Exact idle flux gain readback missing; no START')
    return v


def motion(board,row):
    fitted.PSI_WB=selected_psi(row)
    percent=row['bemf_gain_percent']
    row['bemf_gain_switch']=gain_status(board.command('MOTOR TEST BEMF GAIN '+str(percent)),percent,False)
    gain.ORIGINAL_MOTION(board,row) # Original BEMF switch and one protected START owner.
    for key,on in (('bemf_before',False),('bemf_switch',bool(percent))):
        gain_status('OK '+ ' '.join(k+'='+v for k,v in row[key].items()),percent,on)


def decode(row):
    ORIGINAL_DECODE(row)
    ram=Path(row['ram_capture']).read_bytes()
    addr,size=base.symbols(ELF)['bemf_gain_percent']
    if size!=4 or not 0<=addr-0x20000000<=len(ram)-4:raise ValueError('Flux gain ABI/bounds')
    row['bemf_gain_saved']=struct.unpack_from('<I',ram,addr-0x20000000)[0]


def setup(path):
    previous.setup(ROOT_RESTORE);base.baseline() # Verify old normal-A/B1003 identity first.
    for obj in (base,gain,fitted):
        obj.IMAGE,obj.ELF,obj.SHA,obj.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA;obj.image=image
    gain.SIZE=SIZE;fitted.SIZE=SIZE
    base.motion=motion;fitted.motion=motion;base.decode_cm=decode;fitted.decode=decode
    if path.resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(path)
    return image()


def metrics(row):
    fitted.PSI_WB=selected_psi(row)
    percent=row['bemf_gain_percent']
    if row.get('bemf_gain_saved')!=percent:
        raise RuntimeError('Final RAM flux gain mismatch; stop')
    for key,on in (('bemf_gain_switch',False),('bemf_before',False),('bemf_switch',bool(percent))):
        v=row.get(key,{})
        gain_status('OK '+' '.join(k+'='+str(x) for k,x in v.items()),percent,on)
    m=prior.metrics(row)
    m.update(bemf_gain_percent=percent,manual_ka=previous.KA,
             bemf_enabled=bool(percent),effective_psi_wb=fitted.PSI_WB)
    return m


def summarize(runs):
    names=('accel_mae_rpm','cruise_mae_rpm','overshoot_rpm','low_speed_mae_rpm',
        'iq_ref_peak_a','iq_meas_peak_a','integrator_peak_a','pi_peak_a',
        'saturation_ms','stable_motion_delay_ms','settling_time_ms','foc_max_us',
        'actual_margin_min_us','deadline_miss','ccr_late','uart_dropped_bytes','bemf_observed_peak_v')
    groups={}
    if [r['metrics']['bemf_gain_percent'] for r in runs]!=list(ORDER[:len(runs)]):
        raise ValueError('Batch order mismatch')
    for percent in (0,25,50,75,100):
        rows=[r['metrics'] for r in runs if r['metrics']['bemf_gain_percent']==percent]
        stats={}
        for name in names:
            values=[r[name] for r in rows if type(r.get(name)) in (int,float)]
            stats[name]=dict(n=len(values),missing=len(rows)-len(values),
                mean=statistics.mean(values) if values else None,
                sd=statistics.stdev(values) if len(values)>1 else None,
                min=min(values) if values else None,max=max(values) if values else None)
        groups[str(percent)]=dict(runs=len(rows),effective_psi_wb=PSI*percent/100,metrics=stats)
    return dict(completed=len(runs)==len(ORDER),groups=groups,
        qualification='Same image, each flux gain three starts, fixed Ka and protection. Rank acceleration MAE jointly with cruise, overshoot and Iq. No automatic flux/PI write; small sample not a physical flux calibration.')


def execute(path,parent):
    if not parent.get('operator_present_whole_batch'):raise ValueError('Fresh supervised powered confirmation required')
    plan=json.loads(path.read_text())
    if plan.get('batch_order')!=list(ORDER) or plan.get('batch_runs')!=15:
        raise ValueError('Exact 15-run plan required')
    data=image();base.staged(path,data);previous_run=None
    for index,percent in enumerate(ORDER,1):
        name='bemf-flux-gain-run-'+str(time.time_ns())
        row=prior.new_run(name,parent,bool(percent),index)
        row.update(bemf_gain_percent=percent,manual_ka=previous.KA,
            reference_psi_wb=PSI,psi_f_wb=PSI*percent/100,automatic_parameter_write=False)
        parent['attempts'].append(row['receipt_path']);parent['last_run']=row['receipt_path']
        prior.checkpoint(parent,'run_'+str(index)+'_intent');prior.checkpoint(row,'prepared')
        print('FLUX GAIN RUN %d/15 %d%%'%(index,percent),flush=True)
        try:
            if previous_run is None:
                try:base.execute(row,name,path,data)
                except RuntimeError as error:
                    if str(error)!=gain.EXPECTED_TERMINAL:raise
                    row['natural_terminal_note']=str(error)
            else:
                metrics(previous_run)
                prior.next_run(row,name,previous_run)
            row['metrics']=metrics(row)
            row.update(pass_=True,acquisition_complete=True,tightening_success=False)
            prior.checkpoint(row,'safe_acquisition_complete')
            parent['runs'].append(dict(receipt_path=row['receipt_path'],metrics=row['metrics']))
            parent['summary']=summarize(parent['runs']);prior.checkpoint(parent,'run_'+str(index)+'_saved')
            print('ACQUIRED %d/15 %s'%(index,json.dumps(row['metrics'])),flush=True)
            previous_run=row
        except BaseException as error:
            row['failure']=str(error)
            if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
                try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
                except Exception as off:row['cleanup_error']=str(off)
            prior.checkpoint(row,'batch_stopped_no_retry');raise
    parent.update(pass_=True,final_outputs_off=previous_run['final_outputs_off'],
                  final_cpu_halted=previous_run['final_cpu_halted'])


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--prepare-off',action='store_true');m.add_argument('--execute-fifteen',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path);p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-whole-batch-drive-on-no-alarm-05a',action='store_true');a=p.parse_args(argv)
    if (a.prepare_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:p.error('Fresh drive OFF required')
    if a.execute_fifteen and not a.operator_present_whole_batch_drive_on_no_alarm_05a:p.error('Fresh whole-batch powered confirmation required')
    source=a.execute_fifteen or a.restore_b_drive_off
    selected=a.baseline_restore or (Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE)
    data=setup(selected)
    if not(a.prepare_off or source):print('OFFLINE PASS: fixed 15-run flux-gain plan; no devices');return 0
    mode='stage' if a.prepare_off else 'restore' if a.restore_b_drive_off else 'batch'
    name='bemf-flux-gain-'+mode+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],
        samples=[],postflight={},runs=[],attempts=[],image_sha256=SHA,elf_sha256=ELF_SHA,
        baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),manual_ka=previous.KA,
        batch_runs=15,batch_order=list(ORDER),friction_enabled=True,bemf_enabled=False,
        physical_power_off=a.drive_off_unlocked_no_load_fixed,automatic_retry=False,
        automatic_parameter_write=False,operator_present_whole_batch=a.operator_present_whole_batch_drive_on_no_alarm_05a)
    prior.checkpoint(row,'prepared')
    try:
        if a.prepare_off:base.stage(row,name,data)
        elif a.restore_b_drive_off:base.restore(row,name,source,data)
        else:execute(source,row)
    except BaseException as error:
        row['failure']=str(error)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    if mode=='batch':row['summary']=summarize(row['runs'])
    prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
