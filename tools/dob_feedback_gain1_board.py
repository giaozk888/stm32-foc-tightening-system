"""Frozen gain1.0 DOB diagnostic, three600rpm ON runs; files-only default."""
import json
from pathlib import Path
import math
import statistics
import sys
import time
import dob_feedback_board as fb
from dob_feedback_repeat5 import metrics

low=fb.low
ROOT_RESTORE=low.TMP/'mechanical-ident-restore-1792737355188145200.json'
IMAGE=low.base.old.ROOT/'foc2_app_a/build/MechanicalDobFeedbackGain1Candidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='cfb4a3c6b26add1533b7d50aeadd9f83cbdbc2bf684351b195468186c592b131'
ELF_SHA='17c5f384fea5f1c84115b1a1a96806f62185af7bf7117661fb1f5ba46b663b74'
SIZE=219852
GAIN=1.0
SUMMARY_KEY='gain1_summary'
ORIGINAL_SETUP=fb.setup
FB_CONFIG=dict(fb.FB_CONFIG,GAIN_PPM='1000000')

def image():
    data=fb.v7.validator.validate_image(IMAGE,ELF,SHA,ELF_SHA,SIZE,
        extra_flags=('FOC_OUTER_OBSERVE_AFTER_ACK=1','FOC_READY_TIMESTAMP_SNAPSHOT=1',
            'FOC_MECHANICAL_DOB_SHADOW=1','FOC_DOB_ID_TRACE=1','FOC_DOB_SPIKE_ADMISSION=1',
            'FOC_DOB_ADMISSION_START_GUARD=1','FOC_DOB_DIRECT_JUMP_REJECT=1',
            'FOC_DOB_RECOVERABLE_ADMISSION=1','FOC_DOB_PERSISTENT_QUALITY=1',
            'FOC_DOB_ID_PRE_LPF_QUALITY=1','DOB_ADMIT_JUMP_A=.200f',
            'FOC_DOB_FEEDBACK_CANDIDATE=1','DOB_FB_GAIN='+str(GAIN)+'f'),
        extra_markers=(b'DOB_SHADOW=1 SIGNS=POS,NEG GRID_RPM=600 DOB_CONTROL=%u',
            b'OK DOBFB ON=%lu GAIN_PPM=%lu CAP_UA=25000',b'ERR DOBFB BUSY_OR_OUTPUT_ENABLED',
            b'OK IDTRACE V=7 PRE=16 DENSE=24 TAIL=32 TAIL_US=16000'))
    symbols=low.base.symbols(ELF)
    for name,size in dict(dob_feedback=80,mechanical_dob_monitor=856,dob_id_trace=96,
                          dob_current_admission=204,outer_completion_trace=644).items():
        if symbols.get(name,(0,0))[1]!=size:raise ValueError('Gain1 DOB ABI '+name)
    return data

def setup(path):
    ORIGINAL_SETUP(ROOT_RESTORE);low.base.baseline() # Actual gain.25 / B1091 before new identity.
    for n in ('IMAGE','ELF','SHA','ELF_SHA','SIZE'):
        setattr(fb,n,globals()[n]);setattr(low,n,globals()[n])
    fb.FB_CONFIG=FB_CONFIG
    low.image,low.run_point,low.MechanicalBoard=image,fb.run_point,fb.FeedbackBoard
    low.base.staged=fb.v7.staged
    for obj in (low.base,low.previous.gain,low.fitted):
        obj.IMAGE,obj.ELF,obj.SHA,obj.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA;obj.image=image
    low.previous.gain.SIZE=low.fitted.SIZE=SIZE
    if path.resolve()!=ROOT_RESTORE.resolve():low.base.configure_baseline(path)
    return image()

def summarize(rows):
    values=[metrics(r) for r in rows];result={}
    for key in metrics({}):
        x=[v[key] for v in values if v[key] is not None and math.isfinite(v[key])]
        result[key]=dict(n=len(x),mean=statistics.mean(x) if x else None,
            sd=statistics.stdev(x) if len(x)>1 else None,min=min(x) if x else None,max=max(x) if x else None)
    return dict(gain=GAIN,runs=len(rows),metrics=result,
        note='Three unloaded ON trials; compare previous gain.25/OFF as noncontemporaneous reference, not paired randomized A/B.')

