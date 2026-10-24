"""Frozen DOB gain0.15, three600rpm ON runs; files-only default."""
from pathlib import Path
import sys
import dob_feedback_gainhalf_board as prior_profile

previous=prior_profile.previous
fb=previous.fb
low=previous.low
ROOT_RESTORE=low.TMP/'mechanical-ident-restore-1792739258244032100.json'
IMAGE=low.base.old.ROOT/'foc2_app_a/build/MechanicalDobFeedbackGain015Candidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='ee8481cdae09e92b4c4417a542be2f08580013a0f88e0aef4cd6acdae06f1fee'
ELF_SHA='dede33e009586b7aaae384d76369e523b943d3ef735635ab7d67e783bd0a8a99'
SIZE=219860
GAIN=.15
SUMMARY_KEY='gain015_summary'
FB_CONFIG=dict(prior_profile.FB_CONFIG,GAIN_PPM='150000')
ORIGINAL_SETUP=prior_profile.setup
ORIGINAL_IMAGE=prior_profile.ORIGINAL_IMAGE

def image():
    names=('IMAGE','ELF','SHA','ELF_SHA','SIZE','GAIN')
    saved=tuple(getattr(previous,n) for n in names)
    try:
        for n in names:setattr(previous,n,globals()[n])
        return ORIGINAL_IMAGE()
    finally:
        for n,v in zip(names,saved):setattr(previous,n,v)

def setup(path):
    ORIGINAL_SETUP(ROOT_RESTORE);low.base.baseline() # Verify actual gain0.5 / B1099 first.
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
