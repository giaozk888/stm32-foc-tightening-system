"""Independently replay the new metric from original OFF CSV; files only."""
import csv
import gzip
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ENV=ROOT/'simulation/dob_simulink/real_five'
OUT=ENV/'feedback_aware_results'


def recovery(rows, start=4.6, tolerance=.008, dwell=.1):
    accepted=None;previous=None;first=None;credit=0.0;expiries=0;expired=False
    held_ms=0.0;fade_ms=0.0
    for row in rows:
        t=float(row['time_s']);now=round(t*1e6)+100020
        source=float(row['observer_source_us']);estimate=float(row['dob_estimate_a'])
        fresh=bool(float(row['dob_valid'])) and math.isfinite(estimate) and 0<=now-source<=2000
        if fresh:
            accepted=(source,estimate);expired=False
        dt=0.0 if previous is None else t-previous;previous=t
        if t<start:continue
        if (not float(row['input_running']) or float(row['simulation_guard_fault']) or
                accepted is None or now-accepted[0]<0 or not 0<=dt<=.002):
            first=None;credit=0.0;continue
        age=now-accepted[0]
        if age>=20000:
            if not expired:expiries+=1;expired=True
            first=None;credit=0.0;continue
        if age>5000:
            fade_ms+=dt*1000;continue
        if not fresh:held_ms+=dt*1000
        if abs(accepted[1]-float(row['load_ground_truth_a']))>tolerance:
            first=None;credit=0.0;continue
        if first is None:first=t;credit=0.0
        else:credit+=dt
        if credit>=dwell-1e-9:
            return dict(recovery_s=first-start,confirmed_s=t-start,held_ms=held_ms,
                        fade_pause_ms=fade_ms,expired_events=expiries)
    return dict(recovery_s=math.nan,confirmed_s=math.nan,held_ms=held_ms,
                fade_pause_ms=fade_ms,expired_events=expiries)


def main():
    with (OUT/'off_recomputed_metrics.csv').open(newline='',encoding='utf-8-sig') as f:
        metrics=list(csv.DictReader(f))
    assert len(metrics)==200
    maximum=0.0;confirmed=[]
    mapping={'recovery_s':'feedback_recovery_s','confirmed_s':'feedback_confirmed_s',
             'held_ms':'recovery_held_ms','fade_pause_ms':'recovery_fade_pause_ms',
             'expired_events':'recovery_expired_events'}
    for m in metrics:
        path=ENV/'results'/f"{m['case_name']}_seed{int(m['seed']):03d}_g0_cap0.025.csv.gz"
        with gzip.open(path,'rt',newline='') as f:
            r=recovery(csv.DictReader(f))
        for key,field in mapping.items():
            difference=abs(r[key]-float(m[field]));assert difference<1e-8,(path,key,r[key],m[field])
            maximum=max(maximum,difference)
        confirmed.append(r['confirmed_s'])
    result=dict(passed=True,trials=200,maximum_metric_abs_delta=maximum,
                confirmed_min_s=min(confirmed),confirmed_max_s=max(confirmed),
                missing_samples_promoted_to_valid=False,hardware_access=False)
    (OUT/'recovery_independent_audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
