"""Offline actual-C replay and waveform characterization; no device access."""
from pathlib import Path
import json
import math
import subprocess
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'safety_backups/dual-threshold-20261012'

def main():
    OUT.mkdir(exist_ok=True)
    exe=OUT/'dual_replay.exe'
    subprocess.run([r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe','-O2','-std=c11',
        '-Wall','-Wextra','-Werror','-DFOC_CURRENT_SPIKE_ONLY=1','-I',str(ROOT/'firmware_common'),
        str(ROOT/'tests/foc_current_spike_replay_host.c'),'-o',str(exe)],check=True)
    def replay(samples):
        result=subprocess.run([str(exe)],input=''.join(f'{u} {v}\n' for u,v in samples),
                              text=True,capture_output=True,check=True,timeout=10)
        return [tuple(map(int,line.split())) for line in result.stdout.splitlines()]
    report=dict(endpoint_counts=10,jump_counts=40,replacement='rounded_endpoint_mean',
                delay_pairs=1,hardware_flashed=False,motor_qualified=False)
    last=json.loads((ROOT/'safety_backups/zero-failure-trace-20261012/sample-1791810619307161800.json').read_text('utf-8'))
    report['failure_window_witnesses']=[]
    for p in last['extrema']:
        _,u,v,mask=replay([p['a'],p['b'],p['c']])[0]
        report['failure_window_witnesses'].append(dict(seq=p['seq'],raw=p['b'],
            old_filter=p['filter'],new_filter=[u,v],new_mask=mask))
    samples=[last['points'][0]['a']]+[p['b'] for p in last['points']]+[last['points'][-1]['c']]
    rows=replay(samples)
    report['failure_neighborhood']=dict(centers=len(rows),changed=sum(bool(p[3]) for p in rows),
        range_u=[min(p[1] for p in rows),max(p[1] for p in rows)],
        range_v=[min(p[2] for p in rows),max(p[2] for p in rows)],
        full_calibration_replay=False)
    old=json.loads((ROOT/'safety_backups/switch-feedback-20261012/off-repaired-a-1791801336398511500.json').read_text('utf-8'))['samples']
    rows=replay(old)
    report['older_3600_pair_capture']=dict(centers=len(rows),changed=sum(bool(p[3]) for p in rows),
        range_u=[min(p[1] for p in rows),max(p[1] for p in rows)],
        range_v=[min(p[2] for p in rows),max(p[2] for p in rows)])
    report['older_3600_pair_capture']['minimum_witnesses']=[]
    for ch in range(2):
        p=min(rows,key=lambda row:row[1+ch]); i=p[0]
        report['older_3600_pair_capture']['minimum_witnesses'].append(dict(channel=ch,
            triple=[old[j][ch] for j in (i-1,i,i+1)],filtered=p[ch+1],mask=p[3]))
    old_reference=[]
    for i in range(1,len(old)-1):
        pair=[]
        for ch in range(2):
            a,b,c=(old[j][ch] for j in (i-1,i,i+1))
            isolated=abs(a-c)<=60 and abs(a-b)>60 and abs(b-c)>60 and (b>max(a,c) or b<min(a,c))
            pair.append(a if isolated else b)
        old_reference.append(pair)
    report['older_3600_pair_capture']['previous_60_reference_ranges']=[
        [min(p[ch] for p in old_reference),max(p[ch] for p in old_reference)] for ch in range(2)]
    report['ideal_sine_characterization']=[]
    for hz in (20,100,500,1000,1300):
        samples=[(round(1560+500*math.sin(2*math.pi*hz*n/20000)),1560) for n in range(4000)]
        rows=replay(samples)
        report['ideal_sine_characterization'].append(dict(hz=hz,centers=len(rows),
            changed=sum(u!=samples[i][0] for i,u,v,mask in rows),
            max_error_counts=max(abs(u-samples[i][0]) for i,u,v,mask in rows)))
    (OUT/'replay.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
