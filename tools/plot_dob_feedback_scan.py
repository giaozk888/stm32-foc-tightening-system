"""Saved-data-only plots; display subsampling never changes metrics."""
import csv
import gzip
from html import escape
import json
from pathlib import Path
from plot_dob_empirical import panel

ROOT=Path(__file__).resolve().parents[1]
ENV=ROOT/'simulation/dob_simulink/real_five'
OUT=ENV/'feedback_aware_results'


def read(path):
    opener=gzip.open if path.suffix=='.gz' else open
    with opener(path,'rt',newline='',encoding='utf-8-sig') as f:
        return [{k:float(v) for k,v in row.items()} for row in csv.DictReader(f)]


def header(width,height,title,subtitle):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
            '<rect width="100%" height="100%" fill="white"/><g font-family="Arial, sans-serif" fill="#172a3a">',
            f'<text x="24" y="30" font-size="22" font-weight="bold">{escape(title)}</text>',
            f'<text x="24" y="54" font-size="14">{escape(subtitle)}</text>']


def main():
    choice=json.loads((OUT/'primary_candidates.json').read_text())['selected']
    if not choice:return
    gain,cap=choice['gain'],choice['cap_a']
    svg=header(2000,1240,f'Saved Simulink traces | tuning-selected gain {gain:g}, cap {cap*1000:g} mA',
               'Fixed seed1 and seed61, not best-case selections. Independent synthetic load; actual motor performance NOT validated.')
    for j,(hyp,seed) in enumerate([('measurement',1),('measurement',61),('torque',1),('torque',61)]):
        off=read(ENV/'results'/f'{hyp}_seed{seed:03d}_g0_cap0.025.csv.gz')
        on=read(OUT/f'{hyp}_seed{seed:03d}_g{gain:g}_cap{cap:g}.csv')
        x=j*500
        panel(svg,x,75,500,280,f'{hyp}, seed{seed}: physical speed',
              [('reference',off,'speed_ref_rpm',1),('OFF',off,'rpm_true',1),('ON',on,'rpm_true',1)],2.7,5.5,'rpm',2)
        panel(svg,x,365,500,280,'Load / published estimate (invalid=0)',
              [('true load',off,'load_ground_truth_a',1000),('ON published',on,'dob_estimate_a',1000)],2.7,5.5,'mA equivalent',2)
        panel(svg,x,655,500,280,'Actually applied compensation',
              [('ON comp',on,'iq_dob_a',1000)],2.7,6.8,'mA',2)
        panel(svg,x,945,500,280,'Quality remains per-epoch',
              [('valid',on,'dob_valid',1),('LPF updated',on,'lpf_updated',1),('reset',on,'epoch_resets',1)],2.7,5.5,'flag',1)
    svg.append('</g></svg>')
    (OUT/'off_on_selected.svg').write_text('\n'.join(svg),encoding='utf-8')

    with (OUT/'summary_paired_by_split.csv').open(newline='',encoding='utf-8-sig') as f:
        summary=list(csv.DictReader(f))
    svg=header(1600,940,'Held-out tradeoffs | seeds61..100 only',
               'Candidate selected using seeds1..60; these panels do not retune it. Negative change is better. Missing outcomes remain separately counted.')
    for col,hyp in enumerate(['measurement','torque']):
        for row,metric in enumerate(['true_load_speed_mae_rpm','unload_overshoot_rpm']):
            data=[s for s in summary if s['hypothesis']==hyp and s['split']=='heldout' and s['event']=='both' and s['metric']==metric]
            x=col*800+80;y=125+row*400;w=675;h=240
            vals=[float(s['delta_mean']) for s in data]
            span=max(max(abs(v) for v in vals)*1.2,.001)
            svg.append(f'<text x="{x-40}" y="{y-30}" font-size="19" font-weight="bold">{hyp}: {metric.replace("_"," ")}</text>')
            zero=y+h/2
            for i in range(5):
                yy=y+h*i/4;val=span*(1-i/2)
                svg.append(f'<path d="M{x} {yy}h{w}" stroke="#e1e7eb"/><text x="{x-8}" y="{yy+4}" text-anchor="end" font-size="12">{val:.3g}</text>')
            for i,(s,v) in enumerate(zip(data,vals)):
                xx=x+(i+.5)*w/9;yy=zero-v/span*h/2
                color='#d06140' if v>0 else '#158273'
                selected=abs(float(s['gain'])-gain)<1e-10 and abs(float(s['cap_a'])-cap)<1e-10
                svg.append(f'<rect x="{xx-22}" y="{min(yy,zero)}" width="44" height="{max(abs(yy-zero),.7)}" fill="{color}" stroke="{"#172a3a" if selected else color}" stroke-width="{3 if selected else 1}"/>')
                svg.append(f'<text x="{xx}" y="{y+h+22}" text-anchor="middle" font-size="12">g{float(s["gain"]):g}</text>')
                svg.append(f'<text x="{xx}" y="{y+h+40}" text-anchor="middle" font-size="12">{float(s["cap_a"])*1000:g}mA</text>')
                svg.append(f'<text x="{xx}" y="{yy-6 if v>=0 else yy+15}" text-anchor="middle" font-size="11">{v:+.3g}</text>')
            svg.append(f'<text x="{x}" y="{y+h+67}" font-size="13">Change ON minus OFF, rpm. Dark outline: tuning-selected candidate.</text>')
    svg.append('</g></svg>')
    (OUT/'selection_tradeoffs.svg').write_text('\n'.join(svg),encoding='utf-8')
    print('Saved off_on_selected.svg and selection_tradeoffs.svg (software only).')


if __name__=='__main__':main()
