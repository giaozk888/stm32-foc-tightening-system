"""Six supervised 50mV voltage shots, PI bypassed. Files-only by default.

No voltage escalation or automatic retry. Quality failures continue only after
known terminal/output closure; genuine protection/unknown ACK stops the batch.
"""
import argparse
import json
from pathlib import Path
import re
import struct
import time
import motor_ident_l_repeat_batch as previous

axis=previous.axis;run=previous.run;base=previous.base;TMP=previous.TMP
IMAGE=base.old.ROOT/'foc2_app_a/build/MotorParameterIdentificationVoltageStepDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='e15a2ce8da9ad87752065a40521c4ad55ecfebe4fd9300245060d4499d72228c'
ELF_SHA='bbe64f7fc04a28e51cd8ea2433a148c1d94b8ba16eb98cd4053eb0c77dd306a7'
RESTORE=TMP/'motor-ident-l-repeat-restore-1792559974775747900.json'
BASE_SHA='f7bba7062087ef436cbb83a112b521c83e27f000b25429cb59e51697c2c4e051'
OLD_SHA=previous.SHA


def image():
    data=previous.shared.selected.previous.pinned_image(IMAGE,SHA,ELF_SHA,214716,
        ('-DFOC_IDENT_VOLTAGE_STEP_DIAG=1','-DFOC_IDENT_L_RS_ADMISSION_ENABLE=1'))
    if b'PI_BYPASS=1 STEP_MV=50' not in data or b'RAW_FRAME_ABI=1' not in data:
        raise ValueError('Exclusive 50mV raw voltage image required')
    return data


def configure():
    run.ORIGINAL_CONFIGURE(base.ROOT_RESTORE);root=base.baseline()
    r=json.loads(RESTORE.read_text('utf-8'));capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or r.get('image_sha256')!=OLD_SHA or
        r.get('motor_commands')!=0 or any(r.get(k) is not True for k in
            ('pass_','all_app_private_unchanged','b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Exact preserved B868 restore required')
    raw=capture.read_bytes();meta=base.old.zero.latest_meta(raw);off=r.get('outputs',{})
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=BASE_SHA or r.get('final_sha256')!=BASE_SHA or
        list(meta)!=r.get('metadata') or meta[2:10]!=(2,0,0,868,215156,4121158908,227964,627317606) or
        base.old.zero.digest(raw[0x8000:0x8000+215156])!=OLD_SHA or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or off.get('VTOR')!=0x08040000 or
        not off.get('DHCSR',0)&0x20000 or off.get('SD',0x40)&0x40 or off.get('BDTR',0xC000)&0xC000 or off.get('CCER',1)):
        raise ValueError('B868 image/B/boot/private/output mismatch')
    base.BASE=capture;base.BASE_SHA=BASE_SHA;base.EXPECT_META=meta;base.BASE_RESTORE_RECEIPT=RESTORE.resolve()


def policy(reply):
    f=base.hw.fields(reply)
    if any(f.get(k)!=v for k,v in dict(VOLTAGE_STEP='1',PI_BYPASS='1',STEP_MV='50',
        STEP_US='100000',END_US='104000',RAW_FRAME_ABI='1').items()):
        raise ValueError('Explicit fixed 50mV/no-PI voltage policy required')
    return f


def motion(board,row):
    row['voltage_policy_pre']=policy(board.command('MOTOR TEST IDENT VOLTAGE POLICY'))
    row['encoder_time_pre']=axis.encoder.policy(board.command('MOTOR TEST IDENT ENCODER TIME'))
    axis.ORIGINAL_MOTION(board,row,ident_mode=axis.AXIS,voltage_step=True)


def extra_readout(board,row):
    previous.extra_readout(board,row)
    reply=board.command('MOTOR TEST IDENT VOLTAGE POLICY')
    row['voltage_policy_reply']=reply;row['ident_replies'].append(reply)
    policy(reply)


def decode_wire(text):
    rows={}
    for line in text.splitlines():
        if ' OK MID K=' not in ' '+line:continue
        f={k:int(v) for k,v in re.findall(r'\b([A-Z_]+)=(-?\d+)',line)}
        for k in ('RU','RV','TCNT','TDIR','US','SEQ','PSEQ','M','S','F','D','Q','VD','VQ','A','RPM'):
            if k not in f:raise ValueError('Explicit raw voltage frame required')
        if f['K'] in rows and rows[f['K']]!=f:raise ValueError('Mixed UART raw voltage rows')
        rows[f['K']]=f
    if sorted(rows)!=list(range(len(rows))):raise ValueError('Missing UART row')
    return [rows[k] for k in sorted(rows)]


