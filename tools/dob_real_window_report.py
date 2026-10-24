"""Read actual saved raw/Flash/RAM only; never estimates load ground truth."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics as st

def analyze(path):
    receipt=json.loads(path.read_text())
    capture=receipt['raw_capture'];csv_path=Path(capture['csv'])
    if hashlib.sha256(csv_path.read_bytes()).hexdigest()!=capture['csv_sha256']:
        raise ValueError('Raw CSV hash changed')
    for field,key in [('ram_capture','ram_sha256'),('final_capture','final_sha256')]:
        expected=capture[key] if key in capture else receipt[key]
        if hashlib.sha256(Path(receipt[field]).read_bytes()).hexdigest()!=expected:raise ValueError(field+' hash')
    with csv_path.open(newline='') as f:rows=list(csv.DictReader(f))
    def values(key):return [float(r[key]) for r in rows]
    def summary(v):return dict(n=len(v),mean=st.mean(v),sd=st.stdev(v),min=min(v),max=max(v),rms=math.sqrt(st.mean(x*x for x in v)))
    def jumps(v):return [b-a for a,b in zip(v,v[1:])]
    id_a,iq_a=values('id_raw_a'),values('iq_raw_a')
    adjacent=[max(abs(a),abs(b)) for a,b in zip(jumps(id_a),jumps(iq_a))]
    events=[]
    for i in range(1,len(rows)):
        if adjacent[i-1]>.2 or rows[i]['lpf_updated']=='False':
            events.append(dict(index=i,time_us=int(rows[i]['timestamp_us']),id_a=id_a[i],iq_a=iq_a[i],
                delta_id_a=id_a[i]-id_a[i-1],delta_iq_a=iq_a[i]-iq_a[i-1],
                lpf_updated=rows[i]['lpf_updated']=='True',dob_valid=rows[i]['dob_valid']=='True',
                dob_status=int(rows[i]['dob_status'])))
    report=dict(receipt=str(path.resolve()),samples=len(rows),header=capture['header'],
        quality_pass=capture['quality_pass'],id_a=summary(id_a),iq_a=summary(iq_a),
        speed_rpm=summary(values('mechanical_rpm')),observed_age_us=summary(values('observed_age_us')),
        min_dt_us=min(values('dt_us')[1:]),max_dt_us=max(values('dt_us')[1:]),
        adjacent_pair_jump_gt200ma=sum(x>.2 for x in adjacent),events=events,
        dob_valid_samples=sum(r['dob_valid']=='True' for r in rows),
        lpf_updated_samples=sum(r['lpf_updated']=='True' for r in rows),
        capture_wall_max_us=capture['header']['max_cycles']/170,
        capture_cpu_time_isolated=False,load_ground_truth_available=False,
        note='Raw Id/Iq excursions are observations, not proof of measurement errors or applied load torque. Fixed192ms window only; no natural rare-event rate claim.')
    output=path.with_suffix('.window-report.json')
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('receipt',type=Path)
    print(json.dumps(analyze(p.parse_args().receipt),indent=2))
