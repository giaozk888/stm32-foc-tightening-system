"""Files-only fixed-window Id/Iq statistics. Never writes motor parameters."""
import argparse
import json
import math
from pathlib import Path
import struct
import mechanical_dob_report as dob

SIZE=336
META=('version state running frozen stable_us begin_us last_us window_us good_us bad_us '
      'good_n bad_n unstable_us voltage_sat_us iq_sat_us last_seq have_seq positive_over_us '
      'negative_over_us filtered_good_us filtered_bad_us').split()
SIGNALS=('Id_ref_A','Id_meas_A','Iq_A','Id_error_A','speed_rpm')
OVER_KEYS='total_us run_us max_us episodes samples censored'.split()
OVER_BINS=('<5ms','5..20ms','20..100ms','>=100ms')
REASON_NAMES=('VALID',)+tuple(dob.REASONS.values())


def decode_bytes(raw):
    if len(raw)!=SIZE:raise ValueError('Id steady ABI mismatch')
    meta=dict(zip(META,struct.unpack_from('<21I',raw)))
    if meta['version']&1:raise ValueError('Id steady writer in progress')
    if (meta['state']>3 or any(meta[k] not in (0,1) for k in ('running','frozen','have_seq')) or
        meta['window_us']>1000000 or meta['good_us']+meta['bad_us']!=meta['window_us'] or
        meta['filtered_good_us']+meta['filtered_bad_us']!=meta['window_us'] or
        meta['filtered_good_us']>meta['good_us'] or meta['unstable_us']>meta['window_us'] or
        any(meta[k]>meta['good_us'] for k in ('voltage_sat_us','iq_sat_us')) or
        (meta['state']==2 and meta['window_us']!=1000000) or
        (meta['frozen'] and meta['running'])):raise ValueError('Id steady counter/state mismatch')
    signals={}
    for i,key in enumerate(SIGNALS):
        integral,absolute,square,lo,hi=struct.unpack_from('<5f',raw,84+i*20)
        if not all(math.isfinite(v) for v in (integral,absolute,square,lo,hi)) or absolute<0 or square<0:
            raise ValueError('Nonfinite/invalid Id moments')
        if meta['good_us']:
            mean=integral/meta['good_us'];rms=math.sqrt(square/meta['good_us'])
            signals[key]=dict(mean=mean,mean_abs=absolute/meta['good_us'],rms=rms,
                              std=math.sqrt(max(0.,rms*rms-mean*mean)),min=lo,max=hi)
            if lo>hi:raise ValueError('Moment range mismatch')
        else:signals[key]=None
    over={}
    for key,offset,coverage in (('raw_abs_Id',184,meta['good_us']),
                               ('dob_filtered_abs_Id',224,meta['filtered_good_us'])):
        values=struct.unpack_from('<10I',raw,offset)
        row=dict(zip(OVER_KEYS,values[:6]));bins=values[6:]
        if (row['total_us']>coverage or row['max_us']>row['total_us'] or
            row['run_us']>row['max_us'] or row['censored']>sum(bins) or
            sum(bins)+bool(row['run_us'])!=row['episodes'] or
            (meta['state']>=2 and row['run_us'])):raise ValueError('Over-threshold duration mismatch')
        row.update(total_ms=row['total_us']/1000,max_observed_run_ms=row['max_us']/1000,
                   fraction_of_available=row['total_us']/coverage if coverage else None,
                   duration_histogram=dict(zip(OVER_BINS,bins)),coverage_ms=coverage/1000)
        over[key]=row
    hist=struct.unpack_from('<5I',raw,264)
    if sum(hist)!=meta['good_n']:raise ValueError('Id histogram sample count mismatch')
    if meta['positive_over_us']+meta['negative_over_us']!=over['raw_abs_Id']['total_us']:
        raise ValueError('Signed Id duration mismatch')
    counts=struct.unpack_from('<12I',raw,284)
    return dict(meta=meta,signals=signals,over_50ma=over,
                abs_Id_histogram=dict(zip(('<=20mA','20..50mA','50..100mA','100..200mA','>200mA'),hist)),
                whole_run_dob_status_counts=dict(zip(REASON_NAMES,counts)),
                max_compute_us=struct.unpack_from('<I',raw,332)[0],
                fixed_window_complete=meta['state']==2,steady_throughout=meta['state']==2 and not meta['unstable_us'],
                current_data_coverage=meta['good_us']/meta['window_us'] if meta['window_us'] else None,
                feedback_enabled=False,threshold_changed=False,
                semantics='First 1s wall window after target=600rpm and accel_ref<=1rpm/s and speed error<=12rpm '
                'for 500ms. No selection using Id, DOB VALID or residual. Id_ref is the actual task-read fixed '
                'reference, Id/Iq a coherent ADC pair. All moments use available interval weights; missing '
                'current data is not zero-filled. Saturation is included and counted separately. Over-duration '
                'runs are observed within the fixed window and split at missing data; window boundaries may '
                'truncate actual runs. censored counts right closures at gap/window/STOP, not left-boundary '
                'censoring. LP duration excludes epochs where DOB did not update its Id filter. '
                'Raw current is sampled at outer-task rate, NOT every 20kHz ADC frame.')


def decode(receipt,elf):
    from foc_path_profile_report import symbols
    proven=dob.decode(receipt,elf)
    r=json.loads(receipt.read_text());ram=Path(r['ram_capture']).read_bytes()
    address,size=symbols(elf)['id_steady_stats'];offset=address-0x20000000
    if size!=SIZE or not 0<=offset<=len(ram)-SIZE:raise ValueError('Id stats symbol/bounds mismatch')
    result=decode_bytes(ram[offset:offset+SIZE])
    if result['meta']['running'] or not result['meta']['frozen']:raise ValueError('Id stats not frozen')
    if result['whole_run_dob_status_counts']['VALID']!=proven['meta']['valid_samples']:
        raise ValueError('Whole-run DOB sample count disagrees')
    result.update(session_hash=proven['session_hash'],board_verified=True,dob_capture=proven)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt',type=Path,required=True);p.add_argument('--elf',type=Path,required=True)
    args=p.parse_args();print(json.dumps(decode(args.receipt,args.elf),indent=2,allow_nan=False))


if __name__=='__main__':main()
