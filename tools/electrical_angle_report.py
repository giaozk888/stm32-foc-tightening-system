"""File-only electrical angle diagnostic decoder. No serial/SWD/start commands.

Hand input is saved ANGLE READ/STATUS text, with final inactive STATUS after
END. Offset input is a matching future capture receipt plus its BIN/ELF/RAM.
Does not select, write, or recommend an automatic new magnetic zero.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import struct
import rundown_startup_decode as startup
import breakaway_current_report as motion_schema
from foc_path_profile_report import symbols
from loaded_fsm_snapshot_report import decode as protection_decode


def hand_report(text):
    rows={}; status=None
    for line in text.splitlines():
        fields=dict(re.findall(r'\b([A-Z][A-Z0-9_]*)=([+-]?[0-9]+)',line))
        if 'OK ANGLE ROW=' in line:
            keys=('ROW','US','RAW','MC','MMDEG','EMDEG','WRMDEG')
            if not all(k in fields for k in keys): raise ValueError('Incomplete hand row')
            f={k:int(fields[k]) for k in keys}; seq=f['ROW']
            if seq in rows and rows[seq]!=f: raise ValueError('Conflicting duplicate hand row')
            rows[seq]=f
        elif 'OK ANGLE ACTIVE=' in line: status={k:int(v) for k,v in fields.items()}
    if not rows or status is None: raise ValueError('Hand rows and final STATUS required')
    a=[rows[k] for k in sorted(rows)]; reasons=[]
    if sorted(rows)!=list(range(len(rows))) or status.get('N')!=len(rows): reasons.append('MISSING_ROWS')
    if status.get('ACTIVE')!=0 or status.get('OFF')!=1: reasons.append('NOT_ENDED_OUTPUT_OFF')
    if status.get('ERR')!=0 or status.get('PASS')!=1: reasons.append('FIRMWARE_HAND_CHECK_NOT_PASSED')
    if status.get('PP')!=10 or status.get('DIR')!=-1 or status.get('ZERO')!=10507: reasons.append('MAPPING_CHANGED')
    max_error=0.0; max_position_error=0.0; forward=False; reverse=False
    for f in a:
        if not 0<=f['RAW']<16384 or not 0<=f['WRMDEG']<360001: reasons.append('INVALID_RAW_OR_WRAP')
        max_error=max(max_error,abs(f['EMDEG']/1000-f['MC']*3600/16384))
        max_position_error=max(max_position_error,abs(f['MMDEG']/1000-f['MC']*360/16384))
    for x,y in zip(a,a[1:]):
        if not 19000<=y['US']-x['US']<=60000: reasons.append('HAND_RECORD_GAP')
        dm=y['MC']-x['MC']; de=(y['EMDEG']-x['EMDEG'])/1000
        if abs(dm)>=8:
            forward|=dm>0; reverse|=dm<0
            if dm*de<0: reasons.append('DIRECTION_MISMATCH')
        # Verify unwrapped electrical accumulation follows actual wrapped
        # output, not only a separately reconstructed mechanical*10 value.
        dw=(y['WRMDEG']-x['WRMDEG'])/1000
        if dw>180: dw-=360
        if dw< -180: dw+=360
        if abs(de)>180 or abs(de-dw)>0.02: reasons.append('WRAPPED_UNWRAPPED_MISMATCH_OR_ALIAS')
    excursion=max(abs(f['MC']) for f in a)
    if excursion<16384 or abs(a[-1]['MC'])>128 or not (forward and reverse): reasons.append('FULL_TURN_AND_RETURN_NOT_CAPTURED')
    if max_error>2 or max_position_error>.1: reasons.append('ANGLE_CHAIN_ERROR')
    at=max(a,key=lambda f:abs(f['MC']))
    ratio=(at['EMDEG']/1000)/(at['MC']*360/16384) if at['MC'] else None
    return dict(mode='OUTPUT_OFF_HAND',offline_only=True,hardware_access=False,rows=len(a),
        software_chain_pass=not reasons,reasons=sorted(set(reasons)),
        observed_electrical_to_mechanical_ratio=ratio,expected_pole_pairs=10,
        max_chain_error_electrical_deg=max_error,max_mechanical_position_error_deg=max_position_error,
        mechanical_excursion_deg=excursion*360/16384,net_mechanical_deg=a[-1]['MC']*360/16384,
        measured_rows=[dict(encoder_raw=f['RAW'],us=f['US'],seq=f['ROW'],
            mechanical_angle_unwrapped_deg=f['MMDEG']/1000,electrical_angle_unwrapped_deg=f['EMDEG']/1000,
            electrical_angle_wrapped_deg=f['WRMDEG']/1000) for f in a],
        physical_pole_pairs_verified=False,magnetic_zero_verified=False,
        interpretation='Software sign/wrap/10x check only. Physical shaft marker and magnetic zero need separate evidence.')


def offset_report(receipt,elf,image):
    r=json.loads(receipt.read_text('utf-8')); data=image.read_bytes(); ram=Path(r['ram_capture']).read_bytes()
    flash=Path(r['final_capture']).read_bytes(); digest=lambda x:hashlib.sha256(x).hexdigest()
    if (digest(data)!=r.get('image_sha256') or digest(elf.read_bytes())!=r.get('elf_sha256') or
        digest(flash)!=r.get('final_sha256') or flash[0x8000:0x8000+len(data)]!=data or
        r.get('outputs',{}).get('VTOR')!=0x08008000): raise ValueError('Matching A BIN/ELF/Flash/RAM receipt required')
    if b'OK ANGLE OFFSET IQ_MA=350 ID_MA=0 LEASE_US=400000' not in data:
        raise ValueError('Not the 400ms electrical-offset diagnostic image')
    table=symbols(elf)
    address,size=table['torque_diag']
    if size!=20: raise ValueError('Wrong diagnostic metadata ABI')
    values=struct.unpack_from('<Iii6BH',ram,address-0x20000000)
    offset=values[2]
    if offset not in (-30,-20,-10,0,10,20,30) or values[1]!=1 or values[-1]!=350:
        raise ValueError('Not fixed positive 350mA allowed-offset capture')
    trace=startup.decode(startup.extract(elf,ram,0x20000000,'arm-none-eabi-nm'),period_us=12000)
    rows=trace['rows']; p=protection_decode(ram,elf)
    address,size=table['breakaway_motion']
    if size!=motion_schema.MOTION.size: raise ValueError('Motion schema mismatch')
    m=dict(zip(motion_schema.MOTION_NAMES,motion_schema.MOTION.unpack_from(ram,address-0x20000000)))
    if not rows: raise ValueError('No driven rows; not an offset motion result')
    for f in rows:
        if f['mode']!=3 or f['gates']!=3 or abs(f['IqRef_A']-.35)>1e-6: raise ValueError('Not fixed +350mA driven IQ')
    mean=lambda key:statistics.mean(f[key] for f in rows)
    mean_abs=lambda key:statistics.mean(abs(f[key]) for f in rows)
    return dict(mode='MANUAL_ONE_OFFSET',offline_only=True,hardware_access=False,offset_electrical_deg=offset,
        IdRef_A=0,IqRef_A=.35,rows=len(rows),mean_Iq_A=mean('Iq_A'),mean_Id_A=mean('Id_A'),
        mean_abs_Iq_A=mean_abs('Iq_A'),mean_abs_Id_A=mean_abs('Id_A'),
        Id_Iq_abs_ratio=mean_abs('Id_A')/mean_abs('Iq_A') if mean_abs('Iq_A') else None,
        mean_Vq_V=mean('Vq_V'),mean_Vd_V=mean('Vd_V'),mean_speed_rpm=mean('speed_ctrl_rpm'),
        net_travel_deg=m['net_counts']*360/16384,total_abs_raw_encoder_travel_deg=m['absolute_counts']*360/16384,
        max_positive_excursion_deg=m['positive_counts']*360/16384,
        max_negative_excursion_deg=m['negative_counts']*360/16384,
        raw_encoder_jitter_included=True,full_window_motion=m,timing=p['timing'],fault=p['first_fault'],
        trace=trace,automatic_sweep=False,automatic_zero_selection=False,magnetic_zero_written=False)


def main():
    p=argparse.ArgumentParser(description=__doc__); mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--hand-log',type=Path); mode.add_argument('--offset-receipt',type=Path)
    p.add_argument('--elf',type=Path); p.add_argument('--image',type=Path)
    a=p.parse_args()
    if a.offset_receipt and not(a.elf and a.image): p.error('Offset requires matching ELF and image')
    result=hand_report(a.hand_log.read_text('utf-8')) if a.hand_log else offset_report(a.offset_receipt,a.elf,a.image)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__': raise SystemExit(main())
