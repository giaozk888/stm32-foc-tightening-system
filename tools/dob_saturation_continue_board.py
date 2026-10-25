"""One supervised normal500/240rpm measurement-valid saturation observation.
Original feedback hold/fade/limits, separate physical stage/run/restore gates.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import dob_trend_continuous_board as previous

base=previous.base;normal=previous.normal
ROOT_RESTORE=previous.TMP/'dob-trend-continuous-restore-1792820964519768800.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/DobSaturationContinuousCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='43f3188b07eca8440bd2e140d6a0d8e6783d3e9ae9a4636548ea466589a9751f'
ELF_SHA='22d45928b1496ef4078076ed1cbc71d1e6a2c32d109919ea7fe502e3a3ffa1ec'
SIZE=226792
CONFIG=dict(V='1',EST_ON_LIMIT='1',FB_ON_LIMIT='0',INPUT_GATES='ORIGINAL',HOLD_US='5000',ZERO_US='20000')
OLD_CONFIGURE=previous.configure;OLD_IMAGE=previous.image;OLD_MOTION=previous.motion
OLD_DECODE=previous.decode;OLD_RECORD=previous.record
OLD_IDENTITY={k:getattr(previous,k) for k in ('ROOT_RESTORE','IMAGE','ELF','SHA','ELF_SHA','SIZE')}
AUDIT_KEYS='samples iq_limited voltage_limited limited_valid input_resets feedback_blocks current_skips warmup_frames'.split()

def image():
    data=IMAGE.read_bytes()
    if len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA:
        raise ValueError('Pinned saturation image/ELF mismatch')
    cmd=next(x['command'] for x in json.loads((IMAGE.parent/'compile_commands.json').read_text()) if x['file'].endswith('/Core/Src/main.c'))
    for flag in ('FOC_DOB_SATURATION_CONTINUE=1','FOC_DOB_TREND_CONTINUOUS=1','FOC_NORMAL_RUN_TRIP500=1',
                 'FOC_DOB_NORMAL_CONTROL=1','FOC_DOB_CONTACT20_OBSERVE10=1','FOC_ONE_CYCLE_PWM_PIPELINE=1',
                 'FOC_DOB_ID_PRE_LPF_QUALITY=1','DOB_ADMIT_JUMP_A=.200f'):
        if '-D'+flag+' ' not in cmd:raise ValueError('Required profile '+flag)
    for flag in ('FOC_DOB_REAL_TRACE','FOC_DOB_ID_TRACE','FOC_DOB_GAIN_AB_DIAG','FOC_MECHANICAL_HIGH_SPEED_DIAG'):
        if '-D'+flag+'=1 ' in cmd:raise ValueError('Conflicting profile '+flag)
    symbols=base.symbols(ELF)
    for name,size in dict(dob_saturation_audit=32,dob_trend_continuous=100,dob_trend_continuous_arena=4,
                          mechanical_capture=4712,dob_feedback=80,mechanical_dob_monitor=856,dob_current_admission=204).items():
        if symbols.get(name,(0,0))[1]!=size:raise ValueError('Candidate ABI '+name)
    if base.hw.image_info(data)[0]!='A' or b'RUNDOWN240: RAM=240rpm TRIP=500rpm SAVE=OFF' not in data:
        raise ValueError('A/normal500 identity missing')
    return data

def configure(path):
    for k,v in OLD_IDENTITY.items():setattr(previous,k,v)
    OLD_CONFIGURE(ROOT_RESTORE) # Validate original stopped B1213/continuous image first.
    for k in ('IMAGE','ELF','SHA','ELF_SHA','SIZE'):setattr(previous,k,globals()[k])
    previous.ROOT_RESTORE=ROOT_RESTORE
    for k in ('IMAGE','ELF','SHA','ELF_SHA'):setattr(base,k,globals()[k])
    base.image=image;base.motion=motion;base.decode_cm=decode
    if Path(path).resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(Path(path))
    return image()

def motion(board,row):
    row['saturation_config']=normal.check_values(board.command('MOTOR TEST MECH DOB SAT CFG'),CONFIG,
        'Estimation only during limitation, original feedback hold/fade')
    try:OLD_MOTION(board,row)
    finally:row['postflight']['MOTOR TEST MECH DOB SAT STATS']=board.command('MOTOR TEST MECH DOB SAT STATS')

def decode(row):
    OLD_DECODE(row)
    ram=Path(row['ram_capture']).read_bytes();a,n=base.symbols(ELF)['dob_saturation_audit']
    offset=a-0x20000000
    if n!=32 or not 0<=offset<=len(ram)-n:raise ValueError('Saturation audit RAM bounds')
    stats=dict(zip(AUDIT_KEYS,struct.unpack_from('<8I',ram,offset)))
    if (stats['samples']!=row['trend_capture']['header']['observations'] or
        stats['limited_valid']>stats['iq_limited']+stats['voltage_limited'] or
        any(stats[k]>stats['samples'] for k in ('iq_limited','voltage_limited','input_resets','current_skips','warmup_frames'))):
        raise ValueError('Saturation audit counters inconsistent')
    row['saturation_audit']=stats
    row['trend_capture']['semantics']+=' SAT128 may coexist with estimator valid; fresh feedback explicitly blocks SAT128.'

def record(*args):
    row=OLD_RECORD(*args)
    row.update(image_sha256=SHA,elf_sha256=ELF_SHA,saturation_estimation_continuity=True,
        saturation_fresh_feedback=False,all_other_limits_preserved=True)
    return row

def main(argv=None):
    parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--baseline-restore',type=Path)
    args,remaining=parser.parse_known_args(argv)
    previous.configure=configure;previous.ROOT_RESTORE=args.baseline_restore or ROOT_RESTORE
    previous.record=record
    return previous.main(remaining)

if __name__=='__main__':raise SystemExit(main())
