"""One supervised 600rpm outer-completion A retest; FILES ONLY default."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import mechanical_encoder_fix_board as previous

low=previous.low
ROOT_RESTORE=low.TMP/'mechanical-ident-restore-1792672777028793500.json'
IMAGE=low.base.old.ROOT/'foc2_app_a/build/MechanicalOuterCompletionCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='e2f875992a94830d729155137d7aa70fee48feec6f801f61f3788c65db7b0e84'
ELF_SHA='6b2ed548cb4751f6dc99b8f16ade53c59667dc0751d576ee7ff06a4348bc6a8f'
SIZE=209084
ORIGINAL_SETUP=previous.setup
ORIGINAL_RUN=low.run_point
FRAME_KEYS='entry_us consume_us sample_us sequence commit_us observe_begin_us observe_end_us status phase'.split()


def image():
    data=previous.validate_image(IMAGE,ELF,SHA,ELF_SHA,SIZE,
        extra_flags=('FOC_OUTER_OBSERVE_AFTER_ACK=1',),extra_markers=(b'OBS_AFTER_ACK=1',))
    if low.base.symbols(ELF).get('outer_completion_trace',(0,0))[1]!=644:
        raise ValueError('Reviewed task timing ABI required')
    return data


def decode_trace(row,*,elf=ELF,elf_sha=ELF_SHA):
    raw=Path(row['ram_capture']).read_bytes()
    if (len(raw)!=0x20000 or hashlib.sha256(raw).hexdigest()!=row['ram_sha256'] or
        row['elf_sha256']!=elf_sha or hashlib.sha256(elf.read_bytes()).hexdigest()!=elf_sha):
        raise ValueError('Same-session task timing RAM/ELF required')
    addr,size=low.base.symbols(elf)['outer_completion_trace'];offset=addr-0x20000000
    if size!=644 or not 0<=offset<=len(raw)-size:raise ValueError('Task timing ABI/bounds')
    def frame(at):return dict(zip(FRAME_KEYS,struct.unpack_from('<9I',raw,at)))
    current=frame(offset+16*36)
    keys='head count frozen fault_phase last_entry_us max_entry_gap_us max_core_us max_observe_us'.split()
    meta=dict(zip(keys,struct.unpack_from('<8I',raw,offset+17*36)))
    if meta['head']>=16:raise ValueError('Task timing ring head invalid')
    n=min(max(0,meta['count']-1),16)
    frames=[frame(offset+((meta['head']-n+i)%16)*36) for i in range(n)]
    return dict(meta=meta,current=current,frames=frames,
        phases={'1':'task entry','2':'fresh sample consumed','3':'core completed and ACK/outer heartbeat published',
                '4':'non-control observations','5':'observations completed'},
        limitation='Task-only timestamps include IRQ preemption. Maxima include preflight; first fault freezes phase. No new watchdog ACK or control write.')


def run_point(row,*args):
    try:return ORIGINAL_RUN(row,*args)
    finally:
        if row.get('ram_capture'):row['outer_completion_trace']=decode_trace(row)


def setup(path):
    ORIGINAL_SETUP(ROOT_RESTORE);low.base.baseline() # Prove the actual prior fixed A first.
    low.IMAGE,low.ELF,low.SHA,low.ELF_SHA,low.SIZE=IMAGE,ELF,SHA,ELF_SHA,SIZE
    low.image=image;low.run_point=run_point
    for obj in (low.base,low.previous.gain,low.fitted):
        obj.IMAGE,obj.ELF,obj.SHA,obj.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA;obj.image=image
    low.previous.gain.SIZE=SIZE;low.fitted.SIZE=SIZE
    if path.resolve()!=ROOT_RESTORE.resolve():low.base.configure_baseline(path)
    return image()


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if '--execute-once' in args:args[args.index('--execute-once')]='--execute-six'
    if '--baseline-restore' not in args and not any(x in args for x in ('--execute-six','--restore-b-drive-off')):
        args+=['--baseline-restore',str(ROOT_RESTORE)]
    low.setup=setup;low.POINTS=(600,);low.TRIP_RPM=1000;low.TRAVEL_DEG=30000
    low.CLOSURE_SECONDS=11.;low.LIMITS_QUERY=True
    low.LIMITS_EXTRA=dict(PLAUSIBLE_RPM='1000',REJECT_BUSY='1',OBS_AFTER_ACK='1')
    return low.main(args)


if __name__=='__main__':raise SystemExit(main())