def extra_decode(row,ram,offset):
    keys='us seq pending_before raw_u raw_v tail_cnt tail_flags id iq vd vq angle speed mode status reason reserved'.split()
    first=dict(zip(keys,struct.unpack_from('<3I4H6f4B',ram,offset+1596)))
    vals=struct.unpack_from('<2I2H4B',ram,offset+1644)
    stats=dict(zip(('reject','good','raw_u','raw_v','run','max_run','sample_rejected','first_valid'),vals))
    row['current_admission_ram']=stats
    row['first_current_reject']=first if stats['first_valid'] else None
    r=row['ident_run'];r.update(current_admission=dict(REJECT=stats['reject'],GOOD=stats['good'],
        MAX_RUN=stats['max_run'],REJECT_MAX=0,RUN_LIMIT=0,TOTAL_STOP=0,RUN_STOP=0,RUN_SAT=255),
        admission_policy='L_RS_ADMISSION_V1',time_policy=base.hw.fields(row['time_policy_reply']),
        voltage_step_policy=policy(row['voltage_policy_reply']))
    wire=base.hw.fields(row['current_reject_reply'])
    if any(wire.get(k)!=str(stats[v]) for k,v in
        (('REJECT','reject'),('GOOD','good'),('MAX_RUN','max_run'),('FIRST','first_valid'))):
        raise ValueError('Frozen reject counters mismatch')
    gap=dict(zip(('hold_delta','events','skipped','max_skipped'),struct.unpack_from('<4I',ram,offset+1724)))
    row['rs_gap_ram']=gap;g=base.hw.fields(row['rs_gap_reply'])
    if (any(g.get(k)!=str(gap[v]) for k,v in (('RS_GAPS','events'),('SKIPPED','skipped'),('MAX_GAP','max_skipped'))) or
        any(g.get(k)!=v for k,v in dict(BUDGET='0',TOTAL_STOP='0',RUN_LIMIT='2').items())):
        raise ValueError('Frozen voltage diagnostic gap mismatch')
    r['rs_gap_admission']=dict(RS_GAPS=gap['events'],SKIPPED=gap['skipped'],MAX_GAP=gap['max_skipped'],BUDGET=0,RUN_LIMIT=2,TOTAL_STOP=0)
    row['ident_timing_failure']=previous.motor_ident_timing_report.decode(ram,offset,max_dt_us=100)
    row['encoder_terminal_saved']=previous.encoder_saved_fault_report.decode_saved(row,ELF)
    decoded=decode_wire('\n'.join(row['ident_replies']))
    if len(decoded)!=len(r['rows']):raise ValueError('Frozen voltage frame count mismatch')
    for a,b in zip(decoded,r['rows']):
        for k,v in dict(US='us',SEQ='seq',PSEQ='pending_before',RU='raw_u',RV='raw_v',TCNT='tail_cnt',TDIR='tail_flags',M='mode',S='status',F='reason').items():
            if a[k]!=b[v]:raise ValueError('Frozen UART/RAM raw voltage identity mismatch')
        for k,v,scale in (('D','id',1e-6),('Q','iq',1e-6),('VD','vd',1e-6),('VQ','vq',1e-6),('A','angle',1e-6),('RPM','speed',1e-3)):
            if abs(a[k]*scale-b[v])>1.01*scale:raise ValueError('Frozen UART/RAM float mismatch')
        if b['id_ref']!=0 or b['iq_ref']!=0:raise ValueError('PI bypass current reference must be zero')
        expected=.05 if b['us']>=100000 else 0.
        vd,vq=(expected,0.) if row['axis']=='LD' else (0.,expected)
        if abs(b['vd']-vd)>1e-7 or abs(b['vq']-vq)>1e-7:
            raise ValueError('Non-fixed voltage output; cannot claim no PI dynamics')
    row['conditional_estimate']=axis.estimate(r)
    row['qualified_inductance']=False
    if r['rows']:
        import statistics as st
        current,other=('id','iq') if row['axis']=='LD' else ('iq','id')
        rows=r['rows']
        row['observations']=dict(n=len(rows),mean_axis_a=st.mean(x[current] for x in rows),
            mean_cross_axis_a=st.mean(x[other] for x in rows),current_span_a=max(x[current] for x in rows)-min(x[current] for x in rows),
            mean_vd_v=st.mean(x['vd'] for x in rows),mean_vq_v=st.mean(x['vq'] for x in rows))


def decode(row):
    axis.ORIGINAL_DECODE(row,ident_mode=axis.AXIS,voltage_step=True)


def point(row,name,source,before,data,first):
    row.update(voltage_step=True,pi_bypassed=True,
        test=dict(mode=row['axis']+'V',step_mv=50,step_us=100000,max_us=104000,nonzero_max_us=4000))
    run.COMMAND='MOTOR TEST IDENT %sV 50MV LOCKED CONFIRM'%row['axis']
    previous.shared.run_point(row,name,source,before,data,first)


def install():
    previous.install()
    previous.RESTORE,previous.BASE_SHA=RESTORE,BASE_SHA
    previous.IMAGE,previous.ELF,previous.SHA,previous.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    axis.IMAGE,axis.ELF,axis.SHA,axis.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    run.IMAGE,run.ELF,run.SHA,run.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    run.image=image;run.configure=configure;run.motion=motion;run.decode_capture=decode
    run.EXTRA_READOUT=extra_readout;run.EXTRA_DECODE=extra_decode
    previous.shared.ELF=ELF;run.install()


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
        print('OFFLINE PASS: fixed six 50mV voltage shots, no PI, preserved B868; no devices');return 0
    kind='stage' if a.stage_off else 'batch' if a.execute_powered else 'restore'
    name='motor-ident-voltage-'+kind+'-'+str(time.time_ns())
    row=previous.record(kind,name,physical_power_off=a.drive_off_locked_fixture,
        powered_no_alarm=a.operator_present_locked_drive_on_no_alarm_05a,voltage_step=True,pi_bypassed=True)
    row['baseline_restore_receipt']=str(RESTORE);base.old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.execute_powered:previous.execute_batch(row,name,a.execute_powered,data,point_runner=point)
        else:
            parent=json.loads(a.restore_b_drive_off.read_text('utf-8'))
            if (a.restore_b_drive_off.resolve().parent!=TMP.resolve() or parent.get('mode')!='batch' or
                parent.get('image_sha256')!=SHA or parent.get('elf_sha256')!=ELF_SHA):raise ValueError('Exact stopped voltage batch required')
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
