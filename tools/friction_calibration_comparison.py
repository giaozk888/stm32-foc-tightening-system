"""Offline comparison of ALL saved points, including non-motion failures.

Uses actual FCAL aggregates plus explicitly sparse 10Hz FRC logs. Does not fit
failed windows, alter the live batch or access a device.
"""
import argparse
import json
import math
from pathlib import Path
import re
import statistics
import friction_calibration_report as identification


def frames(row):
    result={}
    for d in row.get('tokenized_decoded',[]):
        text=d['decoded'];match=re.search(r'\bFRC ([RCI]) seq=(\d+)\b',text)
        if not match:continue
        values={k:float(v) for k,v in re.findall(r'\b([a-z_]+)=([-+]?[0-9]+(?:\.[0-9]+)?)',text)}
        if not all(math.isfinite(x) for x in values.values()):raise ValueError('Nonfinite FRC log')
        key=int(match[2]);frame=result.setdefault(key,{'seq':key,'parts':set()})
        frame['parts'].add(match[1]);frame.update(values)
    return [v for _,v in sorted(result.items()) if v['parts']=={'R','C','I'}]


def summarize(row):
    s=row['calibration_point'];rpm=row.get('rpm',s['rpm']);all_frames=frames(row)
    plateau=[f for f in all_frames if abs(f['command']-rpm)<.001 and
        abs(f['speed_ref']-rpm)<.001 and abs(f['accel_ref'])<=.001]
    def mean(key):return statistics.mean(f[key] for f in plateau) if plateau else None
    net=s['net_travel'];duration=s['valid_s']
    fallback=('NOT_ADMITTED' if re.fullmatch(r'\d+ ERR FCAL NOT_READY',row.get('failure','')) and s.get('seen')==0 else
        'NO_ROTATION' if row.get('snapshot',{}).get('first_fault',{}).get('fault_reason')==7 else 'UNKNOWN')
    return dict(rpm=rpm,repeat=row['repeat'],outcome=row.get('point_outcome',fallback),
        qualified=bool(s['passed']),driven_observations=s['seen'],valid_s=duration,
        valid=s['valid'],reject=s['reject'],net_travel_deg=net,total_abs_travel_deg=s['abs_travel'],
        travel_ratio=s['abs_travel']/abs(net) if abs(net)>1e-6 else None,
        candidate_window_mean_iq_a=s['iq_sum']/duration if duration>0 else None,
        candidate_window_mean_iqref_a=s['iq_ref_sum']/duration if duration>0 else None,
        candidate_window_mean_id_a=s['id_sum']/duration if duration>0 else None,
        candidate_window_mean_abs_id_a=s['abs_id_sum']/duration if duration>0 else None,
        sparse_plateau_samples=len(plateau),sparse_plateau_speed_mean_rpm=mean('speed_meas'),
        sparse_plateau_speed_mae_rpm=statistics.mean(abs(f['speed_meas']-rpm) for f in plateau) if plateau else None,
        sparse_plateau_iq_mean_a=mean('iq_meas'),sparse_plateau_iqref_mean_a=mean('iq_ref'),
        timing=row['snapshot']['timing'],fault=row['snapshot']['first_fault'],
        receipt=row.get('receipt_path'),
        caution='10Hz plateau means are sample averages, not full-rate peaks or a qualified friction-current estimate')


def compare(batch):
    rows=[]
    for path in batch['points']:
        row=json.loads(Path(path).read_text('utf-8'))
        # Some historical receipts predate classification, never modify them.
        rows.append(summarize(row))
    groups=[]
    for rpm in batch.get('plan',{}).get('speeds_rpm',(40,80,120,240,-40,-80,-120,-240)):
        points=[r for r in rows if r['rpm']==rpm]
        if not points:continue
        def avg(key):
            measured=[p[key] for p in points if p[key] is not None]
            return statistics.mean(measured) if measured else None
        groups.append(dict(rpm=rpm,attempts=len(points),qualified=sum(p['qualified'] for p in points),
            outcomes={o:sum(p['outcome']==o for p in points) for o in sorted({p['outcome'] for p in points})},
            sparse_plateau_speed_mean_rpm=avg('sparse_plateau_speed_mean_rpm'),
            sparse_plateau_speed_mae_rpm=avg('sparse_plateau_speed_mae_rpm'),
            sparse_plateau_iq_mean_a=avg('sparse_plateau_iq_mean_a'),
            sparse_plateau_iqref_mean_a=avg('sparse_plateau_iqref_mean_a'),
            candidate_window_mean_iq_a=avg('candidate_window_mean_iq_a'),
            candidate_window_mean_id_a=avg('candidate_window_mean_id_a'),
            net_travel_mean_deg=avg('net_travel_deg'),total_abs_travel_mean_deg=avg('total_abs_travel_deg')))
    fitted=identification.report(batch['calibration_points'],batch.get('plan',{}).get('speeds_rpm'))
    sensitivity=identification.admitted_window_sensitivity(batch['calibration_points'],
        batch.get('plan',{}).get('speeds_rpm'))
    return dict(acquisition_complete=batch.get('acquisition_complete',False),point_count=len(rows),
        points=rows,groups=groups,friction_fit=fitted['fit'],friction_identification=fitted,
        exploratory_admitted_window_sensitivity=sensitivity,
        max_foc_us=max((r['timing']['wall_max_us'] for r in rows),default=None),
        deadline_miss=sum(r['timing']['deadline_miss'] for r in rows),
        actual_late_count=sum(r['timing']['actual_late_count'] for r in rows),
        minimum_ccr_margin_us=min((r['timing']['actual_margin_min_us'] for r in rows),default=None),
        automatic_parameter_write=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('batch',type=Path)
    a=p.parse_args();print(json.dumps(compare(json.loads(a.batch.read_text('utf-8'))),indent=2))
