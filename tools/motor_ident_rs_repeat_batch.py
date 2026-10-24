"""Fixed nine-point Rs repeat experiment. Quality failures continue; safety stops.

Default files only. No firmware changes. One shot per boot, nine explicitly
planned (50,75,100)mA x3. Each max400ms. No re-send, no Ld/Lq, no PI write.
"""
import argparse
import json
import math
from pathlib import Path
import statistics as st
import time
import zlib
import motor_ident_rs_reject_count_board as selected
import motor_ident_rs75_board as baseline_helper

run=selected.run;base=run.base;TMP=run.TMP
IMAGE,ELF,SHA,ELF_SHA=selected.IMAGE,selected.ELF,selected.SHA,selected.ELF_SHA
RESTORE=TMP/'motor-ident-rs100-restore-1792557122933125000.json'
BASE_SHA='432604c6e6356517b0e4c61d0ed4ce2cfbcc1f1f765975fd4ca5fb86533ac089'
PLAN=tuple((ma,rep) for rep in (1,2,3) for ma in (50,75,100))
image=selected.image


def configure():
    baseline_helper.configure_from(RESTORE,BASE_SHA,856)


def install():
    selected.install();run.configure=configure;run.RESTORE=RESTORE;run.BASE_SHA=BASE_SHA


def record(kind,name,**extra):
    return dict(mode=kind,pass_=False,receipt_path=str(TMP/(name+'.json')),
        image_sha256=SHA,elf_sha256=ELF_SHA,baseline_restore_receipt=str(RESTORE),
        steps=[],commands=[],uart=[],samples=[],postflight={},start_attempts=0,excitation_attempts=0,
        automatic_retry=False,automatic_next_stage=False,friction_enabled=True,
        locked_fixture=True,**extra)


def classify(row):
    """Only a known terminal, clean, fully captured/off result may advance."""
    required=('final_cpu_halted','final_outputs_off','all_app_private_unchanged','preflight_pass')
    if any(row.get(k) is not True for k in required) or row.get('operation_error'):
        return 'SAFETY_OR_TRANSPORT_STOP'
    if row.get('image_sha256')!=SHA or row.get('elf_sha256')!=ELF_SHA:
        return 'IDENTITY_STOP'
    if row.get('excitation_attempts')!=1 or ' OK IDENT QUEUED ONE_SHOT=1 LOCKED_ACK=1' not in row.get('excitation_ack',''):
        return 'UNKNOWN_ADMISSION_STOP'
    if any(row.get('safe',{}).get(k)!=v for k,v in dict(LATCHED='1',SD='0',MOE='0',FOC='0').items()):
        return 'OUTPUT_STOP'
    guards=row.get('live_guard',{});snap=row.get('snapshot',{});timing=snap.get('timing',{})
    if (any(guards.get(k)!=0 for k in ('cl_flags','cl_fault_valid','adc_fault','foc_fault')) or
        guards.get('encoder_valid')!=1 or snap.get('first_fault',{}).get('valid')!=0 or
        snap.get('cur_confirm',{}).get('fault')!=0 or
        timing.get('deadline_miss')!=0 or timing.get('actual_late_count')!=0):
        return 'PROTECTION_STOP'
    enc=row.get('encoder_terminal_saved',{})
    if (enc.get('first_fault',{}).get('valid')!=0 or
        any(enc.get('counters',{}).get(k)!=0 for k in
            ('diagnostic_fault_status','timeouts','dma_errors','schedule_misses','control_stale'))):
        return 'ENCODER_STOP'
    ident=row.get('ident_ram',{});terminal=row.get('terminal_ident',{})
    if (ident.get('mode')!=1 or ident.get('used')!=1 or abs(ident.get('current_a',-1)-row['ma']/1000)>1e-6 or
        terminal.get('STATUS')!=str(ident.get('status')) or terminal.get('REASON')!=str(ident.get('reason'))):
        return 'TERMINAL_MISMATCH_STOP'
    if (ident['status'],ident['reason']) not in ((3,0),(4,8)):
        # Motion/voltage/nonfinite or any other diagnostic safety exit stops.
        return 'DIAGNOSTIC_SAFETY_STOP'
    if not row.get('ident_run',{}).get('protection_evidence',{}).get('verified'):
        return 'EVIDENCE_STOP'
    try:row['qualified_point']=run.analysis.qualify_rs_point(row['ident_run'])
    except run.analysis.Insufficient as e:
        row['quality_error']=str(e);return 'QUALITY_FAILED'
    return 'QUALIFIED'


