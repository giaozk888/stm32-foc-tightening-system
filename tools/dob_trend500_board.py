"""Normal500rpm overspeed configuration; one240rpm shadow/brake retest.

Reuse original single-START/calibration/protections/OFF-stage/OFF-restore path.
Frozen previous image must validate first. No devices without explicit CLI gates.
"""
import argparse
import json
from pathlib import Path
import dob_trend_shadow_board as old

base=old.base;normal=old.normal
ROOT_RESTORE=old.TMP/'dob-trend-restore-1792818484415940100.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/DobTrendShadowTrip500Candidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='2ea468d2c89cca5c6c9511d8e1fa1d2d12e6f1c77f68030a429f8cc020f5f445'
ELF_SHA='d677238588e43eb19ac687e68f20a373cff462930ca63f8e48b1f330807736b6'
SIZE=225940
LIMITS=dict(TARGET_RPM='240',GUARD_RPM='500',SPEED_TRIP_RPM='500',IQ_LIMIT_MA='500',
            TRAVEL_DEG='20000',LEASE_US='12000000')
OLD_CONFIGURE=old.configure;OLD_IMAGE=old.image;OLD_MOTION=old.motion
OLD_IDENTITY={key:getattr(old,key) for key in ('ROOT_RESTORE','IMAGE','ELF','SHA','ELF_SHA','SIZE')}
OLD_RECORD=old.record

def image():
    data=OLD_IMAGE() # Same old ABI checks; globals bind the new pinned identity after configure.
    command=next(x['command'] for x in json.loads((IMAGE.parent/'compile_commands.json').read_text()) if x['file'].endswith('/Core/Src/main.c'))
    if '-DFOC_NORMAL_RUN_TRIP500=1 ' not in command:raise ValueError('Normal500 build flag missing')
    if b'RUNDOWN240: RAM=240rpm TRIP=500rpm SAVE=OFF' not in data:raise ValueError('Normal500 boot marker missing')
    return data

def motion(board,row):
    row['normal_limits_before_start']=normal.check_values(board.command('MOTOR TEST MECH DOB LIMITS'),
        LIMITS,'Actual normal500 guard/speed thresholds and original target/Iq/travel/lease')
    OLD_MOTION(board,row)

def configure(path):
    for key,value in OLD_IDENTITY.items():setattr(old,key,value)
    OLD_CONFIGURE(ROOT_RESTORE) # Actual stopped B1201 and previous trend image, under its old identity.
    old.ROOT_RESTORE=ROOT_RESTORE
    for key in ('IMAGE','ELF','SHA','ELF_SHA','SIZE'):setattr(old,key,globals()[key])
    for key in ('IMAGE','ELF','SHA','ELF_SHA'):setattr(base,key,globals()[key])
    base.image=image;base.motion=motion
    if Path(path).resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(Path(path))
    return image()

def record(*args):
    row=OLD_RECORD(*args)
    row.update(overspeed_trip_rpm=500,normal_run_configuration=True,all_other_limits_preserved=True)
    return row

def main(argv=None):
    # The old main keeps the separate physical gates, one START and no retry.
    # Bind only its file identity/configuration entry; its decoder is unchanged.
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--baseline-restore',type=Path)
    args,remaining=parser.parse_known_args(argv)
    old.configure=configure;old.ROOT_RESTORE=args.baseline_restore or ROOT_RESTORE;old.record=record
    return old.main(remaining)

if __name__=='__main__':raise SystemExit(main())
