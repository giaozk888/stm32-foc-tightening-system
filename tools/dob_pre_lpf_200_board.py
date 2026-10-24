"""One supervised 600rpm / 200mA pre-LPF DOB shadow run; files-only default."""
import json
from pathlib import Path
import sys
import dob_id_pre_lpf_board as previous

low=previous.low
ROOT_RESTORE=low.TMP/'mechanical-ident-restore-1792733313738259200.json'
IMAGE=low.base.old.ROOT/'foc2_app_a/build/MechanicalDobPreLpf200Candidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='5bd9e2c52ffaeecf70d8c0b35f981b90e0bfa250aa3ae39620f2a5b411346301'
ELF_SHA='eba0c08a3b8c76bee758570fe88b077ee89c18a05c69d660640b8cf6072930a3'
SIZE=216620
POINTS=(600,)
CONFIG=dict(previous.CONFIG,JUMP_UA='200000')
ORIGINAL_SETUP=previous.setup
ORIGINAL_IMAGE=previous.image
ORIGINAL_RUN=previous.run_point

def image():
    # The previous validator reads its module identity. Scope overrides for
    # files-only validation; preserve old receipt identity until setup proves it.
    names=('IMAGE','ELF','SHA','ELF_SHA','SIZE')
    old=tuple(getattr(previous,n) for n in names)
    try:
        for n in names:setattr(previous,n,globals()[n])
        data=ORIGINAL_IMAGE()
    finally:
        for n,v in zip(names,old):setattr(previous,n,v)
    commands=json.loads((IMAGE.parent/'compile_commands.json').read_text())
    cmd=next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
    if 'DOB_ADMIT_JUMP_A=.200f' not in cmd:
        raise ValueError('Exact compiled 200mA threshold required')
    return data

def run_point(row,*args):
    ORIGINAL_RUN(row,*args)
    row['admission_quality']['jump_a']=.200
    row['admission_quality']['threshold_identity']='compiled .200f and UART 200000uA'

def setup(path):
    # First verify actual prior V7/B1075 restore under the original 100mA image.
    ORIGINAL_SETUP(ROOT_RESTORE);low.base.baseline()
    for n in ('IMAGE','ELF','SHA','ELF_SHA','SIZE'):
        setattr(previous,n,globals()[n]);setattr(low,n,globals()[n])
    previous.CONFIG=CONFIG
    low.image,low.run_point,low.MechanicalBoard=image,run_point,previous.PreLpfBoard
    low.base.staged=previous.staged
    for obj in (low.base,low.previous.gain,low.fitted):
        obj.IMAGE,obj.ELF,obj.SHA,obj.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA;obj.image=image
    low.previous.gain.SIZE=low.fitted.SIZE=SIZE
    if path.resolve()!=ROOT_RESTORE.resolve():low.base.configure_baseline(path)
    return image()

def execute(path,parent):
    previous.execute(path,parent)
    parent['note']='200mA trusted pre-LPF DOB quarantine; one600rpm shadow run, no feedback or retry.'

def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if '--execute-once' in args:args[args.index('--execute-once')]='--execute-six'
    if '--baseline-restore' not in args and not any(x in args for x in ('--execute-six','--restore-b-drive-off')):
        args+=['--baseline-restore',str(ROOT_RESTORE)]
    low.setup,low.POINTS,low.execute=setup,POINTS,execute
    low.TRIP_RPM,low.TRAVEL_DEG,low.CLOSURE_SECONDS,low.LIMITS_QUERY=1000,30000,11.,True
    low.LIMITS_EXTRA=dict(PLAUSIBLE_RPM='1000',REJECT_BUSY='1',OBS_AFTER_ACK='1')
    return low.main(args)

if __name__=='__main__':raise SystemExit(main())
