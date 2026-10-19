"""File-only schema-2 startup decoder. Never opens serial/debugger/hardware.

Use --trace-bin with an extracted cl_startup object, or --elf + --sram with
an existing SRAM capture (default base 0x20000000). The ELF's symbol size must
match. ELF/SRAM matching identity still belongs to the capture receipt; this
decoder cannot independently prove which firmware ran on the board.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess

FRAME=struct.Struct('<III4H16fi3I6H10B2x')
ROWS=32
TRACE_SIZE=FRAME.size*33+20
FLOATS=('speed_ramped_rpm','speed_instant_rpm','speed_ctrl_rpm','IqRef_A',
        'Id_A','Iq_A','Vd_V','Vq_V','int_d_V','int_q_V','speed_cmd_rpm',
        'speed_detect_rpm','Iq_error_A','mechanical_angle_deg',
        'electrical_angle_rad','predicted_electrical_angle_rad')
BYTES=('validator_state','encoder_valid','pending_valid','rundown_armed',
       'contact_candidate','state','mode','gates','voltage_saturated','current_path')


def frame(data,offset=0,direction=-1):
    v=FRAME.unpack_from(data,offset)
    row=dict(zip(('us','adc_seq','encoder_timestamp_us','encoder_raw','IU_raw','IV_raw',
                  'encoder_glitch_streak'),v[:7]))
    row.update(zip(FLOATS,v[7:23]))
    row.update(zip(('encoder_delta','encoder_dt_us','pending_source_seq','actual_commit_count'),v[23:27]))
    row['PWM_pending']=list(v[27:30])
    row['PWM_applied_preload_readback']=list(v[30:33])
    row.update(zip(BYTES,v[33:43]))
    if any(not math.isfinite(row[k]) for k in FLOATS):
        raise ValueError('Nonfinite diagnostic frame; not valid evidence')
    if row['encoder_raw']>=16384 or max(row['IU_raw'],row['IV_raw'])>4095:
        raise ValueError('Out-of-range raw words; retain original capture for investigation')
    row['Vdq_magnitude_V']=math.hypot(row['Vd_V'],row['Vq_V'])
    row['encoder_delta_rpm']=None
    if row['encoder_valid'] and not row['encoder_glitch_streak'] and row['encoder_dt_us']:
        row['encoder_delta_rpm']=row['encoder_delta']*direction*60e6/(16384*row['encoder_dt_us'])
        row['estimator_delta_rpm_error']=row['speed_instant_rpm']-row['encoder_delta_rpm']
    return row


def decode(data,direction=-1,period_us=50000):
    if len(data)!=TRACE_SIZE: raise ValueError(f'Expected schema-2 {TRACE_SIZE} bytes')
    start,flags,off,total,active,frozen,fault,terminal=struct.unpack_from('<4I4B',data,FRAME.size*33)
    if active or not frozen: raise ValueError('Trace must be frozen and inactive')
    if total>ROWS or fault>1 or terminal>1: raise ValueError('Invalid schema-2 header')
    rows=[frame(data,i*FRAME.size,direction) for i in range(total)]
    for a,b in zip(rows,rows[1:]):
        if b['us']-a['us']<period_us: raise ValueError('Nonsequential startup cadence')
    terminal_row=frame(data,FRAME.size*32,direction) if fault or terminal else None
    return dict(schema=2,offline_only=True,hardware_access=False,
        capture_identity_verified=False,encoder_direction_assumption=direction,
        sample_period_min_us=period_us,consecutive_adc_pairs=False,
        start_us=start,first_flags=flags,off_us=off,total=total,frozen=bool(frozen),
        fault_valid=bool(fault),terminal_valid=bool(terminal),rows=rows,terminal=terminal_row,
        interpretation=[
            'Outer-loop decimated snapshots, not simultaneous ADC/encoder samples.',
            'Iq/Id/Vdq may retain the last valid FOC result on a rejected ADC pair; inspect current_path.',
            'PWM_applied_preload_readback is CCR register readback, not measured active latch or bridge output.',
            'Terminal frame may be post-stop: use preceding rows for pre-stop current demand.',
            'A/B/C/D are investigation branches, not automatic phase/sign/PI corrections.',
            '20Hz observations cannot rule out sub-50ms spikes or prove electrical alignment/torque.'
        ])


def extract(elf,sram,base,nm):
    result=subprocess.run([nm,'-S','--defined-only',str(elf)],capture_output=True,text=True,check=True)
    symbols=[line.split() for line in result.stdout.splitlines() if line.split()[-1:] == ['cl_startup']]
    if len(symbols)!=1: raise ValueError('Missing/ambiguous cl_startup symbol')
    address,size=int(symbols[0][0],16),int(symbols[0][1],16)
    if size!=TRACE_SIZE: raise ValueError('ELF is not schema-2 RundownDiagnosticTrial')
    offset=address-base
    if offset<0 or offset+size>len(sram): raise ValueError('SRAM does not cover cl_startup')
    return sram[offset:offset+size]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trace-bin',type=Path)
    p.add_argument('--elf',type=Path); p.add_argument('--sram',type=Path)
    p.add_argument('--sram-base',type=lambda v:int(v,0),default=0x20000000)
    p.add_argument('--nm',default='arm-none-eabi-nm')
    p.add_argument('--encoder-direction',type=int,choices=(-1,1),default=-1)
    args=p.parse_args()
    if args.trace_bin and not (args.elf or args.sram): data=args.trace_bin.read_bytes()
    elif args.elf and args.sram and not args.trace_bin:
        data=extract(args.elf,args.sram.read_bytes(),args.sram_base,args.nm)
    else: p.error('Use --trace-bin OR --elf + --sram')
    report=decode(data,args.encoder_direction)
    report['trace_sha256']=hashlib.sha256(data).hexdigest()
    if args.elf: report['elf_sha256']=hashlib.sha256(args.elf.read_bytes()).hexdigest()
    print(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=='__main__': main()
