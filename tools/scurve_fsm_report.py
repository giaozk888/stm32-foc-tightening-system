"""File-only SC1 evidence report. No debugger, serial, reset or motor I/O."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import statistics
import struct
from foc_path_profile_report import symbols

ROOT=Path(__file__).resolve().parents[1]
BIN_SHA='be4a89f500cd542f82e3cd1d447ee6c7ed45fabe45b55c35bcf25a62f551024f'
ELF_SHA='608c0e98150b4de00d2a21801ed742d792fbf0d1678bd8a10510a0c8ecf89d6c'
ELF=ROOT/'foc2_app_a/build/Tightening240rpmScurveCandidate/foc2.elf'
FRAME=struct.Struct('<3I4H10f')
FIELDS=('us','adc_seq','encoder_us','encoder_raw','IU_raw','IV_raw','reserved',
    'reference_rpm','speed_raw_rpm','speed_ctrl_rpm','iq_ref_a','id_a','iq_a',
    'vd_v','vq_v','current_integral_d_v','current_integral_q_v')

def digest(data): return hashlib.sha256(data).hexdigest()

def speed_window(r,lo=2,hi=7.9):
    points=[s for s in r['samples'] if s['status'].get('BUSY')=='1' and lo<=s['elapsed_s']<=hi]
    v=[float(s['status']['CTRL'].removesuffix('rpm')) for s in points]
    return dict(start_s=lo,end_s=hi,count=len(v),mean_rpm=statistics.mean(v),
        min_rpm=min(v),max_rpm=max(v),std_rpm=statistics.pstdev(v),
        mean_abs_error_rpm=statistics.mean(abs(x-240) for x in v),
        within_10_percent_fraction=sum(abs(x-240)<=24 for x in v)/len(v))

def trace_v1(ram,table):
    address,size=table['cl_startup']
    if size!=2000 or len(ram)!=0x20000: raise ValueError('Expected schema-1 trace and full SRAM')
    off=address-0x20000000
    start,flags,off_us,total,active,frozen,fault,_=struct.unpack_from('<4I4B',ram,off+33*60)
    if active or not frozen or total<32: raise ValueError('Expected complete frozen rolling tail')
    rows=[dict(zip(FIELDS,FRAME.unpack_from(ram,off+(n%32)*60))) for n in range(total-32,total)]
    return dict(schema=1,total=total,start_us=start,flags=flags,off_us=off_us,
        fault_valid=bool(fault),rows=rows,mean_iq_a=statistics.mean(x['iq_a'] for x in rows),
        mean_id_a=statistics.mean(x['id_a'] for x in rows),
        mean_iq_ref_a=statistics.mean(x['iq_ref_a'] for x in rows),
        qualification='Last 32 completed outer frames, not the startup ramp; mixed-age FOC/encoder data')

def report(path):
    r=json.loads(path.read_text('utf-8')); image=ELF.with_suffix('.bin').read_bytes()
    flash=Path(r['final_capture']).read_bytes(); ram=Path(r['ram_capture']).read_bytes()
    if (digest(image)!=BIN_SHA or digest(ELF.read_bytes())!=ELF_SHA or
            r['image_sha256']!=BIN_SHA or r['elf_sha256']!=ELF_SHA or
            digest(flash)!=r['final_sha256'] or flash[0x8000:0x8000+len(image)]!=image or
            r['outputs']['VTOR']!=0x08008000 or not r['final_cpu_halted'] or not r['final_outputs_off']):
        raise ValueError('Same-run halted SC1 BIN/ELF/Flash identity required')
    comparisons={}
    for name,relative in (
            ('AW0','tmp/aw-no-sb3-fsm-run-1792467627757706000.json'),
            ('L00','tmp/legacy-aw-no-sb3-fsm-run-1792468286958655500.json')):
        comparisons[name]=speed_window(json.loads((ROOT/relative).read_text('utf-8')))
    comparisons['SC1']=speed_window(r)
    speeds=[s for s in r['samples'] if s['status'].get('BUSY')=='1']
    lines=[x['line'] for x in r['uart'] if ' OK STATUS ' in x['line'] and ' BUSY=1 ' in x['line']
        and f" START_REQ={r['start_request_id']} " in x['line']]
    if len(lines)!=len(speeds): raise ValueError('STATUS/IqRef correspondence incomplete')
    currents=[int(re.search(r' IqRef=(-?\d+)mA',line)[1]) for line in lines]
    first_target=next((s['elapsed_s'] for s in speeds if float(s['status']['CTRL'].removesuffix('rpm'))>=240),None)
    tail=trace_v1(ram,symbols(ELF))
    return dict(offline_only=True,hardware_access=False,source_receipt=str(path),
        image_sha256=BIN_SHA,elf_sha256=ELF_SHA,flash_sha256=digest(flash),ram_sha256=digest(ram),
        comparisons=comparisons,speed_summary=r['speed_summary'],
        first_observed_control_speed_at_or_above_240_s=first_target,
        iq_ref_status_mA=dict(min=min(currents),max=max(currents),mean=statistics.mean(currents)),
        zero=r['zero'],timing=r['snapshot']['timing'],cur_confirm=r['snapshot']['cur_confirm'],
        terminal=r['terminal_status'],startup_trace=tail,
        reference_ramp_capture='NOT_MEASURED: compact STATUS has no REF; schema-1 ring retains only final 32 frames',
        qualification='One unloaded run per build, sparse STATUS; no torque accuracy or causal superiority claim')

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('receipt',type=Path)
    args=p.parse_args(); print(json.dumps(report(args.receipt),indent=2,allow_nan=False))

if __name__=='__main__': main()
