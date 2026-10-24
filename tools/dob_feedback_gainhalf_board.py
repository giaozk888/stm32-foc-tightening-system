"""Frozen DOB gain0.5, three600rpm ON runs; files-only default."""
from pathlib import Path
import sys
import dob_feedback_gain1_board as previous

fb=previous.fb
low=previous.low
ROOT_RESTORE=low.TMP/'mechanical-ident-restore-1792738356256376500.json'
IMAGE=low.base.old.ROOT/'foc2_app_a/build/MechanicalDobFeedbackGainHalfCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='3508081b2835eb4668aba861cfdc3abc3061948c37bd01be405d42e8eb74e474'
ELF_SHA='f8400b14bc1d009c11ca78cc027615533241de6e845ae7b9e3b9e821a4ccec2c'
SIZE=219860
GAIN=.5
SUMMARY_KEY='gainhalf_summary'
FB_CONFIG=dict(previous.FB_CONFIG,GAIN_PPM='500000')
ORIGINAL_SETUP=previous.setup
ORIGINAL_IMAGE=previous.image

def image():
    names=('IMAGE','ELF','SHA','ELF_SHA','SIZE','GAIN')
    saved=tuple(getattr(previous,n) for n in names)
    try:
        for n in names:setattr(previous,n,globals()[n])
        return ORIGINAL_IMAGE()
    finally:
        for n,v in zip(names,saved):setattr(previous,n,v)

def setup(path):
    ORIGINAL_SETUP(ROOT_RESTORE);low.base.baseline() # Actual gain1 / B1095 before installing .5.
    for n in ('IMAGE','ELF','SHA','ELF_SHA','SIZE'):
        for obj in (previous,fb,low):setattr(obj,n,globals()[n])
    previous.GAIN=GAIN;previous.SUMMARY_KEY=SUMMARY_KEY;previous.image=image
    fb.FB_CONFIG=FB_CONFIG
    low.image,low.run_point,low.MechanicalBoard=image,fb.run_point,fb.FeedbackBoard
    low.base.staged=fb.v7.staged
    for obj in (low.base,low.previous.gain,low.fitted):
        obj.IMAGE,obj.ELF,obj.SHA,obj.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA;obj.image=image
    low.previous.gain.SIZE=low.fitted.SIZE=SIZE
    if path.resolve()!=ROOT_RESTORE.resolve():low.base.configure_baseline(path)
    return image()

def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if '--execute-three' in args:args[args.index('--execute-three')]='--execute-six'
    if '--baseline-restore' not in args and not any(x in args for x in ('--execute-six','--restore-b-drive-off')):
        args+=['--baseline-restore',str(ROOT_RESTORE)]
    fb.FEEDBACK_ON=False
    low.setup,low.POINTS,low.execute=setup,(600,),previous.execute
    low.TRIP_RPM,low.TRAVEL_DEG,low.CLOSURE_SECONDS,low.LIMITS_QUERY=1000,30000,11.,True
    low.LIMITS_EXTRA=dict(PLAUSIBLE_RPM='1000',REJECT_BUSY='1',OBS_AFTER_ACK='1')
    return low.main(args)

if __name__=='__main__':raise SystemExit(main())
