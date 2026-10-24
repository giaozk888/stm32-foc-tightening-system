"""Dependency-free SVG curves from saved Simulink CSV; no simulation logic."""
import csv
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT/'simulation/dob_simulink/empirical/results'
COLORS = ['#1f77b4', '#dc5b32', '#222222', '#0e9471']


def load(name, gain):
    with (FOLDER/f'{name}_seed101_g{gain:g}_cap0.025.csv').open(newline='') as f:
        return [{k: float(v) for k, v in r.items()} for r in csv.DictReader(f)]


def panel(svg, x, y, w, h, title, series, lo, hi, ylabel, stride=3):
    # series: list of (label, rows, field, scale). Each field retains actual
    # timestamp; subsampling is display-only, not estimation/metric filtering.
    X,Y,W,H=x+60,y+42,w-80,h-96
    points=[]
    for label, rows, field, scale in series:
        p=[(r['time_s'],r[field]*scale) for r in rows if lo<=r['time_s']<=hi]
        points.append(p[::stride])
    vals=[v for p in points for _,v in p];mn,mx=min(vals),max(vals)
    margin=max((mx-mn)*.12,.0001);mn-=margin;mx+=margin
    svg.append(f'<text x="{x+10}" y="{y+20}" font-size="17" font-weight="bold">{escape(title)}</text>')
    for i in range(5):
        yy=Y+H*i/4;val=mx-(mx-mn)*i/4
        label=f'{val:.3f}' if mx-mn<1 else f'{val:.3g}'
        svg.append(f'<path d="M{X} {yy}h{W}" stroke="#e2e7eb"/><text x="{X-7}" y="{yy+4}" text-anchor="end" font-size="11">{label}</text>')
        xx=X+W*i/4;t=lo+(hi-lo)*i/4
        svg.append(f'<text x="{xx}" y="{Y+H+17}" text-anchor="middle" font-size="11">{t:.3f}</text>')
    svg.append(f'<text x="{x+2}" y="{Y-7}" font-size="12">{escape(ylabel)}</text>')
    for i,(label,rows,field,scale) in enumerate(series):
        pts=' '.join(f'{X+(t-lo)/(hi-lo)*W:.2f},{Y+(mx-v)/(mx-mn)*H:.2f}' for t,v in points[i])
        color=COLORS[i];svg.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.35"/>')
        xx=X+i*130
        svg.append(f'<path d="M{xx} {y+h-20}h16" stroke="{color}" stroke-width="2"/><text x="{xx+22}" y="{y+h-16}" font-size="11">{escape(label)}</text>')


def main():
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="930" viewBox="0 0 1500 930">',
         '<rect width="100%" height="100%" fill="white"/><g font-family="Arial, sans-serif" fill="#172a3a">',
         '<text x="24" y="30" font-size="21" font-weight="bold">Empirical-event-conditioned Simulink stress | DOB gain 0.25 vs OFF</text>',
         '<text x="24" y="53" font-size="13">Synthetic external load truth; event amplitude/pairing from real records. Not a full historical replay or physical validation.</text>']
    for j,name in enumerate(['measurement_train','torque_train','unloaded_stress']):
        off,on=load(name,0),load(name,.25);x=j*500
        panel(svg,x,70,500,270,name+' : speed', [('OFF',off,'rpm_true',1),('ON',on,'rpm_true',1),('reference',off,'speed_ref_rpm',1)],2.5,5.7,'rpm')
        panel(svg,x,350,500,270,'Load truth / estimate',[('true load',off,'load_ground_truth_a',1000),('OFF estimate',off,'dob_estimate_a',1000),('ON estimate',on,'dob_estimate_a',1000)],2.5,5.7,'mA equivalent')
        panel(svg,x,630,500,270,'Applied compensation / validity',[('ON comp (mA)',on,'iq_dob_a',1000),('ON valid',on,'dob_valid',1)],2.5,5.7,'mA / flag')
    svg.append('</g></svg>');(FOLDER/'off_on_curves.svg').write_text('\n'.join(svg),encoding='utf-8')
    rows=load('measured_once',0)
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="650">','<rect width="100%" height="100%" fill="white"/><g font-family="Arial, sans-serif" fill="#172a3a">',
         '<text x="24" y="28" font-size="20" font-weight="bold">Single paired spike: raw input vs unchanged DOB filter</text>']
    panel(svg,0,40,1200,280,'Raw Id/Iq and absId LPF',[('raw Id',rows,'id_raw_a',1000),('raw Iq',rows,'iq_meas_a',1000),('absId LPF',rows,'abs_id_lpf_a',1000)],3.8,3.841,'mA',1)
    panel(svg,0,340,1200,280,'Per-epoch status (no full observer reset)',[('LPF updated',rows,'lpf_updated',1),('DOB valid',rows,'dob_valid',1),('reset event',rows,'epoch_resets',1)],3.8,3.841,'flag',1)
    svg.append('</g></svg>');(FOLDER/'spike_isolation.svg').write_text('\n'.join(svg),encoding='utf-8')


if __name__=='__main__':
    main()
