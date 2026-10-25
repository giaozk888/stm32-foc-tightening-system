"""File-only breakaway evaluator. NO serial, debugger, flash, motion or FF writes.

Default: NOT_MEASURED table. --elf/--ram/--flash/--vtor: a completed matching
breakaway capture. --replay-receipt: historical torque evidence, excluded from
breakaway estimates. --summary: aggregate distinct new-mode capture reports.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from app_a_source_layout import read_app_source
import re
import statistics
import struct
import torque_chain_decode as torque
from foc_path_profile_report import symbols
from loaded_fsm_snapshot_report import decode as decode_protection

ROOT=Path(__file__).resolve().parents[1]
CANDIDATES=(100,120,150,180,200,250)
MOTION=struct.Struct('<4I3i7Ii3I2H')
MOTION_NAMES=('count','first_us','last_us','max_gap_us','net_counts','positive_counts',
    'negative_counts','absolute_counts','forward','backward','stationary',
    'stationary_start_us','max_stationary_us','tail_absolute_counts','tail_net_counts',
    'bad_ref','bad_gates','bad_encoder','last_raw','reserved')


def policy(five_second=False):
    source=(ROOT/'firmware_common/foc_breakaway_current_test.h').read_text('utf-8')
    result={name:float(value) for name,value in re.findall(
        r'^#define (BREAKAWAY_\w+)\s+([0-9]+(?:\.[0-9]+)?)[fU]?\s*$',source,re.M)}
    if five_second:
        result.update(BREAKAWAY_TEST_DURATION_US=5000000,BREAKAWAY_RECORD_PERIOD_US=200000,
            BREAKAWAY_MIN_COVERAGE_US=4800000,BREAKAWAY_MAX_RECORD_GAP_US=220000,
            BREAKAWAY_MAX_END_RECORD_US=5050000)
    return result


def direct_limit_ma():
    values=[]
    for slot in 'ab':
        source=read_app_source(ROOT/f'foc2_app_{slot}/Core/Src/main.c',encoding='utf-8')
        values.append(round(float(re.search(r'^#define MOTOR_DIRECT_IQ_LIMIT_A\s+([0-9.]+)f',source,re.M)[1])*1000))
    if values[0]!=values[1]: raise ValueError('A/B direct limits differ')
    return values[0]


def digest(data): return hashlib.sha256(data).hexdigest()


def evaluate(report,iq_ma,sign,snapshot,limit_ma,verified=False,five_second=False,motion=None,actual_stop_us=None):
    if iq_ma not in CANDIDATES or sign not in (-1,1): raise ValueError('Explicit signed candidate required')
    p=policy(five_second); result=dict(report)
    result.update(diagnostic='FOC_BREAKAWAY_CURRENT_TEST',iq_mA=iq_ma,sign=sign,
        Iq_command_A=sign*iq_ma/1000,IdRef_A=0,limit_mA=limit_ma,policy=p,
        policy_sha256=digest((ROOT/'firmware_common/foc_breakaway_current_test.h').read_bytes()),
        capture_identity_verified=verified,control_write_performed=False,automatic_step=False,
        mechanical_or_torque_certified=False,classification='INSUFFICIENT_DATA',reasons=[])
    result.update(five_second=five_second,lease_us=int(p['BREAKAWAY_TEST_DURATION_US']))
    result['actual_output_stop_us']=actual_stop_us
    if five_second:
        result['interpretation']=[
            'Five-second lease; 200ms decimated dq/PWM frames plus task-rate raw encoder motion accumulation.',
            'Motion aggregate is not 20kHz or simultaneous ADC data; dq means use saved frames only.',
            'PWM applied is preload readback, not observed active gates. No physical torque certification.']
    fail=result['reasons']; rows=report.get('rows',[])
    result['protection']=snapshot
    if iq_ma>min(limit_ma,p['BREAKAWAY_CURRENT_MAX_MA']):
        result['classification']='LIMIT_BLOCKED'; fail.append('CURRENT_LIMIT'); return result
    if not rows or not snapshot or not isinstance(snapshot.get('timing'),dict) or not isinstance(snapshot.get('first_fault'),dict):
        fail.append('MISSING_ROWS_OR_PROTECTION_EVIDENCE'); return result
    required=('us','mechanical_angle_deg','IqRef_A','Iq_A','Id_A','mode','gates',
              'encoder_valid','encoder_glitch_streak','voltage_saturated','current_path')
    if any(k not in r or not isinstance(r[k],(int,float)) or not math.isfinite(r[k]) for r in rows for k in required):
        fail.append('NONFINITE_OR_MISSING_DATA'); return result
    t=snapshot['timing']; f=snapshot['first_fault']
    if any(k not in t or not isinstance(t[k],(int,float)) or not math.isfinite(t[k]) for k in
           ('wall_max_us','deadline_miss','actual_late_count','actual_margin_min_us')) or 'valid' not in f:
        fail.append('MISSING_TIMING_OR_FAULT_FIELDS'); return result
    if f['valid'] or report.get('first_flags') or report.get('fault_valid'):
        result['classification']='FAULT'; fail.append('PROTECTION_FAULT'); return result
    timing_ok=0<t['wall_max_us']<50 and t['deadline_miss']==0 and t['actual_late_count']==0 and t['actual_margin_min_us']>1
    if not timing_ok:
        result['classification']='TIMING_FAIL'; fail.append('FOC_OR_CCR_TIMING'); return result
    if any(abs(r['IqRef_A']-sign*iq_ma/1000)>1e-6 or r['mode']!=3 or r['gates']!=3 for r in rows):
        result['classification']='REFERENCE_MISMATCH'; fail.append('ACTUAL_IQ_OR_MODE_OR_GATES'); return result
    terminal=report.get('terminal')
    if (not isinstance(terminal,dict) or terminal.get('gates')!=0 or terminal.get('mode')!=0 or
            abs(terminal.get('IqRef_A',math.inf))>1e-6 or not report.get('frozen') or
            not p['BREAKAWAY_TEST_DURATION_US']<=terminal.get('us',0)<=p['BREAKAWAY_MAX_END_RECORD_US']):
        fail.append('END_NOT_PROVEN_OFF'); return result
    dt=[b['us']-a['us'] for a,b in zip(rows,rows[1:])]
    duration=rows[-1]['us']-rows[0]['us']
    if (len(rows)<p['BREAKAWAY_MIN_FRAMES'] or duration<p['BREAKAWAY_MIN_COVERAGE_US'] or
            not 0<=rows[0]['us']<=p['BREAKAWAY_MAX_FIRST_RECORD_US'] or
            rows[-1]['us']>p['BREAKAWAY_TEST_DURATION_US'] or not dt or min(dt)<=0 or
            max(dt)>p['BREAKAWAY_MAX_RECORD_GAP_US']):
        fail.append('SHORT_OR_GAPPED_WINDOW'); return result
    if any(not r['encoder_valid'] or r['encoder_glitch_streak'] for r in rows):
        fail.append('ENCODER_INVALID'); return result
    if any(r['voltage_saturated'] for r in rows): fail.append('VOLTAGE_SATURATED')
    step=[sign*(b['mechanical_angle_deg']-a['mechanical_angle_deg']) for a,b in zip(rows,rows[1:])]
    net=sum(step); absolute=sum(abs(x) for x in step); resolution=360/16384
    moving=[x for x in step if abs(x)>resolution]
    forward=sum(x>resolution for x in step)
    forward_fraction=forward/len(moving) if moving else 0
    moving_fraction=len(moving)/len(step)
    longest=0; held=0
    for d,us in zip(step,dt):
        held=held+us if abs(d)<=resolution else 0; longest=max(longest,held)
    tail=[r for r in rows if r['us']>=rows[0]['us']+duration*2/3]
    tail_travel=sign*(tail[-1]['mechanical_angle_deg']-tail[0]['mechanical_angle_deg']) if len(tail)>1 else 0
    iq=statistics.fmean(r['Iq_A'] for r in rows); target=sign*iq_ma/1000
    mae=statistics.fmean(abs(r['Iq_A']-target) for r in rows)
    wrong=sum(sign*r['Iq_A']<0 for r in rows)/len(rows)
    path_ratio=absolute/net if net>resolution else None
    if five_second:
        # Preserve the original binary aggregate even when admission below
        # rejects it. Otherwise a boundary failure hides its own evidence.
        # This is diagnostic output only: no tolerance/decision is changed.
        result['full_window_motion']=motion
        stop_boundary=p['BREAKAWAY_TEST_DURATION_US']
        if actual_stop_us is not None:
            if not stop_boundary<=actual_stop_us<=terminal['us']:
                fail.append('INVALID_ACTUAL_OUTPUT_STOP'); return result
            stop_boundary=actual_stop_us
        if (not isinstance(motion,dict) or set(MOTION_NAMES)!=set(motion) or
            motion['count']<4000 or motion['last_us']-motion['first_us']<4800000 or
            motion['first_us']>20000 or motion['last_us']>stop_boundary or
            motion['max_gap_us']>20000 or any(motion[k] for k in ('bad_ref','bad_gates','bad_encoder')) or
            motion['forward']+motion['backward']+motion['stationary']!=motion['count']-1 or
            motion['absolute_counts']<abs(motion['net_counts'])):
            fail.append('MISSING_OR_INVALID_FULL_WINDOW_MOTION'); return result
        net=sign*motion['net_counts']*resolution
        absolute=motion['absolute_counts']*resolution
        moving_n=motion['forward']+motion['backward']
        forward_fraction=motion['forward']/moving_n if moving_n else 0
        # Motion rate at task resolution is reported, but the minimum moving
        # fraction uses 200ms intervals: slow real motion can be <1 LSB/ms.
        longest=motion['max_stationary_us']
        tail_travel=sign*motion['tail_net_counts']*resolution
        path_ratio=absolute/net if net>resolution else None
        result['full_window_motion']=motion
        result['motion_sample_count']=motion['count']
        result['decimated_statistics']=dict(report.get('statistics') or {})
        result['statistics']=dict(report.get('statistics') or {})
        result['statistics'].update(net_mechanical_travel_deg=motion['net_counts']*resolution,
            mechanical_travel_deg=motion['net_counts']*resolution,total_absolute_travel_deg=absolute,
            max_positive_excursion_deg=motion['positive_counts']*resolution,
            max_negative_excursion_deg=motion['negative_counts']*resolution,
            max_negative_excursion_abs_deg=-motion['negative_counts']*resolution,
            motion_statistics_source='fresh outer-task raw encoder aggregate; dq means from saved frames')
    criteria=dict(direction=net>resolution,
        net_travel=net>=p['BREAKAWAY_MIN_NET_TRAVEL_DEG'],
        path_to_net=path_ratio is not None and path_ratio<=p['BREAKAWAY_MAX_PATH_TO_NET_RATIO'],
        direction_fraction=forward_fraction>=p['BREAKAWAY_MIN_FORWARD_FRACTION'],
        moving_fraction=moving_fraction>=p['BREAKAWAY_MIN_MOVING_FRACTION'],
        no_long_stationary=longest<=p['BREAKAWAY_MAX_STATIONARY_US'],
        tail_keeps_moving=tail_travel>=p['BREAKAWAY_MIN_TAIL_TRAVEL_DEG'],
        iq_mean=abs(iq-target)<=max(p['BREAKAWAY_IQ_ERROR_FLOOR_A'],abs(target)*p['BREAKAWAY_IQ_MEAN_ERROR_RATIO']),
        iq_mae=mae<=max(p['BREAKAWAY_IQ_ERROR_FLOOR_A'],abs(target)*p['BREAKAWAY_IQ_MAE_RATIO']),
        iq_direction=wrong<=p['BREAKAWAY_MAX_WRONG_IQ_FRACTION'],
        accepted_current=sum(r['current_path']==1 for r in rows)/len(rows)>=p['BREAKAWAY_MIN_ACCEPTED_FRACTION'],
        not_saturated=not any(r['voltage_saturated'] for r in rows))
    fail.extend(k for k,v in criteria.items() if not v and k.upper() not in fail)
    result['criteria']=criteria
    result['motion_metrics']=dict(signed_net_travel_deg=net,total_absolute_travel_deg=absolute,
        path_to_net_ratio=path_ratio,forward_fraction=forward_fraction,moving_fraction=moving_fraction,
        max_stationary_us=longest,tail_signed_travel_deg=tail_travel,
        mean_Iq_A=iq,iq_mae_A=mae,wrong_iq_fraction=wrong)
    if net < -resolution: label='WRONG_DIRECTION'
    elif absolute<=p['BREAKAWAY_NO_MOTION_TRAVEL_DEG']: label='NO_MOTION'
    elif all(criteria.values()): label='CONTINUOUS_ROTATION'
    elif any(not criteria[k] for k in ('path_to_net','direction_fraction','moving_fraction','no_long_stationary','tail_keeps_moving')): label='STICK_SLIP'
    else: label='MARGINAL'
    result['classification']=label
    result['conclusion']=f'Iq={target:+.2f} A -> {label} (decimated software evidence only)'
    return result


def capture_report(elf,ram_path,flash_path,vtor):
    image=elf.with_suffix('.bin').read_bytes(); flash=flash_path.read_bytes(); ram=ram_path.read_bytes()
    if vtor not in (0x08008000,0x08040000) or len(flash)!=0x80000 or flash[vtor-0x08000000:vtor-0x08000000+len(image)]!=image:
        raise ValueError('Matching full Flash / BIN / capture VTOR required')
    table=symbols(elf)
    if struct.unpack_from('<I',image,4)[0]!=(table['Reset_Handler'][0]|1):
        raise ValueError('ELF and BIN reset identity mismatch')
    def scalar(name,size):
        address,actual=table[name]
        source,base=(flash,0x08000000) if 0x08000000<=address<0x08080000 else (ram,0x20000000)
        off=address-base
        if actual!=size or off<0 or off+size>len(source): raise ValueError('Breakaway metadata ABI mismatch')
        return int.from_bytes(source[off:off+size],'little')
    tag=scalar('breakaway_capture_tag',4)
    if tag not in (0x42574159,0x42574135): raise ValueError('Not a breakaway capture')
    five_second=tag==0x42574135
    limit=scalar('breakaway_direct_limit_ma',2)
    m=torque.metadata(elf,ram,0x20000000,'arm-none-eabi-nm')
    if not m['used'] or any(m[k] for k in ('active','admitting','queued','denied')) or m['offset_electrical_deg']!=0:
        raise ValueError('Require completed, admitted, zero-offset manual capture')
    if m['iq_mA'] not in CANDIDATES or m['sign'] not in (-1,1): raise ValueError('Invalid capture selection')
    data=torque.startup.extract(elf,ram,0x20000000,'arm-none-eabi-nm')
    trace=torque.analyze_samples(data,m['sign'],0,m['iq_mA'])
    motion=None; actual_stop_us=None
    if five_second:
        address,size=table['breakaway_motion']; offset=address-0x20000000
        if size!=MOTION.size or offset<0 or offset+size>len(ram): raise ValueError('Motion ABI mismatch')
        motion=dict(zip(MOTION_NAMES,MOTION.unpack_from(ram,offset)))
        address,size=table['cl_session']; offset=address-0x20000000
        if size!=12 or offset<0 or offset+size>len(ram): raise ValueError('Session ABI mismatch')
        start=int.from_bytes(ram[offset:offset+4],'little')
        if start!=trace['start_us']: raise ValueError('Trace/session start mismatch')
        actual_stop_us=(scalar('cl_stop_us',4)-start)&0xffffffff
    result=evaluate(trace,m['iq_mA'],m['sign'],decode_protection(ram,elf),limit,True,five_second,motion,actual_stop_us)
    result.update(evidence_kind='breakaway_capture',metadata=m,
        flash_sha256=digest(flash),ram_sha256=digest(ram),elf_sha256=digest(elf.read_bytes()),
        capture_id=digest(flash)+':'+digest(ram),
        inputs=dict(elf=str(elf.resolve()),ram=str(ram_path.resolve()),flash=str(flash_path.resolve()),vtor=vtor))
    return result


def replay_receipt(path):
    r=json.loads(path.read_text('utf-8')); trace=r['torque_diagnostic']; m=trace['metadata']
    result=evaluate(trace,m['iq_mA'],m['sign'],r.get('snapshot'),direct_limit_ma(),False)
    result.update(evidence_kind='historical_torque_replay',source=str(path),capture_id=None,
        note='Historical different diagnostic/initial angle, not a new breakaway experiment; excluded from minima.')
    return result


def summarize(reports):
    cohorts={bool(r.get('five_second')) for r in reports if r.get('evidence_kind')=='breakaway_capture'}
    if len(cohorts)>1: raise ValueError('Do not mix 200ms and five-second breakaway cohorts')
    p=policy(); limit=direct_limit_ma(); grouped={}; seen=set(); repeats=int(p['BREAKAWAY_MIN_CONFIRMED_REPEATS'])
    for r in reports:
        if r.get('evidence_kind')!='breakaway_capture' or not r.get('capture_identity_verified'): continue
        key=r.get('capture_id')
        if not key or key in seen: continue
        seen.add(key)
        if r.get('policy_sha256')!=digest((ROOT/'firmware_common/foc_breakaway_current_test.h').read_bytes()): continue
        ma=r.get('iq_mA'); sign=r.get('sign')
        if ma not in CANDIDATES or sign not in (-1,1) or ma>min(limit,r.get('limit_mA',0)): continue
        grouped.setdefault((sign,ma),[]).append(r)
    table=[]; minimum={}; observed={}; no_continuous_through={}
    for sign,label in ((1,'POS'),(-1,'NEG')):
        observed[label]=None; minimum[label]=None; no_continuous_through[label]=None
        for ma in CANDIDATES:
            batch=grouped.get((sign,ma),[]); count=sum(x['classification']=='CONTINUOUS_ROTATION' for x in batch)
            table.append(dict(direction=label,iq_mA=ma,trials=len(batch),continuous=count,
                status='LIMIT_BLOCKED' if ma>limit else 'NOT_MEASURED' if not batch else ' / '.join(x['classification'] for x in batch)))
            if count and observed[label] is None: observed[label]=ma/1000
            lower=[n for n in CANDIDATES if n<ma and n<=limit]
            complete_lower=all(len(grouped.get((sign,n),[]))>=repeats for n in lower)
            if minimum[label] is None and count>=repeats and count==len(batch) and complete_lower:
                minimum[label]=ma/1000
            if complete_lower and len(batch)>=repeats and not count and not any(
                x['classification']=='CONTINUOUS_ROTATION' for n in lower for x in grouped.get((sign,n),[])):
                no_continuous_through[label]=ma/1000
    pos,neg=minimum['POS'],minimum['NEG']; asymmetric=None
    if pos is not None and neg is not None: asymmetric=abs(pos-neg)/min(pos,neg)>p['BREAKAWAY_ASYMMETRY_RATIO']
    ff={k:math.ceil(v*(1+p['BREAKAWAY_FF_MARGIN_RATIO'])*1000-1e-9)/1000 if v is not None else None for k,v in minimum.items()}
    requested=max(ff.values()) if all(v is not None for v in ff.values()) else None
    usable=requested if requested is not None and requested<=limit/1000 else None
    return dict(status='OBSERVED_GRID_BREAKAWAY' if pos is not None and neg is not None else 'WAITING_MANUAL_BOARD_TESTS',table=table,
        five_second=True in cohorts,
        observed_min_continuous_A=observed,BREAKAWAY_IQ_POS=pos,BREAKAWAY_IQ_NEG=neg,
        no_continuous_through_A=no_continuous_through,
        IQ_FRICTION_FF=usable,ff_requested_A=requested,ff_by_direction_A=ff,
        ff_limit_blocked=requested is not None and usable is None,asymmetric=asymmetric,
        margin_ratio=p['BREAKAWAY_FF_MARGIN_RATIO'],direct_limit_A=limit/1000,
        confirmed_repeats_required=repeats,automatic_control_write=False,
        note='Minima are candidate-grid observations, not torque calibration; missing lower grades or repeats stay unknown. Never average asymmetric directions.')


def load_summary_report(path):
    stored=json.loads(path.read_text('utf-8'))
    if stored.get('evidence_kind')!='breakaway_capture': return stored
    inputs=stored.get('inputs',{})
    if set(inputs)!={'elf','ram','flash','vtor'}: raise ValueError('Capture reports need original source files for summary')
    fresh=capture_report(Path(inputs['elf']),Path(inputs['ram']),Path(inputs['flash']),inputs['vtor'])
    if any(fresh.get(k)!=stored.get(k) for k in ('capture_id','elf_sha256','policy_sha256')):
        raise ValueError('Capture files or classifier policy changed; re-decode explicitly')
    return fresh # Never trust an edited classification in report JSON.


def main():
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group()
    group.add_argument('--replay-receipt',type=Path)
    group.add_argument('--summary',type=Path,nargs='+')
    p.add_argument('--elf',type=Path); p.add_argument('--ram',type=Path); p.add_argument('--flash',type=Path)
    p.add_argument('--vtor',type=lambda x:int(x,0))
    a=p.parse_args(); capture=any(x is not None for x in (a.elf,a.ram,a.flash,a.vtor))
    if capture:
        if not all(x is not None for x in (a.elf,a.ram,a.flash,a.vtor)) or a.summary or a.replay_receipt:
            p.error('Use --elf --ram --flash --vtor together, with no replay/summary')
        result=capture_report(a.elf,a.ram,a.flash,a.vtor)
    elif a.replay_receipt: result=replay_receipt(a.replay_receipt)
    else: result=summarize([load_summary_report(path) for path in a.summary] if a.summary else [])
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=='__main__': main()
