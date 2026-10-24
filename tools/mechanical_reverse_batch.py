"""Reverse identification A, -600/-700/-800rpm x3; FILES ONLY default.

No automatic motion on boot, retries, threshold changes or DOB actuation.
An actual reverse-safe mechanical setup and fresh OFF/ON confirmations are
required by the retained staging/whole-batch operator gates.
"""
import json
from pathlib import Path
import sys
import readiness_snapshot_batch as previous

low=previous.low
ROOT_RESTORE=low.TMP/'mechanical-ident-restore-1792679166747314300.json'
POSITIVE_BATCH=low.TMP/'mechanical-ident-batch-1792675998078677600.json'
IMAGE=low.base.old.ROOT/'foc2_app_a/build/MechanicalReverseIdentificationCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='cad191865cadd1e8dc8377f79e36341170e07c414b8b7defbb4c4d4e40d8f57d'
ELF_SHA='8fddaa5264301f04428c413970609318b72f06cefa414f494b4d608b5aac47dc'
SIZE=209744
POINTS=(-600,-600,-600,-700,-700,-700,-800,-800,-800)
ORIGINAL_SETUP=previous.setup
ORIGINAL_RUN=previous.ORIGINAL_RUN
ORIGINAL_STAGED=previous.ORIGINAL_STAGED
ORIGINAL_BOARD=previous.ReadinessBoard


def image():
    import mechanical_bidirectional_fit as paired
    data=previous.previous.previous.validate_image(IMAGE,ELF,SHA,ELF_SHA,SIZE,
        extra_flags=('FOC_OUTER_OBSERVE_AFTER_ACK=1','FOC_READY_TIMESTAMP_SNAPSHOT=1',
                     'FOC_MECHANICAL_REVERSE_IDENT_DIAG=1'),
        extra_markers=(b'OBS_AFTER_ACK=1',b'OK MECH READY FIX=1 VALID=%lu FAIL=0x%08lX',
                       b'REVERSE_IDENT=1 SIGN=-1 GRID_RPM=600,700,800 DOB_CONTROL=0'))
    for key,size in (('outer_completion_trace',644),('cl_ready_check',20),
                     ('cl_ready_reject',32),('cl_ready_attempts',4)):
        if low.base.symbols(ELF).get(key,(0,0))[1]!=size:raise ValueError('Reverse ABI mismatch')
    paired.matching_profiles(previous.ELF,ELF)
    captures,_=paired.load_batch(POSITIVE_BATCH,previous.ELF,1)
    if len(captures)!=9:raise ValueError('Actual matching positive measurements required')
    return data


class ReverseBoard(ORIGINAL_BOARD):
    def command(self,command,timeout=2):
        if command.startswith('MOTOR TEST MECH RUN '):
            if command not in ('MOTOR TEST MECH RUN NEG 600','MOTOR TEST MECH RUN NEG 700','MOTOR TEST MECH RUN NEG 800'):
                raise ValueError('Exact negative-only whitelist required; no motion')
            reply=super().command('MOTOR TEST MECH DIRECTION',.8)
            values=low.base.hw.fields(reply);self.record['direction_before_start']=values
            if any(values.get(k)!=v for k,v in dict(REVERSE_IDENT='1',SIGN='-1',
                GRID_RPM='600,700,800',DOB_CONTROL='0').items()):
                raise RuntimeError('Reverse diagnostic identity absent; no motion')
        return super().command(command,timeout)


def run_point(row,*args):
    try:return ORIGINAL_RUN(row,*args)
    finally:
        if row.get('ram_capture'):
            row['outer_completion_trace']=previous.previous.decode_trace(row,elf=ELF,elf_sha=ELF_SHA)
            row['readiness_capture']=previous.decode_readiness(row,elf=ELF,elf_sha=ELF_SHA)


def staged(path,data):
    source,raw=ORIGINAL_STAGED(path,data);r=json.loads(path.read_text())
    if (r.get('speeds_rpm')!=list(POINTS) or r.get('ka_a_per_rpm_s')!=low.KA or
        r.get('overspeed_trip_rpm')!=1000 or r.get('travel_limit_deg')!=30000 or
        r.get('activation') is not False or r.get('motor_commands')!=0 or
        r.get('final_outputs_off') is not True or r.get('final_cpu_halted') is not True):
        raise ValueError('Exact reverse nine-point OFF readiness receipt required')
    return source,raw


def setup(path):
    ORIGINAL_SETUP(ROOT_RESTORE);low.base.baseline()
    low.IMAGE,low.ELF,low.SHA,low.ELF_SHA,low.SIZE=IMAGE,ELF,SHA,ELF_SHA,SIZE
    low.image=image;low.run_point=run_point;low.MechanicalBoard=ReverseBoard;low.base.staged=staged
    for obj in (low.base,low.previous.gain,low.fitted):
        obj.IMAGE,obj.ELF,obj.SHA,obj.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA;obj.image=image
    low.previous.gain.SIZE=SIZE;low.fitted.SIZE=SIZE
    if path.resolve()!=ROOT_RESTORE.resolve():low.base.configure_baseline(path)
    return image()


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if '--execute-nine' in args:args[args.index('--execute-nine')]='--execute-six'
    if '--baseline-restore' not in args and not any(x in args for x in ('--execute-six','--restore-b-drive-off')):
        args+=['--baseline-restore',str(ROOT_RESTORE)]
    low.setup=setup;low.POINTS=POINTS;low.TRIP_RPM=1000;low.TRAVEL_DEG=30000
    low.CLOSURE_SECONDS=11.;low.LIMITS_QUERY=True
    low.LIMITS_EXTRA=dict(PLAUSIBLE_RPM='1000',REJECT_BUSY='1',OBS_AFTER_ACK='1')
    return low.main(args)


if __name__=='__main__':raise SystemExit(main())