def run_point(row,name,source,before,data,first):
    if not row.get('powered_no_alarm'):raise ValueError('Supervised powered batch required')
    if not first:
        meta=base.old.zero.latest_meta(before)
        if meta[2:5]!=(1,0,0) or before[0x8000:0x8000+len(data)]!=data:
            raise ValueError('Next segment requires exact clean confirmed A capture')
    port=base.support.support.open_port();uart=base.TokenConsole(port,row)
    try:
        row['hardware_attempted']=True;base.old.prior.checkpoint(row,'segment_boot_intent')
        commands=[*base.old.zero.off_gate(),
            *base.hw.full_compare_commands(TMP/(name+'-before.bin'),source),
            'reset halt',*base.hw.off_commands()]
        if first:commands+=base.hw.write_mailbox(base.mailbox(2,2,1,len(data),zlib.crc32(data)))
        commands+=['reset run','shutdown']
        base.hw.debug(row,commands)
        base.old.prior.wait_health_confirmation(uart,row,base.hw.fields)
        if not any('MOTOR_IDENT_DIAGNOSTIC: LOCK ROTOR' in x for x in uart.lines):
            raise RuntimeError('Identification marker absent')
        row['zero']=base.old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        row['profile']=base.profile(uart.query('MOTOR TEST PROFILE'))
        row['filter']=base.filter_profile(uart.query('MOTOR TEST FILTER'))
        base.old.prior.wait_timing(uart,row);row['preflight_pass']=True
        port.close();board=base.TokenRecordedBoard('COM5',row)
        try:run.motion(board,row)
        finally:board.close()
    except Exception as e:
        row['operation_error']=str(e)
    finally:
        if port.is_open:
            try:row['safe_ack']=uart.query('ANALOG SAFE',.6)
            except Exception as e:row['stop_error']=str(e)
            port.close()
        if row.get('hardware_attempted'):
            base.old.capture_stopped(row,name,before,elf=ELF)
            if row.get('outputs',{}).get('VTOR')==0x08008000:
                try:run.decode_capture(row)
                except run.analysis.Insufficient as e:row['quality_error']=str(e)
    row['point_outcome']=classify(row)
    row['pass_']=row['point_outcome']=='QUALIFIED'
    base.old.prior.checkpoint(row,row['point_outcome'])


def comparison(children):
    summary=dict(points=[],by_current={},qualified_rs=None,automatic_pi_write=False)
    qualified=[]
    for r in children:
        item=dict(ma=r['ma'],repeat=r['repeat'],outcome=r.get('point_outcome','NOT_RUN'),
            receipt=r['receipt_path'],quality_error=r.get('quality_error'),
            observation=r.get('single_point_observation'),timing=r.get('snapshot',{}).get('timing'))
        rows=r.get('ident_run',{}).get('rows',[])
        if len(rows)>=4:
            n=len(rows)//4
            item['quality_metrics']=dict(id_std_a=st.pstdev(x['id'] for x in rows),
                first_last_delta_a=st.mean(x['id'] for x in rows[-n:])-st.mean(x['id'] for x in rows[:n]),
                max_electrical_delta_deg=math.degrees(max(abs(math.remainder(x['angle']-rows[0]['angle'],2*math.pi)) for x in rows)))
        summary['points'].append(item)
        if r.get('point_outcome')=='QUALIFIED':qualified.append(r['ident_run'])
    for ma in (50,75,100):
        group=[r for r in children if r['ma']==ma]
        obs=[r['single_point_observation'] for r in group if r.get('single_point_observation')]
        stats=dict(attempted=len(group),qualified=sum(r.get('point_outcome')=='QUALIFIED' for r in group))
        if obs:
            for key in ('mean_id_a','mean_iq_a','mean_vd_v'):
                v=[o[key] for o in obs];stats[key]=dict(mean=st.mean(v),std=st.pstdev(v),n=len(v))
        stats['qualification']='All captured observations retained; group averages are descriptive, not a quality bypass'
        summary['by_current'][str(ma)]=stats
    try:summary['qualified_rs']=run.analysis.fit_rs(qualified)
    except run.analysis.Insufficient as e:summary['rs_error']=str(e)
    summary['round_fits']=[]
    for rep in (1,2,3):
        entry=dict(repeat=rep)
        group=[r['ident_run'] for r in children if r['repeat']==rep and r.get('point_outcome')=='QUALIFIED']
        try:entry['fit']=run.analysis.fit_rs(group)
        except run.analysis.Insufficient as e:entry['error']=str(e)
        summary['round_fits'].append(entry)
    return summary


