"""Files-only, same-epoch DOB Id filter/reset/warmup decoder. No device access.

Dense data are ~1 kHz task observations, NOT a full 20 kHz ADC waveform.
Recovery frames are decimated and must not be replayed as consecutive LPF inputs.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import struct
import sys
import mechanical_dob_report as dob

SIZE=96
KEYS=('abi bound running frozen state pre_head pre_count post_count tail_count stable_us '
      'observations trigger_us trigger_seq pre_last_us last_stored_us last_seq '
      'reset_calls_total recorded_reset_calls epoch_resets epoch_reason in_epoch before_have '
      'encoding_errors max_compute_us').split()
RESET=1<<11
VALID=1<<12
INITIALIZED=1<<13
SEEDED=1<<14
TRIGGER=1<<15


def decode_bytes(header,buffer):
    if len(header)!=SIZE or len(buffer)!=4608:raise ValueError('Id trace ABI/buffer size')
    m=dict(zip(KEYS,struct.unpack('<24I',header)))
    if m['abi'] not in (1,2,3,4,5,6,7):raise ValueError('Unknown trace ABI')
    admission=m['abi']>=2
    guarded=m['abi']>=3
    direct=m['abi']>=4
    recoverable=m['abi']>=5
    persistent=m['abi']>=6
    prefilter=m['abi']==7
    pre_n,dense_n,tail_n,frame_bytes=(16,24,32,64) if prefilter else (16,32,48,48) if guarded else (32,32,128,24) if admission else (64,64,160,16)
    if (m['bound']!=1 or m['running'] or m['frozen']!=1 or m['in_epoch'] or
        not 3<=m['state']<=5 or m['pre_head']>=pre_n or m['pre_count']>pre_n or
        m['post_count']>dense_n or m['tail_count']>tail_n or
        (m['tail_count'] and m['post_count']!=dense_n) or
        (m['state']==3 and (m['post_count']!=dense_n or m['tail_count']!=tail_n)) or
        m['recorded_reset_calls']>m['reset_calls_total']):raise ValueError('Id trace terminal/counter metadata')
    rows=[]
    def read(index,phase):
        extra={}
        if admission:
            a,iq,b,c,dt,flags,decision,exit_reason=struct.unpack_from('<4f4H',buffer,index*frame_bytes)
            if (not math.isfinite(iq) or decision>(19 if prefilter else 15 if persistent else 13 if recoverable else 11 if direct else 9 if guarded else 8)
                    or exit_reason>(511 if persistent else 4)):raise ValueError('Invalid admission trace')
            if direct and decision in (2,3,4,5):raise ValueError('Legacy classifier decision in direct profile')
            extra=dict(iq_meas_a=iq,admission_decision=decision,
                admission_name=('NORMAL','SEED','SUSPECT','SPIKE_RETURN','TRANSITION','UNRESOLVED','BLOCKED','QUALITY','STOP','PREARM','DIRECT_REJECT','GAP_RECOVERY','GAP_RESEED','GAP_STALE','JUMP_PENDING','RUN_REJECT','QUALITY_WAIT','QUALITY_RETURN','QUALITY_LEVEL','QUALITY_SEED')[decision],
                admission_exit_reason=exit_reason)
            if prefilter:
                extra.pop('admission_exit_reason')
                delta,before,reset_reason,quality=struct.unpack_from('<ffII',buffer,index*frame_bytes+48)
                if (not all(math.isfinite(x) for x in (delta,before)) or before<0 or
                    quality&~0xfffff or reset_reason&~2047 or decision in (1,10,11,14,15)):
                    raise ValueError('Invalid pre-LPF quality trace')
                extra.update(quality_reason=exit_reason,
                    quality_reasons=[s for bit,s in ((1,'SEED'),(2,'ID_JUMP'),(4,'IQ_JUMP'),(8,'WAIT'),
                        (16,'SOURCE'),(32,'GAP'),(64,'RETURN'),(128,'LEVEL'),(256,'FIRST')) if exit_reason&bit],
                    id_adjacent_delta_a=delta,abs_id_lpf_before_a=before,reset_reason=reset_reason,
                    coherent_samples=quality&65535,quality_pending=bool(quality&(1<<16)),
                    id_bad_confirmed=bool(quality&(1<<17)),raw_history_valid=bool(quality&(1<<18)),
                    lpf_updated=bool(quality&(1<<19)))
            elif persistent:
                extra.pop('admission_exit_reason')
                extra.update(jump_run=exit_reason&255,id_bad_confirmed=bool(exit_reason&256))
                if decision==10:raise ValueError('Single-point rejection in persistent profile')
            if guarded:
                adc_seq,source,published,speed_ref,speed_meas,qual=struct.unpack_from('<3I2fI',buffer,index*frame_bytes+24)
                if not all(math.isfinite(x) for x in (speed_ref,speed_meas)) or (not persistent and qual>52000):
                    raise ValueError('Invalid guarded trace speed/qualification')
                extra.update(adc_seq=adc_seq,adc_source_us=source,adc_published_us=published,
                             speed_ref_rpm=speed_ref,speed_meas_rpm=speed_meas)
                extra['id_bad_us' if persistent else 'qualify_us']=qual
        else:a,b,c,dt,flags=struct.unpack_from('<3fHH',buffer,index*frame_bytes)
        if not all(math.isfinite(v) for v in (a,b,c)) or b<0 or c<0 or not dt:
            raise ValueError('Nonfinite/invalid Id trace frame')
        status=flags&2047
        r=dict(phase=phase,id_meas_a=a,abs_id_lpf_a=b,warmup_s=c,interval_us=dt,
               status=status,reasons=dob.reasons(status),reset=bool(flags&RESET),
               valid=bool(flags&VALID),initialized=bool(flags&INITIALIZED),
               filter_seeded=bool(flags&SEEDED),trigger=bool(flags&TRIGGER))
        r.update(extra)
        if prefilter:
            if bool(r['reset_reason'])!=r['reset']:raise ValueError('Actual DOB reset reason/flag mismatch')
            if not r['lpf_updated'] and b!=r['abs_id_lpf_before_a']:raise ValueError('Rejected sample polluted LPF')
            if r['valid'] and (not r['lpf_updated'] or r['quality_pending']):raise ValueError('Unqualified prefilter sample claims valid')
            if decision==16 and (r['lpf_updated'] or not r['quality_pending'] or not exit_reason&8):
                raise ValueError('Quarantine decision mismatch')
            if decision in (17,18,19) and (not r['lpf_updated'] or r['quality_pending']):
                raise ValueError('Quality recovery/seed not actual admitted pair')
        if r['valid'] and (status or not r['initialized']):raise ValueError('Trace validity contradiction')
        id_limit=.060 if direct else .05
        if status&256 and ((not persistent and not r['reset']) or c or r['initialized'] or b<=id_limit):
            raise ValueError('ID reset/gate/warmup mismatch')
        if persistent:
            if r['id_bad_confirmed'] and r['valid']:raise ValueError('Confirmed Id condition claims valid')
            if status&256 and (not r['id_bad_confirmed'] or r['reset'] and r['id_bad_us']<20000):
                raise ValueError('Id confirmation timer mismatch')
        if recoverable and decision==6:raise ValueError('Recoverable profile must not latch')
        if admission and decision in (2,3,5,6,7,9,10,11,12,13,15,16,17,18,19) and r['valid']:
            raise ValueError('Unqualified / gap recovery observation claims valid')
        if guarded and r['valid']:
            # Timestamp is reconstructed below, so validate source->publication
            # here and encoder relation after chronological reconstruction.
            if (r['adc_published_us']-r['adc_source_us'])&0xffffffff>100:
                raise ValueError('Valid guarded source/publication mismatch')
        return r
    start=(m['pre_head']-m['pre_count'])%pre_n
    pre=[read((start+i)%pre_n,'pre') for i in range(m['pre_count'])]
    t=m['pre_last_us']
    for r in reversed(pre):r['timestamp_us']=t;t=(t-r['interval_us'])&0xffffffff
    rows+=pre
    post=[read(pre_n+i,'dense_post') for i in range(m['post_count'])]
    tail=[read(pre_n+dense_n+i,'recovery_decimated') for i in range(m['tail_count'])]
    t=m['pre_last_us']
    for i,r in enumerate(post+tail):
        t=(t+r['interval_us'])&0xffffffff;r['timestamp_us']=t
        if i==0 and (not r['trigger'] or t!=m['trigger_us']):raise ValueError('Trigger timestamp/flag mismatch')
        if i and r['trigger']:raise ValueError('Multiple triggers')
        if r['phase']=='recovery_decimated' and r['interval_us']<(16000 if recoverable else 4000):raise ValueError('Tail cadence mismatch')
    rows+=post+tail
    if rows and rows[-1]['timestamp_us']!=m['last_stored_us']:raise ValueError('Trace endpoint mismatch')
    if guarded:
        for r in rows:
            if r['valid']:
                relative=((r['adc_source_us']-r['timestamp_us']+0x80000000)&0xffffffff)-0x80000000
                if not -200<=relative<=2000:raise ValueError('Valid guarded current/encoder relation')
    anchor=m['trigger_us'] if post else m['pre_last_us']
    for r in rows:r['relative_ms']=(((r['timestamp_us']-anchor+0x80000000)&0xffffffff)-0x80000000)*.001
    checks=dict(dense_pairs=0,max_lpf_residual_a=0.,id_reset_violations=0,
                warmup_reset_violations=0,max_warmup_increment_error_s=0.,hold_lpf_change_a=0.)
    last_accepted=None
    for prev,r in zip(rows,rows[1:]):
        if r['phase']=='recovery_decimated':continue
        checks['dense_pairs']+=1
        decision=r.get('admission_decision',0)
        dt=r['interval_us']
        if prefilter:
            if r['lpf_updated']:
                if r['filter_seeded']:expected=abs(r['id_meas_a'])
                elif last_accepted is not None:
                    gap=(r['timestamp_us']-last_accepted)&0xffffffff
                    expected=r['abs_id_lpf_before_a']+gap/(20000+gap)*(abs(r['id_meas_a'])-r['abs_id_lpf_before_a'])
                else:expected=r['abs_id_lpf_a'] # Missing preceding admitted timestamp; no fabricated interval.
                checks['max_lpf_residual_a']=max(checks['max_lpf_residual_a'],abs(expected-r['abs_id_lpf_a']))
                last_accepted=r['timestamp_us']
            else:
                checks['hold_lpf_change_a']=max(checks['hold_lpf_change_a'],abs(r['abs_id_lpf_a']-r['abs_id_lpf_before_a']))
                if decision in (13,16) and r['id_bad_us']!=prev['id_bad_us']:
                    raise ValueError('Rejected sample advanced or cleared Id timer')
            if r['reset'] and r['warmup_s']:checks['warmup_reset_violations']+=1
            if not r['reset'] and decision in (0,17,18,19) and r['initialized']:
                expected=prev['warmup_s']+(dt*1e-6 if prev['initialized'] and decision==0 else 0)
                checks['max_warmup_increment_error_s']=max(checks['max_warmup_increment_error_s'],abs(expected-r['warmup_s']))
            if decision==16 and r['reset_reason'] not in (0,8):raise ValueError('Single quarantine caused unnecessary reset')
            if r['raw_history_valid'] and prev['raw_history_valid'] and decision not in (7,9):
                if abs(r['id_adjacent_delta_a']-(r['id_meas_a']-prev['id_meas_a']))>1e-6:
                    raise ValueError('Raw adjacent Id delta mismatch')
            continue
        if admission and decision in (2,5,6,10,13,15):
            checks['hold_lpf_change_a']=max(checks['hold_lpf_change_a'],abs(r['abs_id_lpf_a']-prev['abs_id_lpf_a']))
        if not (r['status']&(64|128|512)) and (not r['status']&1024 or admission and decision in (3,11,12)):
            if admission and decision in (3,11):
                if last_accepted is None:continue
                dt=(r['timestamp_us']-last_accepted)&0xffffffff
            expected=abs(r['id_meas_a']) if r['filter_seeded'] else prev['abs_id_lpf_a']+dt/(20000+dt)*(abs(r['id_meas_a'])-prev['abs_id_lpf_a'])
            checks['max_lpf_residual_a']=max(checks['max_lpf_residual_a'],abs(expected-r['abs_id_lpf_a']))
        if not admission or decision in (0,1,3,4,9,11,12,14):last_accepted=r['timestamp_us']
        # V2 persistent transition resets THEN seeds the actual new pair in the
        # same call: initialized may be true, but elapsed must still be zero.
        if r['reset'] and (r['warmup_s'] or r['initialized'] and not (admission and decision==4 or guarded and decision==1 or recoverable and decision==12)):
            checks['warmup_reset_violations']+=1
        if not r['reset'] and r['initialized'] and (not admission or decision in (0,1,3,4,11,14)):
            expected=prev['warmup_s']+r['interval_us']*1e-6 if prev['initialized'] else 0.
            if admission and decision in (3,11):expected=prev['warmup_s']
            checks['max_warmup_increment_error_s']=max(checks['max_warmup_increment_error_s'],abs(expected-r['warmup_s']))
        if guarded and decision==9 and r['warmup_s']:checks['warmup_reset_violations']+=1
        if persistent and decision in (14,15):
            jump=max(abs(r['id_meas_a']-prev['id_meas_a']),abs(r['iq_meas_a']-prev['iq_meas_a']))
            if jump<=.100 or (decision==14 and not 1<=r['jump_run']<3) or (decision==15 and r['jump_run']<3):
                raise ValueError('Persistent raw-adjacent jump confirmation mismatch')
    note=('Id and LPF/warmup are from the same observer call. RESET is an actual reset hook. '
          '20 ms is abs(Id) LPF time constant, not a reset dwell. Warmup needs 5/g (~398 ms). '
          'Tail is decimated: intervening resets/samples may be absent. No 20 kHz waveform claim. '
          'V2 retains raw dq pair and admission decisions; held/recovery points are invalid, '
          'no warmup credit on recovery and no inferred missing current waveform.')
    if prefilter:
        note=('V7: suspect dq pairs quarantined BEFORE either DOB current LPF; only an actual qualified '
              'return near trusted baseline or the latest of3 coherent candidate points is admitted. '
              'No replay of stored suspects, no unverified raw-Id absolute bound. Rejections do not update '
              'LPFs, Id timer/baseline, warmup or valid statistics. Short-gap recovery is invalid; '
              'long gap>10ms resets recoverably. Existing20ms LPF and separate20ms Id confirmation remain. '
              'Actual same-epoch raw Id/delta, before/after LPF and reset reason are recorded. '
              'Tail is decimated; no complete20kHz waveform or hardware acceptance implied by offline fixtures.')
    elif persistent:
        note=('V6: raw-adjacent jumps >100mA are admitted as pending for the first2 consecutive points; '
              'rejection starts at point3. Id uses the existing20ms LPF PLUS a separate20ms '
              'continuous-high confirmation timer; ID entry resets once, then good evidence rewarms. '
              'Same-epoch RESET hook; short holds/recovery earn no warmup credit. '
              'Tail is decimated, not a consecutive waveform; no full20kHz ADC or closed-loop DOB claim.')
    return dict(meta=m,rows=rows,checks=checks,triggered=bool(post),complete=m['state']==3,
        filtered_abs_id_limit_a=.060 if direct else .05,
        reset_events=[r for r in rows if r['reset']],feedback_enabled=False,
        note=note)


def decode(receipt,elf):
    evidence=dob.decode(receipt,elf)
    from foc_path_profile_report import symbols
    r=json.loads(receipt.read_text());ram=Path(r['ram_capture']).read_bytes();sym=symbols(elf)
    def block(name,size):
        a,n=sym[name];o=a-0x20000000
        if n!=size or not 0<=o<=len(ram)-size:raise ValueError('Trace RAM symbol/bounds '+name)
        return ram[o:o+size]
    mechanical=block('mechanical_capture',4712)
    count,flags=struct.unpack_from('<I',mechanical,4612)[0],struct.unpack_from('<I',mechanical,4620)[0]
    if count or flags!=0x80000000:raise ValueError('Exclusive trace buffer owner required')
    result=decode_bytes(block('dob_id_trace',SIZE),mechanical[:4608])
    result.update(dob_capture=evidence,board_verified=True,session_hash=evidence['session_hash'])
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--receipt',required=True,type=Path)
    p.add_argument('--elf',required=True,type=Path);p.add_argument('--csv',action='store_true');a=p.parse_args()
    result=decode(a.receipt,a.elf)
    if a.csv:
        columns=('timestamp_us relative_ms phase id_meas_a abs_id_lpf_a warmup_s status '
                 'reset valid initialized filter_seeded trigger interval_us').split()
        if result['meta']['abi']>=2:columns+=['iq_meas_a','admission_decision','admission_name']
        if result['meta']['abi']>=3:columns+=['adc_seq','adc_source_us','adc_published_us','speed_ref_rpm','speed_meas_rpm']
        if result['meta']['abi']==7:
            columns+=['quality_reason','quality_reasons','id_adjacent_delta_a','abs_id_lpf_before_a',
                      'reset_reason','coherent_samples','quality_pending','raw_history_valid',
                      'lpf_updated','id_bad_confirmed','id_bad_us']
        elif result['meta']['abi']==6:columns+=['jump_run','id_bad_confirmed','id_bad_us']
        else:
            if result['meta']['abi']>=2:columns+=['admission_exit_reason']
            if result['meta']['abi']>=3:columns+=['qualify_us']
        writer=csv.DictWriter(sys.stdout,fieldnames=columns,extrasaction='ignore',lineterminator='\n')
        writer.writeheader();writer.writerows(result['rows'])
    else:print(json.dumps(result,indent=2,allow_nan=False))
