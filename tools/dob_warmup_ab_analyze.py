"""Audit saved warmup trials and report descriptive comparisons, no devices."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics
import zlib
import dob_warmup_ab_board as b

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def analyze_run(path):
    r=json.loads(path.read_text());assert r['pass_'] and r['start_attempts']==1
    assert all(r[k] for k in ('final_outputs_off','final_cpu_halted','all_app_private_unchanged'))
    assert r['actual_tau_ram']==r['warmup_tau_requested'] and r['image_sha256']==b.SHA and r['elf_sha256']==b.ELF_SHA
    raw=Path(r['final_capture']).read_bytes();assert digest(r['final_capture'])==r['final_sha256']
    assert raw[0x8000:0x8000+b.SIZE]==b.image()
    assert zlib.crc32(raw[0x40000:0x40000+227964])==627317606
    ram=Path(r['ram_capture']).read_bytes();assert digest(r['ram_capture'])==r['trend_capture']['ram_sha256']
    h,points,events,cov=b.continuous.decode_capture(ram,b.base.symbols(b.ELF))
    assert h==r['trend_capture']['header'] and cov['full_observed_run']
    for info in r['trend_capture']['files'].values():assert digest(info['csv'])==info['sha256']
    n=h['observations'];assert n==r['saturation_audit']['samples']==r['feedback_capture']['updates']
    audit=r['saturation_audit'];f=r['accel_ff_ram_stats'];tim=r['snapshot']['timing']
    assert tim['deadline_miss']==0 and tim['actual_late_count']==0
    gaps=[]
    for e in events:
        if e['event']!='quality_reset':continue
        def subsequent(q):return 0<((q['timestamp_us']-e['timestamp_us'])&0xffffffff)<0x80000000
        level=next((q for q in events if subsequent(q) and q['event']=='level_changed' and q['class_valid']),None)
        trend=next((q for q in events if subsequent(q) and q['event']=='trend_changed' and q['trend_valid']),None)
        gaps.append(dict(begin_s=e['time_from_run_start_s'],
            interval_present=bool(level and trend),
            level_gap_ms=((level['timestamp_us']-e['timestamp_us'])&0xffffffff)*.001 if level else None,
            trend_gap_ms=((trend['timestamp_us']-e['timestamp_us'])&0xffffffff)*.001 if trend else None))
    # Whole-RUN event counter, event ring may overwrite. Never infer zero resets
    # from an overwritten event list; retain counter and completeness separately.
    observer_stats=b.base.hw.fields(r['postflight']['MOTOR TEST MECH DOB STATS'])
    assert int(observer_stats['N'])==n and 0<=int(observer_stats['GOOD'])<=n
    metrics=dict(warmup_frames=audit['warmup_frames'],
        estimator_valid_percent=100*int(observer_stats['GOOD'])/n,
        classifier_input_valid_percent=100*cov['classifier']['accepted']/n,
        feedback_valid_percent=100*r['feedback_capture']['valid_updates']/n,
        quality_resets=cov['classifier']['resets'],
        iq_limited_frames=audit['iq_limited'],source_input_resets=audit['input_resets'],
        current_skips=audit['current_skips'],speed_peak_rpm=f['command_rpm']+f['overshoot_rpm'],
        overshoot_rpm=f['overshoot_rpm'],iq_peak_a=f['iq_peak_a'],iq_saturation_ms=f['saturation_s']*1000,
        compensation_peak_ma=r['feedback_capture']['peak_a']*1000,
        accel_mae_rpm=f['accel_error_integral']/f['accel_time_s'] if f['accel_time_s'] else None,
        foc_max_us=tim['wall_max_us'],deadline_miss=tim['deadline_miss'],ccr_late=tim['actual_late_count'])
    return dict(source=str(path),source_sha256=digest(path),tau=r['actual_tau_ram'],metrics=metrics,
        events_complete=cov['event_timeline_complete'],gaps=gaps,
        outcome=r['terminal_status']['OUTCOME'],total_samples=n,
        records=r['trend_capture']['files'],tightening_success=r['result']['tightening_ok'])

def summarize(batch):
    parent=json.loads(batch.read_text());assert parent['pass_'] and parent['schedule']==list(b.SCHEDULE)
    rows=[analyze_run(Path(p)) for p in parent['runs']]
    assert [r['tau'] for r in rows]==list(b.SCHEDULE)
    groups={}
    for tau in (5,3):
        rr=[r for r in rows if r['tau']==tau];stats={}
        for key in rows[0]['metrics']:
            values=[r['metrics'][key] for r in rr if r['metrics'][key] is not None]
            stats[key]=dict(n=len(values),mean=statistics.mean(values) if values else None,
                sd=statistics.stdev(values) if len(values)>1 else None)
        # A wrapped ring loses early events, but the retained timeline can
        # still contain every reset and both recovery endpoints. Check this.
        complete_resets=all(len(r['gaps'])==r['metrics']['quality_resets'] and
            all(g['interval_present'] for g in r['gaps']) for r in rr)
        stats['recovery_intervals_complete']=complete_resets
        for key in ('level_gap_ms','trend_gap_ms'):
            values=[g[key] for r in rr for g in r['gaps'] if g['interval_present'] and g[key] is not None] if complete_resets else []
            stats[key]=dict(n=len(values),mean=statistics.mean(values) if values else None,
                sd=statistics.stdev(values) if len(values)>1 else None)
        groups[str(tau)]=stats
    return dict(evidence_audit='PASS',batch=str(batch),runs=rows,groups=groups,
        physical_load_truth_available=False,paired_force_matched=False,
        note='n=2 per gate; hand brake load uncontrolled. Descriptive validity/warmup comparison, not verified disturbance accuracy or load rejection. Warmup-frame totals are epochs, not accumulated valid dt or a single recovery delay.')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('batch',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--restore',type=Path);a=p.parse_args()
    result=summarize(a.batch)
    if a.restore:
        r=json.loads(a.restore.read_text());last=json.loads(Path(result['runs'][-1]['source']).read_text())
        assert r['mode']=='restore' and all(r[k] for k in ('pass_','final_outputs_off','final_cpu_halted','all_app_private_unchanged','b_application_not_run'))
        assert r['motor_commands']==0 and r['outputs']['VTOR']==0x08040000
        before=Path(last['final_capture']).read_bytes();after=Path(r['final_capture']).read_bytes()
        assert digest(r['final_capture'])==r['final_sha256']
        assert before[:0x7e800]==after[:0x7e800] and before[0x7f800:]==after[0x7f800:]
        assert zlib.crc32(after[0x40000:0x40000+227964])==627317606
        result['B_restore_audit']=dict(result='PASS',receipt=str(a.restore),sha256=digest(a.restore),metadata=r['metadata'])
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    with a.output.with_suffix('.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=['run','tau',*result['runs'][0]['metrics']]);writer.writeheader()
        for i,r in enumerate(result['runs'],1):writer.writerow(dict(run=i,tau=r['tau'],**r['metrics']))
    print(json.dumps(result['groups'],indent=2))
if __name__=='__main__':main()
