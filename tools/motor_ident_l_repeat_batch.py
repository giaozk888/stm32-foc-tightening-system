"""Six explicitly planned LD/LQ shots with Rs-style diagnostic admission.

Files-only by default. Quality failure continues; original protection/unknown
ACK/output/capture errors stop. Never clears faults, escalates current or PI.
"""
import argparse
import json
from pathlib import Path
import statistics as st
import struct
import time
import motor_ident_l_axis_board as axis
import motor_ident_rs_repeat_batch as shared
import motor_ident_timing_report
import encoder_saved_fault_report

run=axis.run;base=axis.base;TMP=axis.TMP
IMAGE=base.old.ROOT/'foc2_app_a/build/MotorParameterIdentificationLAdmissionDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='13b237a70625218bfddb8924b13022a95410b1313f14547238036de2f9e5c786'
ELF_SHA='08f4fe731598162155fd34cb4432a208d5e6cd5a40dabde2c68185c152b06ea0'
RESTORE=TMP/'motor-ident-ld-restore-1792559284360912200.json'
BASE_SHA='761529dd2be4197daec3420e98b97fe35d5a8060e1aca915ffba294f4d373a6b'
PLAN=tuple((m,r) for r in (1,2,3) for m in ('LD','LQ'))


def image():
    return shared.selected.previous.pinned_image(IMAGE,SHA,ELF_SHA,215156,
        ('-DFOC_IDENT_L_RS_ADMISSION_ENABLE=1','-DFOC_IDENT_RS_REJECT_COUNT_ONLY=1'))


def configure():
    axis.baseline_helper.configure_from(RESTORE,BASE_SHA,864)


def extra_readout(board,row):
    for key,cmd in (
        ('current_reject_reply','MOTOR TEST IDENT REJECT'),
        ('timing_failure_reply','MOTOR TEST IDENT TIMING'),
        ('timing_context_reply','MOTOR TEST IDENT TIMING CONTEXT'),
        ('rs_gap_reply','MOTOR TEST IDENT RS GAPS'),
        ('time_policy_reply','MOTOR TEST IDENT TIME POLICY'),
        ('encoder_time_reply','MOTOR TEST IDENT ENCODER TIME')):
        line=board.command(cmd);row[key]=line;row['ident_replies'].append(line)
    f=base.hw.fields(row['current_reject_reply'])
    if any(f.get(k)!=v for k,v in dict(REJECT_MAX='0',RUN_LIMIT='0',TOTAL_STOP='0',RUN_STOP='0',RUN_SAT='255').items()):
        raise ValueError('Explicit new L current admission policy required')
    if f.get('FIRST')=='1':
        row['first_reject_reply']=board.command('MOTOR TEST IDENT REJECT ROW')
        row['ident_replies'].append(row['first_reject_reply'])
    axis.encoder.policy(row['encoder_time_reply'])
    t=base.hw.fields(row['time_policy_reply'])
    if any(t.get(k)!=v for k,v in dict(RS_DT_MAX='100',L_DT_MAX='100',L_RS_ADMISSION='1').items()):
        raise ValueError('Explicit L100 policy required')


def extra_decode(row,ram,offset):
    axis.reject.extra_decode(row,ram,offset,total_reject_stop=False,run_reject_stop=False)
    row['ident_timing_failure']=motor_ident_timing_report.decode(ram,offset,max_dt_us=100)
    row['encoder_terminal_saved']=encoder_saved_fault_report.decode_saved(row,ELF)
    stats=dict(zip(('hold_delta','events','skipped','max_skipped'),struct.unpack_from('<4I',ram,offset+1724)))
    wire=base.hw.fields(row['rs_gap_reply']);row['rs_gap_ram']=stats
    if (any(wire.get(k)!=v for k,v in dict(BUDGET='0',TOTAL_STOP='0',RUN_LIMIT='2').items()) or
        any(wire.get(k)!=str(stats[v]) for k,v in
            (('RS_GAPS','events'),('SKIPPED','skipped'),('MAX_GAP','max_skipped')))):
        raise ValueError('Frozen new L gap policy UART/RAM mismatch')
    capture=row['ident_run']
    capture.update(admission_policy='L_RS_ADMISSION_V1',time_policy=base.hw.fields(row['time_policy_reply']),
        rs_gap_admission=dict(RS_GAPS=stats['events'],SKIPPED=stats['skipped'],
            MAX_GAP=stats['max_skipped'],BUDGET=0,RUN_LIMIT=2,TOTAL_STOP=0))
    decoded=run.analysis.decode_uart('\n'.join(row['ident_replies']),axis.AXIS)
    s=row['ident_ram']
    if (decoded['status'],decoded['fault'],len(decoded['rows']))!=(s['status'],s['reason'],s['count']):
        raise ValueError('Frozen terminal UART/RAM mismatch')
    for a,b in zip(decoded['rows'],capture['rows']):
        if any(a[k]!=b[k] for k in ('us','seq','pending_before','mode','status','reason')):
            raise ValueError('Frozen row UART/RAM identity mismatch')
    row['conditional_estimate']=axis.estimate(capture)
    row['qualified_inductance']=False
    rows=capture['rows'];other='iq' if axis.AXIS=='LD' else 'id';current='id' if axis.AXIS=='LD' else 'iq'
    if rows:
        row['observations']=dict(n=len(rows),mean_axis_a=st.mean(r[current] for r in rows),
            mean_cross_axis_a=st.mean(r[other] for r in rows),
            current_span_a=max(r[current] for r in rows)-min(r[current] for r in rows),
            mean_vd_v=st.mean(r['vd'] for r in rows),mean_vq_v=st.mean(r['vq'] for r in rows))