def execute_batch(parent,name,path,data,point_runner=run_point):
    if not parent.get('powered_no_alarm') or not parent.get('locked_fixture'):
        raise ValueError('Fresh powered supervised fixed-fixture confirmation required')
    source,before=base.staged(path,data);children=[]
    parent['points']=[];parent['plan']=[dict(ma=ma,repeat=rep) for ma,rep in PLAN]
    parent['explicit_planned_sequence']=True
    parent['hardware_attempted']=True
    for index,(ma,rep) in enumerate(PLAN):
        child_name=name+'-p%d-rs%d-r%d'%(index+1,ma,rep)
        child=record('run',child_name,ma=ma,repeat=rep,powered_no_alarm=True,physical_power_off=False,
            test=dict(mode='RS',id_ref_a=ma/1000,iq_ref_a=0,max_us=400000))
        parent['points'].append(child['receipt_path']);parent['last_point_receipt']=child['receipt_path']
        base.old.prior.checkpoint(parent,'point_%d_intent'%(index+1))
        run.RS_MA=ma;run.COMMAND='MOTOR TEST IDENT RS %d LOCKED CONFIRM'%ma
        try:point_runner(child,child_name,source,before,data,index==0)
        except BaseException as e:
            child.update(operation_error=str(e),point_outcome='SCRIPT_OR_CAPTURE_STOP',pass_=False)
            if child.get('hardware_attempted') and not child.get('final_cpu_halted'):
                try:base.hw.emergency_off(child,TMP/(child_name+'-failed.bin'))
                except Exception as off:child['cleanup_error']=str(off)
        base.old.prior.checkpoint(child,child.get('point_outcome','STOP'))
        children.append(child);parent['comparison']=comparison(children)
        parent['completed_points']=len(children)
        base.old.prior.checkpoint(parent,'point_%d_saved'%(index+1))
        print('POINT %d/9: %dmA repeat%d -> %s'%(index+1,ma,rep,child['point_outcome']),flush=True)
        if child['point_outcome'] not in ('QUALIFIED','QUALITY_FAILED'):
            parent['safety_stop']=child['point_outcome'];break
        source=Path(child['final_capture']);before=source.read_bytes()
        # Confirm identity before any next reset, not just a mutable JSON flag.
        if base.old.zero.digest(before)!=child['final_sha256']:
            raise ValueError('Prior stopped capture hash mismatch')
        if index+1<len(PLAN):time.sleep(1.0)  # Outputs remain OFF, CPU halted.
    parent['remaining_not_run']=[dict(ma=m,repeat=r) for m,r in PLAN[len(children):]]
    parent['pass_']=len(children)==9 and not parent.get('safety_stop')
    parent['all_quality_pass']=parent['pass_'] and all(c['point_outcome']=='QUALIFIED' for c in children)
    if children:
        parent['final_cpu_halted']=children[-1].get('final_cpu_halted',False)
        parent['final_outputs_off']=children[-1].get('final_outputs_off',False)


def main():
    p=argparse.ArgumentParser(description=__doc__);mode=p.add_mutually_exclusive_group()
    mode.add_argument('--stage-off',action='store_true')
    mode.add_argument('--execute-powered',type=Path)
    mode.add_argument('--restore-b-drive-off',type=Path,help='This batch parent receipt')
    p.add_argument('--drive-off-locked-fixture',action='store_true')
    p.add_argument('--operator-present-locked-drive-on-no-alarm-05a',action='store_true')
    a=p.parse_args()
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_locked_fixture:p.error('Fresh OFF confirmation required')
    if a.execute_powered and not a.operator_present_locked_drive_on_no_alarm_05a:p.error('Supervised ON confirmation required')
    install();configure();run.install();data=image();base.baseline()
    if not (a.stage_off or a.execute_powered or a.restore_b_drive_off):
        print('OFFLINE PASS: exact unchanged A/B856, fixed 9-point Rs batch; no devices');return 0
    kind='stage' if a.stage_off else 'batch' if a.execute_powered else 'restore'
    name='motor-ident-rs-repeat-'+kind+'-'+str(time.time_ns())
    row=record(kind,name,physical_power_off=a.drive_off_locked_fixture,
        powered_no_alarm=a.operator_present_locked_drive_on_no_alarm_05a)
    base.old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.execute_powered:execute_batch(row,name,a.execute_powered,data)
        else:
            parent=json.loads(a.restore_b_drive_off.read_text('utf-8'))
            if (a.restore_b_drive_off.resolve().parent!=TMP.resolve() or parent.get('mode')!='batch' or
                parent.get('image_sha256')!=SHA or parent.get('elf_sha256')!=ELF_SHA or
                not parent.get('last_point_receipt')):raise ValueError('Exact stopped batch receipt required')
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
