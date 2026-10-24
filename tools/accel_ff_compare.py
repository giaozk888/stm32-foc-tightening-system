"""Compare saved UART METRICS replies, offline only; never opens devices.

Each input must contain FF STATUS and both METRICS/METRICS2 from one run.
Numbers are 1kHz owner aggregates, not decimated log estimates or a plant model.
"""
import argparse
import json
from pathlib import Path
import re

REQUIRED=('ON','KA_NA_PER_RPM_S','N','MAX_ERR_MRPM','ACC_MAE_MRPM','DEC_MAE_MRPM',
          'OV_MRPM','SETTLE_MS','IQ_REF_PEAK_MA','IQ_MEAS_PEAK_MA','I_PEAK_MA','SAT_MS','SAT_RUN_MS')
def parse(text,enabled):
    values={}
    for line in text.splitlines():
        if 'OK AFF ' in line:
            fields={k:int(v) for k,v in re.findall(r'\b([A-Z_]+)=(-?\d+)\b',line)}
            if any(k in values and values[k]!=v for k,v in fields.items()):
                raise ValueError('Conflicting snapshots: save exactly one completed run per file')
            values.update(fields)
    if any(k not in values for k in REQUIRED) or values['ON']!=enabled or values['N']<=0:
        raise ValueError('Need complete STATUS/METRICS/METRICS2 from correct nonempty ON/OFF run')
    return values

def compare(off,on):
    a=parse(off,0); b=parse(on,1)
    if a['KA_NA_PER_RPM_S']!=b['KA_NA_PER_RPM_S']:
        raise ValueError('Ka must match across runs')
    names={'MAX_ERR_MRPM':'max_speed_error_rpm','ACC_MAE_MRPM':'acceleration_mae_rpm',
        'DEC_MAE_MRPM':'deceleration_mae_rpm','OV_MRPM':'overshoot_rpm',
        'SETTLE_MS':'settling_time_s','IQ_REF_PEAK_MA':'iq_ref_peak_a',
        'IQ_MEAS_PEAK_MA':'iq_measured_peak_a','I_PEAK_MA':'integrator_peak_a',
        'SAT_MS':'saturation_duration_s','SAT_RUN_MS':'max_saturation_run_s'}
    output={}
    for key,name in names.items():
        av=a[key]/1000 if a[key]>=0 else None
        bv=b[key]/1000 if b[key]>=0 else None
        output[name]=dict(ff_off=av,ff_on=bv,on_minus_off=bv-av if av is not None and bv is not None else None)
    return dict(offline_only=True,hardware_access=False,metrics=output,
        qualification='Same recipe/target/load/limits and capture coverage must be checked by operator; missing phase is null, not zero')

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('off',type=Path); p.add_argument('on',type=Path)
    args=p.parse_args(); print(json.dumps(compare(args.off.read_text(),args.on.read_text()),indent=2))
if __name__=='__main__': main()
