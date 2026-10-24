"""One supervised +600 rpm same-epoch Id/reset trace. Files-only by default."""
import json
from pathlib import Path
import sys
import id_steady_board as previous
import mechanical_dob_board as shadow
import mechanical_encoder_fix_board as validator
import readiness_snapshot_batch as readiness
import outer_completion_board as outer
import dob_id_trace_report as report
low=previous.low
ROOT_RESTORE=low.TMP/'mechanical-ident-restore-1792718646428222500.json'
IMAGE=low.base.old.ROOT/'foc2_app_a/build/MechanicalDobIdTraceCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='6a56188d07032d3930be07a8172bb6fc0cb24dd5cb8424acbc5af266e4c4c0b1'
ELF_SHA='e73e53acb9037dcbe1168b11919b32d751870f56c3e36f3facab3f8037581722'
SIZE=213688
POINTS=(600,)
ORIGINAL_SETUP=previous.setup
ORIGINAL_RUN=previous.ORIGINAL_RUN
ORIGINAL_STAGED=previous.ORIGINAL_STAGED
ORIGINAL_EXECUTE=low.execute


def image():
    data=validator.validate_image(IMAGE,ELF,SHA,ELF_SHA,SIZE,
        extra_flags=('FOC_OUTER_OBSERVE_AFTER_ACK=1','FOC_READY_TIMESTAMP_SNAPSHOT=1',
                     'FOC_MECHANICAL_DOB_SHADOW=1','FOC_DOB_ID_TRACE=1'),
        extra_markers=(b'OBS_AFTER_ACK=1',b'OK MECH READY FIX=1 VALID=%lu FAIL=0x%08lX',
                       b'DOB_SHADOW=1 SIGNS=POS,NEG GRID_RPM=600 DOB_CONTROL=0',
                       b'OK IDTRACE V=1 PRE=64 DENSE=64 TAIL=160 TAIL_US=4000'))
    syms=low.base.symbols(ELF)
    for k,n in dict(outer_completion_trace=644,cl_ready_check=20,cl_ready_reject=32,
                   cl_ready_attempts=4,mechanical_dob_monitor=856,
                   mechanical_dob_identified_model=28,mechanical_capture=4712,dob_id_trace=96).items():
        if syms.get(k,(0,0))[1]!=n:raise ValueError('Trace ABI '+k)
    if 'id_steady_stats' in syms:raise ValueError('Mutually exclusive recorder')
    return data


class TraceBoard(shadow.DobBoard):
    def command(self,command,timeout=2):
        if command.startswith('MOTOR TEST MECH RUN '):
            if command!='MOTOR TEST MECH RUN POS 600':raise ValueError('One +600 rpm trace only')
            self.record['idtrace_initial']=shadow.check_values(
                super().command('MOTOR TEST MECH IDTRACE',.8),
                dict(V='1',PRE='64',DENSE='64',TAIL='160',TAIL_US='4000',STATE='0',POST='0',NT='0',RESET='0',FEEDBACK='0'),
                'Unused Id trace')
        return super().command(command,timeout)


def run_point(row,*args):
    try:
        ORIGINAL_RUN(row,*args)
        row['idtrace_capture']=report.decode(Path(row['receipt_path']),ELF)
        row['dob_capture']=row['idtrace_capture']['dob_capture']
    finally:
        if row.get('ram_capture'):
            row['outer_completion_trace']=outer.decode_trace(row,elf=ELF,elf_sha=ELF_SHA)
            row['readiness_capture']=readiness.decode_readiness(row,elf=ELF,elf_sha=ELF_SHA)


def execute(path,parent):
    ORIGINAL_EXECUTE(path,parent)
    parent['identification']=None
    parent['note']='Exclusive Id trace buffer; no mechanical parameter fit or DOB feedback.'


def staged(path,data):
    source,raw=ORIGINAL_STAGED(path,data);r=json.loads(path.read_text())
    if (r.get('speeds_rpm')!=list(POINTS) or r.get('ka_a_per_rpm_s')!=low.KA or
        r.get('overspeed_trip_rpm')!=1000 or r.get('travel_limit_deg')!=30000 or
        r.get('activation') is not False or r.get('motor_commands')!=0 or
        r.get('final_outputs_off') is not True or r.get('final_cpu_halted') is not True):
        raise ValueError('Exact single-point trace OFF plan required')
    return source,raw


def setup(path):
    ORIGINAL_SETUP(ROOT_RESTORE);low.base.baseline()
    low.IMAGE,low.ELF,low.SHA,low.ELF_SHA,low.SIZE=IMAGE,ELF,SHA,ELF_SHA,SIZE
    low.image,low.run_point,low.MechanicalBoard=image,run_point,TraceBoard
    low.base.staged=staged
    for obj in (low.base,low.previous.gain,low.fitted):
        obj.IMAGE,obj.ELF,obj.SHA,obj.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA;obj.image=image
    low.previous.gain.SIZE=low.fitted.SIZE=SIZE
    if path.resolve()!=ROOT_RESTORE.resolve():low.base.configure_baseline(path)
    return image()


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