def classify(row):
    if (row.get('operation_error') or any(row.get(k) is not True for k in
        ('final_cpu_halted','final_outputs_off','all_app_private_unchanged','preflight_pass'))):
        return 'SAFETY_OR_TRANSPORT_STOP'
    if row.get('image_sha256')!=SHA or row.get('elf_sha256')!=ELF_SHA:return 'IDENTITY_STOP'
    if row.get('excitation_attempts')!=1 or ' OK IDENT QUEUED ONE_SHOT=1 LOCKED_ACK=1' not in row.get('excitation_ack',''):
        return 'UNKNOWN_ADMISSION_STOP'
    if any(row.get('safe',{}).get(k)!=v for k,v in dict(LATCHED='1',SD='0',MOE='0',FOC='0').items()):
        return 'OUTPUT_STOP'
    guards=row.get('live_guard',{});snap=row.get('snapshot',{});timing=snap.get('timing',{})
    if (any(guards.get(k)!=0 for k in ('cl_flags','cl_fault_valid','adc_fault','foc_fault')) or
        guards.get('encoder_valid')!=1 or snap.get('first_fault',{}).get('valid')!=0 or
        snap.get('cur_confirm',{}).get('fault')!=0 or
        timing.get('deadline_miss')!=0 or timing.get('actual_late_count')!=0):return 'PROTECTION_STOP'
    enc=row.get('encoder_terminal_saved',{})
    if (enc.get('first_fault',{}).get('valid')!=0 or any(enc.get('counters',{}).get(k)!=0 for k in
        ('diagnostic_fault_status','timeouts','dma_errors','schedule_misses','control_stale'))):return 'ENCODER_STOP'
    s=row.get('ident_ram',{});t=row.get('terminal_ident',{})
    if (s.get('mode')!={'LD':2,'LQ':3}[row['axis']] or s.get('used')!=1 or
        s.get('confirmed_locked')!=1 or abs(s.get('current_a',-1)-(0. if row.get('voltage_step') else .1))>1e-6 or
        t.get('STATUS')!=str(s.get('status')) or t.get('REASON')!=str(s.get('reason'))):return 'TERMINAL_MISMATCH_STOP'
    if (s['status'],s['reason']) not in ((3,0),(4,8)):return 'DIAGNOSTIC_SAFETY_STOP'
    if not row.get('ident_run',{}).get('protection_evidence',{}).get('verified'):return 'EVIDENCE_STOP'
    try:run.analysis.guard(row['ident_run'])
    except run.analysis.Insufficient as e:row['quality_error']=str(e);return 'QUALITY_FAILED'
    if row.get('conditional_estimate',{}).get('quality_error'):
        row['quality_error']=row['conditional_estimate']['quality_error'];return 'QUALITY_FAILED'
    return 'CONDITIONAL_FIT'


def install():
    shared.selected.install()
    axis.IMAGE,axis.ELF,axis.SHA,axis.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    run.IMAGE,run.ELF,run.SHA,run.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    run.image=image;run.configure=configure;run.IDENT_SIZE=1740
    run.motion=axis.motion;run.decode_capture=axis.decode
    run.EXTRA_READOUT=extra_readout;run.EXTRA_DECODE=extra_decode
    shared.ELF=ELF;shared.classify=classify
    run.install()


def record(kind,name,**extra):
    return dict(mode=kind,pass_=False,receipt_path=str(TMP/(name+'.json')),
        image_sha256=SHA,elf_sha256=ELF_SHA,baseline_restore_receipt=str(RESTORE),
        steps=[],commands=[],uart=[],samples=[],postflight={},start_attempts=0,excitation_attempts=0,
        automatic_retry=False,automatic_next_stage=False,friction_enabled=True,locked_fixture=True,
        rs_input_ohm=.78,rs_qualified=False,automatic_pi_write=False,**extra)


