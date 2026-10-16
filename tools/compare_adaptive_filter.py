"""Offline comparison of ACTUAL C kernels. No serial, debugger, or actuation.

Saved data has no clean ground truth: changed counts are not accuracy scores.
Do not concatenate/repeat captures or invent flanks to make zero READY.
"""
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_foc_adaptive_filter import compile_replays, replay

def metrics(rows,samples,truth=None):
    changed=[sum(row[ch+1]!=samples[row[0]][ch] for row in rows) for ch in (0,1)]
    result=dict(centers=len(rows),changed_uv=changed,
        changed_pairs=sum(bool(row[3]) for row in rows),
        outside_nominal100=sum(max(abs(row[1]-1560),abs(row[2]-1560))>100 for row in rows),
        ranges=[[min(row[ch+1] for row in rows),max(row[ch+1] for row in rows)] for ch in (0,1)])
    if truth is not None:
        result['rmse_counts']=math.sqrt(sum((row[ch+1]-truth[row[0]][ch])**2
            for row in rows for ch in (0,1))/(2*len(rows)))
        result['changed_clean_points']=sum(row[ch+1]!=truth[row[0]][ch]
            for row in rows for ch in (0,1) if samples[row[0]][ch]==truth[row[0]][ch])
    return result

def main():
    exes=compile_replays()
    report=dict(hardware_access=False,flashed=False,motor_qualified=False,
        delay_pairs=1,delay_us_at_20khz=50,zero_window_physical_pairs=4000,
        notes=['Saved changed counts have no clean ground truth.',
               'Real one-period current pulses are indistinguishable from matching spikes.',
               'Host average timings are NOT Cortex-M4 worst-case ISR timings.'],saved={},synthetic={})
    source=ROOT/'safety_backups/switch-feedback-20261012/off-repaired-a-1791801336398511500.json'
    saved=json.loads(source.read_text('utf-8'))['samples']
    failed=ROOT/'safety_backups/zero-failure-trace-20261012/sample-1791810619307161800.json'
    points=json.loads(failed.read_text('utf-8'))['points']
    assert all(b['seq']==a['seq']+1 and b['a']==a['b'] and b['b']==a['c'] for a,b in zip(points,points[1:]))
    context=[points[0]['a']]+[p['b'] for p in points]+[points[-1]['c']]
    for name,path,samples in [('off_capture',source,saved),('failure_context',failed,context)]:
        result=dict(source=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    physical_pairs=len(samples),clean_ground_truth=False)
        for kind,exe in exes.items():
            rows=replay(exe,samples)
            result[kind]=dict(filter=metrics(rows,samples),
                zero_window=replay(exe,samples,'--zero-window'))
        report['saved'][name]=result
    for amplitude in (25,35,60,240):
        truth=[(1560,1560)]*4000
        samples=truth.copy()
        for n in range(100,4000,200): samples[n]=(1560+amplitude,1560)
        report['synthetic'][f'isolated_{amplitude}']={kind:metrics(replay(exe,samples),samples,truth)
            for kind,exe in exes.items()}
    for name,values in {
        'step':[1560]*100+[1900]*200,
        'two_sample_pulse':[1560]*100+[1900]*2+[1560]*200,
        'ramp':list(range(1200,2400,5)),
        'physical_one_sample_pulse':[1560]*100+[2400]+[1560]*200,
    }.items():
        samples=[(x,1560) for x in values]
        report['synthetic'][name]={kind:metrics(replay(exe,samples),samples,samples)
            for kind,exe in exes.items()}
    report['zero_synthetic']={}
    window=[(1560+n%3-1,1560) for n in range(4000)]
    for n in range(100,4000,500): window[n]=(1800,1560)
    for kind,exe in exes.items():
        report['zero_synthetic'][kind]=replay(exe,[(1560,1560)]*20000+window+[(1560,1560)]*3,'--zero')
    report['host_average_ns_per_pair']={}
    for kind,exe in exes.items():
        values=[json.loads(subprocess.run([str(exe),'--bench'],capture_output=True,text=True,check=True).stdout)
                ['host_ns_per_pair'] for _ in range(7)]
        report['host_average_ns_per_pair'][kind]=dict(median=statistics.median(values),runs=values)
    out=ROOT/'safety_backups/adaptive-filter-offline-20261014'
    out.mkdir(exist_ok=True)
    (out/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8')
    print('Report:',out/'comparison.json')
    for name,result in report['saved'].items():
        print(name, 'fixed repairs=',result['fixed']['filter']['changed_pairs'],
              'adaptive repairs=',result['adaptive']['filter']['changed_pairs'],
              'robust zero=',result['adaptive']['zero_window'])
    print('Host timing only:',report['host_average_ns_per_pair'])

if __name__=='__main__': main()
