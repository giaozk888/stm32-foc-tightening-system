"""Offline torque diagnostic decoder. No serial, flashing, motion or zero selection.

Accept an existing matching ELF + SRAM, or an extracted trace with explicitly
provided test sign/offset. Neither input independently proves capture identity.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import struct
import subprocess
import rundown_startup_decode as startup

META=struct.Struct('<Iii6BH')


def metadata(elf,sram,base,nm):
    output=subprocess.run([nm,'-S','--defined-only',str(elf)],check=True,
                          capture_output=True,text=True).stdout
    symbols=[s.split() for s in output.splitlines() if s.split()[-1:]==['torque_diag']]
    if len(symbols)!=1: raise ValueError('ELF lacks unique torque diagnostic metadata')
    addr,size=int(symbols[0][0],16),int(symbols[0][1],16)
    if size!=META.size: raise ValueError('Unsupported torque diagnostic metadata size')
    offset=addr-base
    if offset<0 or offset+size>len(sram): raise ValueError('SRAM does not cover torque metadata')
    v=META.unpack_from(sram,offset)
    return dict(zip(('outer_generation_before','sign','offset_electrical_deg',
                     'used','queued','prepared','admitting','active','denied','iq_mA'),v))


def analyze(data,sign,offset,iq_ma=50):
    if sign not in (-1,1) or offset not in (-5,0,5):
        raise ValueError('Only explicit manual +/-Iq and 0/+5/-5 degrees are supported')
    if iq_ma not in (50,100,200): raise ValueError('Only explicit 50/100/200mA diagnostic profiles')
    if iq_ma!=50 and offset!=0: raise ValueError('Fixed 100/200mA diagnosis does not change electrical angle offset')
    if iq_ma==200 and sign!=1: raise ValueError('200mA diagnosis is positive only')
    return analyze_samples(data,sign,offset,iq_ma)


def analyze_samples(data,sign,offset,iq_ma):
    """Statistics only. Callers must validate their distinct capture/profile ABI."""
    report=startup.decode(data,-1,8000)
    rows=report['rows']
    report.update(diagnostic='FOC_TORQUE_CHAIN_DIAG',manual_sign=sign,
                  manual_offset_electrical_deg=offset,IdRef_A=0.0,Iq_command_A=sign*iq_ma/1000,
                  lease_us=200000,automatic_sweep=False,automatic_zero_selection=False)
    report['interpretation']=[
        'Decimated >=8ms outer snapshots, not consecutive or simultaneous ADC/encoder/PWM samples.',
        'IQ mode bypasses speed PI; raw encoder delta/dt and current_path must still be inspected.',
        'PWM applied means preload register readback, not a measurement of active gate output.',
        'Good software dq tracking and low Id do NOT establish physical magnetic-axis alignment.',
        f'200ms at {iq_ma}mA is a short direction probe, not a stable-speed/torque calibration.',
        'No-motion alone cannot separate friction, low torque, wiring, polarity or zero error.',
        'Do not select a new electrical zero from this report automatically.'
    ]
    if not rows: report['statistics']=None; return report
    mean=lambda name: statistics.fmean(r[name] for r in rows)
    abs_id=statistics.fmean(abs(r['Id_A']) for r in rows)
    abs_iq=statistics.fmean(abs(r['Iq_A']) for r in rows)
    delta=[b['mechanical_angle_deg']-a['mechanical_angle_deg'] for a,b in zip(rows,rows[1:])]
    # Anchor to first recorded DRIVE frame (not a pre-enable angle, and never
    # the post-stop terminal). Include ALL deltas, without the direction-count
    # deadband, so oscillatory travel is not silently discarded.
    excursion=[r['mechanical_angle_deg']-rows[0]['mechanical_angle_deg'] for r in rows]
    net=excursion[-1]; absolute=sum(abs(d) for d in delta)
    for r,d in zip(rows[1:],delta): r['mechanical_delta_since_previous_frame_deg']=d
    # One encoder LSB is a resolution allowance, not a protection threshold.
    resolution=360/16384
    moving=[d for d in delta if abs(d)>resolution]
    report['statistics']=dict(frames=len(rows),duration_us=rows[-1]['us']-rows[0]['us'],
        mean_Id_A=mean('Id_A'),mean_Iq_A=mean('Iq_A'),mean_abs_Id_A=abs_id,
        mean_abs_Iq_A=abs_iq,Id_Iq_abs_ratio=abs_id/abs_iq if abs_iq>1e-9 else None,
        mean_abs_Iq_error_A=statistics.fmean(abs(r['IqRef_A']-r['Iq_A']) for r in rows),
        mean_speed_rpm=mean('speed_ctrl_rpm'),mean_Vd_V=mean('Vd_V'),mean_Vq_V=mean('Vq_V'),
        Vdq_max_V=max(r['Vdq_magnitude_V'] for r in rows),
        mechanical_travel_deg=net,net_mechanical_travel_deg=net,
        total_absolute_travel_deg=absolute,
        max_positive_excursion_deg=max(0.0,max(excursion)),
        max_negative_excursion_deg=min(0.0,min(excursion)),
        max_negative_excursion_abs_deg=max(0.0,-min(excursion)),
        directionality_ratio=sign*net/absolute if absolute else None,
        excursion_reference='first recorded DRIVE frame; excludes post-stop terminal',
        stationary_intervals=sum(abs(d)<=resolution for d in delta),
        expected_direction_intervals=sum(d*sign>resolution for d in delta),
        opposite_direction_intervals=sum(d*sign < -resolution for d in delta),
        monotonic_expected_fraction=sum(d*sign>0 for d in moving)/len(moving) if moving else None,
        encoder_invalid_rows=sum(not r['encoder_valid'] or r['encoder_glitch_streak']!=0 for r in rows),
        expected_direction='signed mechanical angle increases / encoder raw decreases' if sign>0
                           else 'signed mechanical angle decreases / encoder raw increases')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trace-bin',type=Path)
    p.add_argument('--elf',type=Path); p.add_argument('--sram',type=Path)
    p.add_argument('--sign',type=int,choices=(-1,1)); p.add_argument('--offset-deg',type=int,choices=(-5,0,5))
    p.add_argument('--iq-ma',type=int,choices=(50,100,200),help='Required with trace-bin; magnitude only, no device access')
    p.add_argument('--sram-base',type=lambda x:int(x,0),default=0x20000000)
    p.add_argument('--nm',default='arm-none-eabi-nm')
    a=p.parse_args(); meta=None
    if a.elf and a.sram and not a.trace_bin and a.sign is None and a.offset_deg is None and a.iq_ma is None:
        ram=a.sram.read_bytes(); meta=metadata(a.elf,ram,a.sram_base,a.nm)
        if any(meta[k] for k in ('queued','admitting','active')) or not meta['used']:
            p.error('Diagnostic must have finished; no live/rearm operation is performed')
        data=startup.extract(a.elf,ram,a.sram_base,a.nm)
        sign,offset=meta['sign'],meta['offset_electrical_deg']
        iq_ma=meta['iq_mA'] or 50  # Explicit zero-padding legacy ABI only.
    elif a.trace_bin and not (a.elf or a.sram) and a.sign is not None and a.offset_deg is not None and a.iq_ma is not None:
        data=a.trace_bin.read_bytes(); sign,offset=a.sign,a.offset_deg
        iq_ma=a.iq_ma
    else: p.error('Use --elf + --sram OR --trace-bin + --sign + --offset-deg + --iq-ma')
    report=analyze(data,sign,offset,iq_ma)
    report['metadata']=meta
    report['trace_sha256']=hashlib.sha256(data).hexdigest()
    if a.elf: report['elf_sha256']=hashlib.sha256(a.elf.read_bytes()).hexdigest()
    print(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=='__main__': main()