def comparison(children):
    result=dict(points=[],ld=None,lq=None,rs_input_ohm=.78,rs_qualified=False,
        automatic_pi_write=False,pi_suggestion=None)
    for c in children:
        result['points'].append(dict(axis=c['axis'],repeat=c['repeat'],outcome=c['point_outcome'],
            reason=c.get('ident_ram',{}).get('reason'),n=c.get('ident_ram',{}).get('count'),
            quality_error=c.get('quality_error'),observations=c.get('observations'),
            estimate=c.get('conditional_estimate'),receipt=c['receipt_path'],
            timing=c.get('snapshot',{}).get('timing')))
    # Never average a failed fit into a result. Provisional Rs remains visible.
    for mode in ('LD','LQ'):
        values=[c['conditional_estimate'][mode.lower()]['inductance_h'] for c in children
            if c['axis']==mode and c['point_outcome']=='CONDITIONAL_FIT']
        if values:result[mode.lower()]=dict(mean_h=st.mean(values),std_h=st.pstdev(values),n=len(values),
            qualification='Conditional on assumed Rs=.78 and independently verified latch evidence; not production parameters')
    return result


def execute_batch(parent,name,path,data,point_runner=shared.run_point):
    if not parent.get('powered_no_alarm') or not parent.get('locked_fixture'):
        raise ValueError('Supervised powered locked-fixture confirmation required')
    source,before=base.staged(path,data);children=[]
    parent.update(plan=[dict(axis=m,repeat=r) for m,r in PLAN],points=[],hardware_attempted=True)
    for i,(mode,rep) in enumerate(PLAN):
        child_name=name+'-p%d-%s-r%d'%(i+1,mode.lower(),rep)
        child=record('run',child_name,axis=mode,repeat=rep,powered_no_alarm=True,physical_power_off=False,
            test=dict(mode=mode,axis_step_a=[.05,.1],other_axis_a=0,max_us=104000))
        parent['points'].append(child['receipt_path']);parent['last_point_receipt']=child['receipt_path']
        base.old.prior.checkpoint(parent,'point_%d_intent'%(i+1))
        axis.AXIS=mode;run.COMMAND='MOTOR TEST IDENT %s RS_VALIDATED LOCKED CONFIRM'%mode
        try:point_runner(child,child_name,source,before,data,i==0)
        except BaseException as e:
            child.update(operation_error=str(e),point_outcome='SCRIPT_OR_CAPTURE_STOP',pass_=False)
            if child.get('hardware_attempted') and not child.get('final_cpu_halted'):
                try:base.hw.emergency_off(child,TMP/(child_name+'-failed.bin'))
                except Exception as off:child['cleanup_error']=str(off)
        base.old.prior.checkpoint(child,child.get('point_outcome','STOP'))
        children.append(child);parent['comparison']=comparison(children);parent['completed_points']=len(children)
        base.old.prior.checkpoint(parent,'point_%d_saved'%(i+1))
        print('POINT %d/6 %s repeat%d -> %s'%(i+1,mode,rep,child['point_outcome']),flush=True)
        if child['point_outcome'] not in ('CONDITIONAL_FIT','QUALITY_FAILED'):
            parent['safety_stop']=child['point_outcome'];break
        source=Path(child['final_capture']);before=source.read_bytes()
        if base.old.zero.digest(before)!=child['final_sha256']:raise ValueError('Stopped capture hash mismatch')
        if i+1<len(PLAN):time.sleep(1)  # Outputs off, CPU halted.
    parent['remaining_not_run']=[dict(axis=m,repeat=r) for m,r in PLAN[len(children):]]
    parent['pass_']=len(children)==6 and not parent.get('safety_stop')
    if children:
        parent['final_cpu_halted']=children[-1].get('final_cpu_halted',False)
        parent['final_outputs_off']=children[-1].get('final_outputs_off',False)


def main():
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--stage-off',action='store_true');m.add_argument('--execute-powered',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-locked-fixture',action='store_true')
    p.add_argument('--operator-present-locked-drive-on-no-alarm-05a',action='store_true')
    a=p.parse_args()
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_locked_fixture:p.error('Fresh OFF confirmation required')
    if a.execute_powered and not a.operator_present_locked_drive_on_no_alarm_05a:p.error('Supervised ON confirmation required')
    configure();install();data=image();base.baseline()
    if not (a.stage_off or a.execute_powered or a.restore_b_drive_off):
        print('OFFLINE PASS: pinned L-admission A/B864, fixed six shots; no devices');return 0
    kind='stage' if a.stage_off else 'batch' if a.execute_powered else 'restore'
    name='motor-ident-l-repeat-'+kind+'-'+str(time.time_ns())
    row=record(kind,name,physical_power_off=a.drive_off_locked_fixture,
        powered_no_alarm=a.operator_present_locked_drive_on_no_alarm_05a)
    base.old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.execute_powered:execute_batch(row,name,a.execute_powered,data)
        else:
            parent=json.loads(a.restore_b_drive_off.read_text('utf-8'))
            if (a.restore_b_drive_off.resolve().parent!=TMP.resolve() or parent.get('mode')!='batch' or
                parent.get('image_sha256')!=SHA or parent.get('elf_sha256')!=ELF_SHA):
                raise ValueError('Exact stopped six-point batch receipt required')
            base.restore(row,name,Path(parent['last_point_receipt']),data)
    except BaseException as e:
        row.update(pass_=False,failure=str(e))
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    base.old.prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('COMPLETE: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
