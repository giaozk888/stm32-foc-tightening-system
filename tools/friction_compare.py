"""Offline-only FRIC OFF/ON metrics comparison, per direction. No device I/O."""
import argparse
import json
from pathlib import Path
import re

def parse(text,enabled):
    groups={'STATUS':{},'POS':{},'NEG':{}}
    for line in text.splitlines():
        if 'OK FRC ' not in line: continue
        match=re.search(r'\bDIR=(POS|NEG)\b',line)
        dest=groups[match[1] if match else 'STATUS']
        fields={k:int(v) for k,v in re.findall(r'\b([A-Z_]+)=(-?\d+)\b',line)}
        if any(k in dest and dest[k]!=v for k,v in fields.items()):
            raise ValueError('Mixed metric snapshots: one completed run per capture')
        dest.update(fields)
    status=groups['STATUS']
    if any(k not in status for k in ('ON','I_UA','DB_MRPM','FF_ON','KA_NA_PER_RPM_S')) or status['ON']!=enabled:
        raise ValueError('Complete FRIC STATUS and correct ON/OFF required')
    required=('N','START_MS','LOW_MAE_MRPM','CRUISE_MAE_MRPM','I_PEAK_MA',
              'PI_PEAK_MA','IQ_REF_PEAK_MA','IQ_MEAS_PEAK_MA','MEAN_MRPM','WRONG_MS')
    for direction in ('POS','NEG'):
        d=groups[direction]
        if d.get('N',0)>0 and any(k not in d for k in required):
            raise ValueError('Need both METRICS and METRICS2 for measured direction')
    if not any(groups[d].get('N',0)>0 for d in ('POS','NEG')):
        raise ValueError('No measured direction')
    return groups

def compare(off,on):
    a=parse(off,0); b=parse(on,1)
    for key in ('I_UA','DB_MRPM','FF_ON','KA_NA_PER_RPM_S'):
        if a['STATUS'][key]!=b['STATUS'][key]: raise ValueError('Only FRIC may change between captures')
    names={'START_MS':'start_delay_s','LOW_MAE_MRPM':'low_speed_mae_rpm',
        'CRUISE_MAE_MRPM':'cruise_mae_rpm','I_PEAK_MA':'integrator_peak_a',
        'PI_PEAK_MA':'iq_pi_peak_a','IQ_REF_PEAK_MA':'iq_ref_peak_a',
        'IQ_MEAS_PEAK_MA':'iq_measured_peak_a','MEAN_MRPM':'mean_signed_speed_rpm',
        'WRONG_MS':'wrong_direction_time_s'}
    result={}
    if not any(a[d].get('N',0)>0 and b[d].get('N',0)>0 for d in ('POS','NEG')):
        raise ValueError('No common measured direction')
    for direction in ('POS','NEG'):
        if not a[direction].get('N',0) or not b[direction].get('N',0):
            result[direction]=None; continue
        metrics={}
        for key,name in names.items():
            def value(d):
                v=d[key]
                return None if v<0 and key in ('START_MS','LOW_MAE_MRPM','CRUISE_MAE_MRPM') else v/1000
            av=value(a[direction]); bv=value(b[direction])
            metrics[name]={'off':av,'on':bv,'on_minus_off':None if av is None or bv is None else bv-av}
        result[direction]=metrics
    # Equal positive/negative speed magnitudes are evidence, not an enforced controller rule.
    asymmetry={}
    for label,groups in (('off',a),('on',b)):
        p,n=groups['POS'],groups['NEG']
        asymmetry[label]=None if not p.get('N',0) or not n.get('N',0) else {
            'speed_magnitude_difference_rpm':(abs(p['MEAN_MRPM'])-abs(n['MEAN_MRPM']))/1000,
            'start_delay_difference_s':None if min(p['START_MS'],n['START_MS'])<0 else
                (p['START_MS']-n['START_MS'])/1000}
    return {'offline_only':True,'directions':result,'direction_asymmetry':asymmetry,
        'qualification':'Match command magnitude, load, power, limits and coverage manually; absent direction/phase is null'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('off',type=Path);p.add_argument('on',type=Path)
    args=p.parse_args(); print(json.dumps(compare(args.off.read_text(),args.on.read_text()),indent=2))
