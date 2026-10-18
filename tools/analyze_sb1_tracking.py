"""File-only diagnosis of the exact SB1 run. No board, UART or reset imports."""
import hashlib
import json
from pathlib import Path
import re
import statistics
import struct

from foc_path_profile_report import symbols

ROOT=Path(__file__).resolve().parents[1]
RECEIPT=ROOT/'tmp/sb1-speed-speed-1792310227239040200.json'
ELF=ROOT/'foc2_app_a/build/ZeroValidAdmissionTrial/foc2.elf'
IMAGE_SHA='11b99efb2323f552b568bb3e8dcbf2f1e0cab5257bd81f15816be2fad475e7e6'
ELF_SHA='ba3bcde75abfbdc73b6184368e6f860be91c7024877155f479a91597df28f889'


def digest(data): return hashlib.sha256(data).hexdigest()


def analyze():
    receipt=json.loads(RECEIPT.read_text('utf-8'))
    image=ELF.with_suffix('.bin').read_bytes()
    flash=Path(receipt['final_capture']).read_bytes()
    ram=Path(receipt['ram_capture']).read_bytes()
    table=symbols(ELF)
    if (len(flash)!=0x80000 or len(ram)!=0x20000 or digest(image)!=IMAGE_SHA or
            digest(ELF.read_bytes())!=ELF_SHA or digest(flash)!=receipt['final_sha256'] or
            flash[0x8000:0x8000+len(image)]!=image or
            struct.unpack_from('<I',image,4)[0]!=(table['Reset_Handler'][0]|1) or
            receipt['start_attempts']!=1 or not receipt['final_outputs_off']):
        raise ValueError('Exact stopped real-SB1 run and matching image/ELF required')

    def scalar(name,fmt='f'):
        address,size=table[name]
        if size!=struct.calcsize('<'+fmt): raise ValueError('ELF scalar schema: '+name)
        return struct.unpack_from('<'+fmt,ram,address-0x20000000)[0]

    names=('speed_diag_time_s','speed_diag_speed_integral','speed_diag_error_integral',
           'speed_diag_min_rpm','speed_diag_max_rpm')
    diag={n:scalar(n) for n in names}
    diag['valid']=scalar('speed_diag_valid','B')
    if diag['valid']!=1 or not 1.9<diag['speed_diag_time_s']<2.2:
        raise ValueError('No complete SPEED-mode diagnostic interval')
    diag['mean_filtered_rpm']=diag['speed_diag_speed_integral']/diag['speed_diag_time_s']
    diag['integrated_angle_deg']=diag['speed_diag_speed_integral']*6

    address,size=table['cl_startup']
    if size!=2000: raise ValueError('Exact ARM32 startup trace required')
    offset=address-0x20000000
    header=dict(zip(('start_us','flags','off_us','total','active','frozen','fault_valid','pad'),
                    struct.unpack_from('<4I4B',ram,offset+1980)))
    if not header['frozen'] or header['active'] or header['fault_valid'] or header['total']<32:
        raise ValueError('Expected stopped, nonfaulting SPEED trace')
    rows=[]
    for seq in range(header['total']-32,header['total']):
        values=struct.unpack_from('<3I4H10f',ram,offset+seq%32*60)
        row=dict(zip(('elapsed_us','adc_seq','encoder_us','angle_raw','adc_u','adc_v','reserved',
            'ref_rpm','instant_rpm','filtered_rpm','iq_ref_A','id_A','iq_A','vd_V','vq_V',
            'current_int_d_V','current_int_q_V'),values))
        row['speed_p_A']=.003*(row['ref_rpm']-row['filtered_rpm'])
        row['inferred_speed_integral_A']=row['iq_ref_A']-row['speed_p_A']
        rows.append(row)
    errors=dict(raw_rpm=[],lpf_rpm=[],speed_iq_ref_A=[])
    for previous,row in zip(rows,rows[1:]):
        dt_us=(row['encoder_us']-previous['encoder_us'])&0xffffffff
        dt=dt_us*1e-6
        delta=(row['angle_raw']-previous['angle_raw']+8192)%16384-8192
        raw=-delta*60/(16384*dt)
        lpf=previous['filtered_rpm']+dt/(.020+dt)*(row['instant_rpm']-previous['filtered_rpm'])
        old=previous['inferred_speed_integral_A']; error=row['ref_rpm']-row['filtered_rpm']
        # This saved tail never reaches the SB1 braking condition. Reproduce
        # its ordinary integration followed by its exact 0.20A/s rise bound.
        next_i=old+.020*error*dt
        if next_i>0 and row['ref_rpm']>0: next_i=min(next_i,max(old,0)+.20*dt)
        next_i=max(-.35,min(.35,next_i))
        iq=max(-.4,min(.4,row['speed_p_A']+next_i))
        errors['raw_rpm'].append(abs(raw-row['instant_rpm']))
        errors['lpf_rpm'].append(abs(lpf-row['filtered_rpm']))
        errors['speed_iq_ref_A'].append(abs(iq-row['iq_ref_A']))
        row['dt_us']=dt_us
    maxima={k:max(v) for k,v in errors.items()}
    if maxima['raw_rpm']>.001 or maxima['lpf_rpm']>.001 or maxima['speed_iq_ref_A']>1e-5:
        raise ValueError('Tail does not reproduce angle/speed/SB1 model: '+str(maxima))
    iq_error=[r['iq_A']-r['iq_ref_A'] for r in rows]
    tail=dict(start_ms=rows[0]['elapsed_us']/1000,end_ms=rows[-1]['elapsed_us']/1000,
        frames=len(rows),iq_reference_mean_A=statistics.mean(r['iq_ref_A'] for r in rows),
        iq_measured_mean_A=statistics.mean(r['iq_A'] for r in rows),
        iq_error_mean_A=statistics.mean(iq_error),
        iq_error_rms_A=(statistics.mean(v*v for v in iq_error))**.5,
        id_mean_A=statistics.mean(r['id_A'] for r in rows),
        vq_mean_V=statistics.mean(r['vq_V'] for r in rows),
        dt_us_min=min(r['dt_us'] for r in rows[1:]),dt_us_max=max(r['dt_us'] for r in rows[1:]))

    wire=[item['line'] for item in receipt['uart'] if ' OK STATUS STAGE=1 BUSY=1 MODE=SPD ' in item['line']]
    if len(wire)!=len(receipt['samples']): raise ValueError('UART/receipt sample association differs')
    uart=[]
    for sample,line in zip(receipt['samples'],wire):
        speed=float(sample['status']['CTRL'].removesuffix('rpm'))
        iq_mA=int(re.search(r'\bIqRef=([+-]?\d+)mA\b',line)[1])
        uart.append(dict(elapsed_s=sample['elapsed_s'],speed_rpm=speed,iq_ref_mA=iq_mA,
            inferred_speed_integral_mA=iq_mA-3*(20-speed) if sample['elapsed_s']>.11 else None))
    result=dict(offline_only=True,hardware_operations=0,controller_modified=False,
        receipt=str(RECEIPT),image_sha256=IMAGE_SHA,elf_sha256=ELF_SHA,
        ram_sha256=digest(ram),speed_diagnostics=diag,startup_header=header,
        tail=tail,tail_replay_max_error=maxima,tail_rows=rows,uart_rows=uart,
        interpretation=dict(
            proved=['SPEED-mode retained maximum is 31.0398rpm; UART maximum17.8rpm misses it.',
                'No protective overspeed/current fault or CCR/deadline miss occurred in this run.',
                'Recorded final32 outer-loop frames reproduce signed angle deltas,20ms LPF and SB1 integral rise.',
                'Final-tail measured dq current is near the command under the SAME sensor/angle model.'],
            inference=['SB1 integral reset above ref+5rpm explains the loss of driving Iq after the burst.',
                'The0.20A/s rebuild can cause slow repeated breakaway rather than sustained low-speed torque.'],
            not_proved=['Exact1kHz event/candidate integral at the31rpm peak was overwritten by the32-frame ring.',
                'Cause of initial~1.2s poor motion: mechanical resistance, electrical angle/phase alignment,',
                'supply behavior and low-speed cogging cannot be separated by this capture.',
                'No independent speed, phase-current polarity or torque calibration is established.']))
    output=ROOT/'tmp/sb1-tracking-analysis-20261018.json'
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(output),speed_diagnostics=diag,tail=tail,
                         tail_replay_max_error=maxima),indent=2))
    return result


if __name__=='__main__': analyze()
