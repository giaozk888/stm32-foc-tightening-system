"""Curves from actual raw CSV and formal saved Simulink CSV only."""
import csv
import gzip
import json
from pathlib import Path
from plot_dob_empirical import panel

ROOT=Path(__file__).resolve().parents[1];ENV=ROOT/'simulation/dob_simulink/real_five';OUT=ENV/'results'

def main():
    manifest=json.loads((ENV/'data/manifest.json').read_text())
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1900" height="940">',
         '<rect width="100%" height="100%" fill="white"/><g font-family="Arial, sans-serif" fill="#172a3a">',
         '<text x="24" y="28" font-size="21" font-weight="bold">Five actual motor windows | 240rpm command | DOB feedback OFF</text>',
         '<text x="24" y="52" font-size="13">192 task samples/window, raw spikes retained; not calibrated load truth or complete8s replay.</text>']
    for j,s in enumerate(manifest['sources']):
        with Path(s['csv']).open(newline='') as f:raw=list(csv.DictReader(f))
        rows=[];origin=int(raw[0]['timestamp_us'])
        for r in raw:
            q={k:float(v) for k,v in r.items() if v not in ('True','False')}
            q['time_s']=(int(r['timestamp_us'])-origin)*1e-6;q['dob_valid']=float(r['dob_valid']=='True');q['lpf_updated']=float(r['lpf_updated']=='True');rows.append(q)
        x=j*380
        panel(svg,x,70,380,270,f'Run{j+1}: raw Id/Iq',[('Id',rows,'id_raw_a',1000),('Iq',rows,'iq_raw_a',1000)],0,.192,'mA',1)
        panel(svg,x,350,380,270,'Measured mechanical speed',[('rpm',rows,'mechanical_rpm',1)],0,.192,'rpm',1)
        panel(svg,x,630,380,270,'Filter/observer flags',[('LPF updated',rows,'lpf_updated',1),('DOB valid',rows,'dob_valid',1)],0,.192,'flag',1)
    svg.append('</g></svg>');(OUT/'five_real_windows.svg').write_text('\n'.join(svg),encoding='utf-8')
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="940">',
         '<rect width="100%" height="100%" fill="white"/><g font-family="Arial, sans-serif" fill="#172a3a">',
         '<text x="24" y="28" font-size="21" font-weight="bold">Formal Simulink estimator-only checks | OFF | ON scan not qualified</text>',
         '<text x="24" y="52" font-size="13">Independent synthetic load truth + real-window-conditioned inputs. Brief invalid points can interrupt strict100ms recovery dwell.</text>']
    for j,(hyp,seed) in enumerate([('measurement',1),('measurement',61),('torque',61)]):
        with gzip.open(OUT/f'{hyp}_seed{seed:03}_g0_cap0.025.csv.gz','rt',newline='') as f:
            rows=[{k:float(v) for k,v in r.items()} for r in csv.DictReader(f)]
        x=j*500
        panel(svg,x,70,500,270,f'{hyp},seed{seed}: speed',[('reference',rows,'speed_ref_rpm',1),('measurement',rows,'speed_meas_rpm',1),('plant truth',rows,'rpm_true',1)],2.3,6.9,'rpm',2)
        panel(svg,x,350,500,270,'Load truth / published estimate (invalid=0)',[('true load',rows,'load_ground_truth_a',1000),('published estimate',rows,'dob_estimate_a',1000)],2.3,6.9,'mA equivalent',2)
        panel(svg,x,630,500,270,'Published quality flags',[('LPF updated',rows,'lpf_updated',1),('DOB valid',rows,'dob_valid',1),('reset event',rows,'epoch_resets',1)],2.3,6.9,'flag',2)
    svg.append('</g></svg>');(OUT/'estimator_checks.svg').write_text('\n'.join(svg),encoding='utf-8')

if __name__=='__main__':main()
