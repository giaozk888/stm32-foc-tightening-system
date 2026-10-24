"""OFF/ON x5 alternating, same frozen600rpm A; files-only by default."""
import json
from pathlib import Path
import math
import statistics
import sys
import time
import dob_feedback_board as fb

low=fb.low
ROOT_RESTORE=low.TMP/'mechanical-ident-restore-1792736567554269700.json'
SCHEDULE=(False,True)*5
ORIGINAL_SETUP=fb.setup

def setup(path):
    ORIGINAL_SETUP(ROOT_RESTORE);low.base.baseline() # Actual feedback A / B1087 first.
    if path.resolve()!=ROOT_RESTORE.resolve():low.base.configure_baseline(path)
    return fb.image()

def metrics(row):
    a=row.get('accel_ff_ram_stats',{});f=row.get('friction_ram_stats',{}).get('POS',{})
    m=row.get('dob_capture',{}).get('meta',{});q=row.get('feedback_capture',{})
    def ratio(n,d):
        x,y=n or 0,d or 0
        return x/y if y>0 and math.isfinite(x) and math.isfinite(y) else None
    return dict(accel_mae_rpm=ratio(a.get('accel_error_integral'),a.get('accel_time_s')),
        decel_mae_rpm=ratio(a.get('decel_error_integral'),a.get('decel_time_s')),
        cruise_mae_rpm=ratio(f.get('cruise_error_integral'),f.get('cruise_time_s')),
        low_mae_rpm=ratio(f.get('low_error_integral'),f.get('low_time_s')),
        max_error_rpm=a.get('max_error_rpm'),overshoot_rpm=a.get('overshoot_rpm'),
        iq_command_peak_a=a.get('iq_peak_a'),pi_peak_a=f.get('pi_peak_a'),
        integrator_peak_a=a.get('integrator_peak_a'),iq_saturation_s=a.get('saturation_s'),
        stable_motion_delay_s=f.get('start_delay_s'),comp_peak_a=q.get('peak_a'),
        dob_valid_fraction=ratio(m.get('valid_samples'),m.get('observations')),
        foc_max_us=row.get('snapshot',{}).get('timing',{}).get('wall_max_us'),
        deadline_miss=row.get('snapshot',{}).get('timing',{}).get('deadline_miss'),
        ccr_late=row.get('snapshot',{}).get('timing',{}).get('actual_late_count'))

def summarize(rows):
    groups={}
    for enabled in (False,True):
        values=[metrics(r) for r in rows if r.get('dob_control_enabled') is enabled]
        result={}
        for key in metrics({}):
            x=[v[key] for v in values if v[key] is not None and math.isfinite(v[key])]
            result[key]=dict(n=len(x),mean=statistics.mean(x) if x else None,
                sd=statistics.stdev(x) if len(x)>1 else None,min=min(x) if x else None,max=max(x) if x else None)
        groups['ON' if enabled else 'OFF']=dict(runs=len(values),metrics=result)
    pairs=[]
    for i in range(0,len(rows)-1,2):
        a,b=rows[i:i+2]
        if a.get('dob_control_enabled') is not False or b.get('dob_control_enabled') is not True:
            raise ValueError('OFF/ON pair order mismatch')
        ma,mb=metrics(a),metrics(b)
        pairs.append(dict(pair=i//2+1,off=a['receipt_path'],on=b['receipt_path'],
            on_minus_off={k:mb[k]-ma[k] if ma[k] is not None and mb[k] is not None else None for k in ma}))
    return dict(groups=groups,pairs=pairs,note='Same-image alternating unloaded trials; mean/SD and paired differences, not calibrated load rejection or proof of causality.')

def execute(path,parent):
    if not parent.get('operator_present_whole_batch'):raise ValueError('Fresh whole-batch powered confirmation required')
    plan=json.loads(path.read_text())
    if (plan.get('speeds_rpm')!=[600] or plan.get('ka_a_per_rpm_s')!=low.KA or
        plan.get('overspeed_trip_rpm')!=1000 or plan.get('travel_limit_deg')!=30000):
        raise ValueError('Exact600rpm frozen limits plan required')
    data=fb.image();source,before=low.base.staged(path,data)
    parent.update(feedback_schedule=[int(x) for x in SCHEDULE],automatic_retry=False,
                  identification=None,dob_feedback_gain=.25,dob_control_enabled=False)
    rows=[]
    for index,enabled in enumerate(SCHEDULE,1):
        fb.FEEDBACK_ON=enabled
        name='mechanical-ident-run-'+str(time.time_ns())
        row=low.prior.new_run(name,parent,True,index)
        row.update(rpm=600,ka_a_per_rpm_s=low.KA,psi_f_wb=low.PSI,friction_enabled=True,
            automatic_parameter_write=False,dob_control_enabled=False,feedback_requested=enabled,
            overspeed_trip_rpm=1000,travel_limit_deg=30000,host_max_seconds=11.)
        parent['attempts'].append(row['receipt_path']);parent['last_run']=row['receipt_path']
        low.prior.checkpoint(parent,'DOB_'+str(index)+'_intent');low.prior.checkpoint(row,'prepared')
        print('DOB %d/10 %s;600rpm gain.25 cap.025A totalIq.50A'%(index,'ON' if enabled else 'OFF'),flush=True)
        try:
            fb.run_point(row,name,source,before,data,600,index==1)
            if (not row.get('pass_') or row.get('final_outputs_off') is not True or
                row.get('final_cpu_halted') is not True or row.get('dob_control_enabled') is not enabled):
                raise RuntimeError('Completed mode/output-off/halt evidence missing; no next run')
            low.prior.checkpoint(row,'safe_acquisition_complete')
            parent['runs'].append(row['receipt_path']);rows.append(row)
            parent['comparison']=summarize(rows)
            source=Path(row['final_capture']);before=source.read_bytes()
            low.prior.checkpoint(parent,'DOB_'+str(index)+'_saved')
            print('SAVED %d/10 %s accelMAE=%s cruiseMAE=%s'%(index,'ON' if enabled else 'OFF',
                metrics(row)['accel_mae_rpm'],metrics(row)['cruise_mae_rpm']),flush=True)
        except BaseException as error:
            row['pass_']=False;row['failure']=str(error)
            if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
                try:low.base.hw.emergency_off(row,low.TMP/(name+'-failed.bin'))
                except Exception as off:row['cleanup_error']=str(off)
            low.prior.checkpoint(row,'batch_stopped_no_retry');raise
    parent.update(pass_=True,acquisition_complete=True,final_outputs_off=True,final_cpu_halted=True,
                  dob_control_enabled=any(SCHEDULE),comparison=summarize(rows))

def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if '--execute-ten' in args:args[args.index('--execute-ten')]='--execute-six'
    if '--baseline-restore' not in args and not any(x in args for x in ('--execute-six','--restore-b-drive-off')):
        args+=['--baseline-restore',str(ROOT_RESTORE)]
    fb.FEEDBACK_ON=False
    low.setup,low.POINTS,low.execute=setup,(600,),execute
    low.TRIP_RPM,low.TRAVEL_DEG,low.CLOSURE_SECONDS,low.LIMITS_QUERY=1000,30000,11.,True
    low.LIMITS_EXTRA=dict(PLAUSIBLE_RPM='1000',REJECT_BUSY='1',OBS_AFTER_ACK='1')
    return low.main(args)

if __name__=='__main__':raise SystemExit(main())
