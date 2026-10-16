"""Offline filter comparison. Never imports serial/debugger or edits firmware."""
from pathlib import Path
import json
import math
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'safety_backups/filter-comparison-20261012'

def select(values,kind):
    if len(values)!=5: raise ValueError('Five physical samples required')
    p,a,b,c,d=values
    if any(x<0 or x>4095 for x in values): return b
    peak=b>max(a,c) or b<min(a,c)
    if kind=='legacy60':
        hit=peak and abs(a-c)<=60 and min(abs(a-b),abs(b-c))>60
        return a if hit else b
    if kind in ('dual10_40','dual30_50'):
        end,jump=(10,40) if kind=='dual10_40' else (30,50)
        hit=peak and abs(a-c)<=end and min(abs(a-b),abs(b-c))>jump
        return (a+c+1)//2 if hit else b
    if kind in ('quadratic4_30_40','cubic5_30_40'):
        # Cubic interpolation at center from the four OTHER samples.
        # 6*prediction avoids FP/division until a point is actually replaced.
        predicted6=2*(3*a+c-p) if kind.startswith('quadratic4') else 4*a+4*c-p-d
        hit=peak and abs(a-c)<=30 and min(abs(a-b),abs(b-c))>40 and 0<=predicted6<=6*4095 and abs(6*b-predicted6)>240
        # Prediction only classifies; endpoint mean cannot invent an excursion
        # beyond both nearest neighbors when an outer neighbor is corrupted.
        return (a+c+1)//2 if hit else b
    raise ValueError(kind)

KINDS=('legacy60','dual10_40','dual30_50','quadratic4_30_40','cubic5_30_40')

def evaluate(samples,kind):
    rows=[]
    for i in range(2,len(samples)-2):
        rows.append((i,*[select([samples[j][ch] for j in range(i-2,i+3)],kind) for ch in (0,1)]))
    return dict(centers=len(rows),changed=sum((u,v)!=tuple(samples[i]) for i,u,v in rows),
                ranges=[[min(row[ch+1] for row in rows),max(row[ch+1] for row in rows)] for ch in (0,1)],
                max_error=max(abs(row[ch+1]-samples[row[0]][ch]) for row in rows for ch in (0,1)))

def main():
    OUT.mkdir(exist_ok=True)
    old=json.loads((ROOT/'safety_backups/switch-feedback-20261012/off-repaired-a-1791801336398511500.json').read_text('utf-8'))['samples']
    last=json.loads((ROOT/'safety_backups/zero-failure-trace-20261012/sample-1791810619307161800.json').read_text('utf-8'))
    # Actual contiguous context only. No fabricated flanks for distant witnesses.
    local=[last['points'][0]['a']]+[p['b'] for p in last['points']]+[last['points'][-1]['c']]
    report=dict(hardware_access=False,firmware_changed=False,baseline_capture=old.__len__(),
                evaluation='common centers excluding two endpoints at either end',results={})
    for kind in KINDS:
        result=report['results'][kind]=dict(delay_pairs=2 if kind.startswith('cubic5') else 1,
                                           saved_capture=evaluate(old,kind),neighborhood=evaluate(local,kind),sines=[])
        for amp in (500,1000,1500):
            for hz in (100,500,1000,1300):
                worst=dict(changed=0,max_error=0)
                for phase in (0,.17,.51,1.03):
                    samples=[(round(2048+amp*math.sin(2*math.pi*hz*n/20000+phase)),2048) for n in range(1000)]
                    x=evaluate(samples,kind)
                    worst['changed']=max(worst['changed'],x['changed'])
                    worst['max_error']=max(worst['max_error'],x['max_error'])
                result['sines'].append(dict(amplitude=amp,hz=hz,**worst))
        result['shapes']={}
        for name,signal in dict(step=[1560]*40+[1900]*40,
             two_pair_pulse=[1560]*40+[1900]*2+[1560]*40,
             ramp=list(range(1200,2000,5)),isolated=[1560]*40+[1900]+[1560]*40).items():
            result['shapes'][name]=evaluate([(u,1560) for u in signal],kind)
    (OUT/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8')
    for kind,x in report['results'].items():
        print(kind,'saved=',x['saved_capture'],'local=',x['neighborhood'])
        print('sine worst',max(p['changed'] for p in x['sines']),max(p['max_error'] for p in x['sines']))
        print('shapes',{k:v['changed'] for k,v in x['shapes'].items()})

if __name__=='__main__': main()