def execute(path,parent):
    if not parent.get('operator_present_whole_batch'):raise ValueError('Fresh three-run powered confirmation required')
    plan=json.loads(path.read_text())
    if (plan.get('speeds_rpm')!=[600] or plan.get('ka_a_per_rpm_s')!=low.KA or
        plan.get('overspeed_trip_rpm')!=1000 or plan.get('travel_limit_deg')!=30000):
        raise ValueError('Exact600rpm limits plan required')
    data=image();source,before=low.base.staged(path,data)
    fb.FEEDBACK_ON=True
    parent.update(feedback_schedule=[1,1,1],dob_feedback_gain=GAIN,automatic_retry=False,identification=None)
    rows=[]
    for index in range(1,4):
        name='mechanical-ident-run-'+str(time.time_ns())
        row=low.prior.new_run(name,parent,True,index)
        row.update(rpm=600,ka_a_per_rpm_s=low.KA,psi_f_wb=low.PSI,friction_enabled=True,
            automatic_parameter_write=False,dob_control_enabled=False,feedback_requested=True,dob_feedback_gain=GAIN,
            overspeed_trip_rpm=1000,travel_limit_deg=30000,host_max_seconds=11.)
        parent['attempts'].append(row['receipt_path']);parent['last_run']=row['receipt_path']
        low.prior.checkpoint(parent,'GAIN'+str(GAIN)+'_'+str(index)+'_intent');low.prior.checkpoint(row,'prepared')
        print('DOB GAIN%g %d/3 ON;600rpm cap.025A totalIq.50A'%(GAIN,index),flush=True)
        try:
            fb.run_point(row,name,source,before,data,600,index==1)
            if (not row.get('pass_') or row.get('final_outputs_off') is not True or
                row.get('final_cpu_halted') is not True or row.get('dob_control_enabled') is not True):
                raise RuntimeError('Correct mode and closure evidence required; no next run')
            low.prior.checkpoint(row,'safe_acquisition_complete')
            parent['runs'].append(row['receipt_path']);rows.append(row);parent[SUMMARY_KEY]=summarize(rows)
            source=Path(row['final_capture']);before=source.read_bytes()
            low.prior.checkpoint(parent,'GAIN'+str(GAIN)+'_'+str(index)+'_saved')
            print('SAVED GAIN%g %d/3 accelMAE=%s cruiseMAE=%s'%(GAIN,index,
                metrics(row)['accel_mae_rpm'],metrics(row)['cruise_mae_rpm']),flush=True)
        except BaseException as error:
            row['pass_']=False;row['failure']=str(error)
            if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
                try:low.base.hw.emergency_off(row,low.TMP/(name+'-failed.bin'))
                except Exception as off:row['cleanup_error']=str(off)
            low.prior.checkpoint(row,'batch_stopped_no_retry');raise
    parent.update(pass_=True,acquisition_complete=True,final_outputs_off=True,final_cpu_halted=True,
                  dob_control_enabled=True)
    parent[SUMMARY_KEY]=summarize(rows)

def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if '--execute-three' in args:args[args.index('--execute-three')]='--execute-six'
    if '--baseline-restore' not in args and not any(x in args for x in ('--execute-six','--restore-b-drive-off')):
        args+=['--baseline-restore',str(ROOT_RESTORE)]
    fb.FEEDBACK_ON=False
    low.setup,low.POINTS,low.execute=setup,(600,),execute
    low.TRIP_RPM,low.TRAVEL_DEG,low.CLOSURE_SECONDS,low.LIMITS_QUERY=1000,30000,11.,True
    low.LIMITS_EXTRA=dict(PLAUSIBLE_RPM='1000',REJECT_BUSY='1',OBS_AFTER_ACK='1')
    return low.main(args)

if __name__=='__main__':raise SystemExit(main())
