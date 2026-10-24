"""Single supervised +600rpm DOB admission observation. Files-only by default.

Exact V2 image identity and fresh OFF/ON gates; no retries or DOB feedback.
"""
import json
from pathlib import Path
import struct
import sys
import dob_id_trace_board as previous
import mechanical_dob_board as shadow
import mechanical_encoder_fix_board as validator
import readiness_snapshot_batch as readiness
import outer_completion_board as outer
import dob_id_trace_report as report

low=previous.low
ROOT_RESTORE=low.TMP/'mechanical-ident-restore-1792721158187369200.json'
IMAGE=low.base.old.ROOT/'foc2_app_a/build/MechanicalDobSpikeAdmissionCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='e502d52c4c4d402f8a17a530aec9aa7925e11c1cf516d600da3cf7ff4dc862c0'
ELF_SHA='4dfbc0c01f575f8856740ff8714c2560af49337b0c9d50078bca2d0094341eeb'
SIZE=214936
POINTS=(600,)
ORIGINAL_SETUP=previous.setup
ORIGINAL_RUN=previous.ORIGINAL_RUN
ORIGINAL_STAGED=previous.ORIGINAL_STAGED
ORIGINAL_EXECUTE=previous.ORIGINAL_EXECUTE
CONFIG=dict(V='1',SHADOW='1',JUMP_UA='250000',RETURN_UA='150000',CONFIRM_UA='50000',
            GAP_US='2500',CONSEC='2',WINDOW='32',MAX_HOLD='4',FEEDBACK='0')
ADMIT_KEYS=('reference_id reference_iq candidate_id candidate_iq seeded pending pending_us '
            'blocked decision samples passed suspects isolated transitions unresolved held '
            'consecutive_holds window_samples window_holds budget_exits last_accepted_us '
            'accepted_gap_us exit_reason').split()


def image():
    data=validator.validate_image(IMAGE,ELF,SHA,ELF_SHA,SIZE,
        extra_flags=('FOC_OUTER_OBSERVE_AFTER_ACK=1','FOC_READY_TIMESTAMP_SNAPSHOT=1',
            'FOC_MECHANICAL_DOB_SHADOW=1','FOC_DOB_ID_TRACE=1','FOC_DOB_SPIKE_ADMISSION=1'),
        extra_markers=(b'OBS_AFTER_ACK=1',b'OK MECH READY FIX=1 VALID=%lu FAIL=0x%08lX',
            b'DOB_SHADOW=1 SIGNS=POS,NEG GRID_RPM=600 DOB_CONTROL=0',
            b'OK IDTRACE V=2 PRE=32 DENSE=32 TAIL=128 TAIL_US=4000',
            b'OK ADMIT V=1 SHADOW=1 JUMP_UA=',b'OK ADMIT STATS V=1'))
    syms=low.base.symbols(ELF)
    for name,n in dict(outer_completion_trace=644,cl_ready_check=20,cl_ready_reject=32,
        cl_ready_attempts=4,mechanical_dob_monitor=856,mechanical_dob_identified_model=28,
        mechanical_capture=4712,dob_id_trace=96,dob_current_admission=92).items():
        if syms.get(name,(0,0))[1]!=n:raise ValueError('Admission ABI '+name)
    if 'id_steady_stats' in syms:raise ValueError('Exclusive V2 recorder required')
    return data


def decode_admission(data):
    if len(data)!=92:raise ValueError('Admission state ABI')
    import math
    m=dict(zip(ADMIT_KEYS,struct.unpack('<4f19I',data)))
    if (not all(math.isfinite(m[k]) for k in ADMIT_KEYS[:4]) or
        any(m[k] not in (0,1) for k in ('seeded','pending','blocked')) or
        m['decision']>8 or m['exit_reason']>4 or m['budget_exits']>1 or
        bool(m['blocked'])!=bool(m['budget_exits']) or
        m['passed']+m['held']>m['samples'] or m['window_samples']>32 or
        m['isolated']+m['transitions']>m['suspects']):raise ValueError('Admission state counters')
    return m


class AdmissionBoard(shadow.DobBoard):
    def command(self,command,timeout=2):
        if command.startswith('MOTOR TEST MECH RUN '):
            if command!='MOTOR TEST MECH RUN POS 600':raise ValueError('Single +600rpm admission test only')
            self.record['admission_config']=shadow.check_values(
                super().command('MOTOR TEST MECH DOB ADMIT CFG',.8),CONFIG,'Admission config')
            self.record['admission_unused']=shadow.check_values(
                super().command('MOTOR TEST MECH DOB ADMIT',.8),
                dict(V='1',DEC='0',BLOCK='0',WHY='0',N='0',HOLD='0',EXIT='0',FEEDBACK='0'),
                'Unused admission')
            self.record['idtrace_initial']=shadow.check_values(
                super().command('MOTOR TEST MECH IDTRACE',.8),
                dict(V='2',PRE='32',DENSE='32',TAIL='128',TAIL_US='4000',STATE='0',POST='0',NT='0',RESET='0',FEEDBACK='0'),
                'Unused V2 trace')
        return super().command(command,timeout)


def run_point(row,*args):
    try:
        ORIGINAL_RUN(row,*args)
        row['idtrace_capture']=report.decode(Path(row['receipt_path']),ELF)
        if row['idtrace_capture']['meta']['abi']!=2:raise ValueError('V2 trace required')
        row['dob_capture']=row['idtrace_capture']['dob_capture']
        ram=Path(row['ram_capture']).read_bytes();address,n=low.base.symbols(ELF)['dob_current_admission']
        offset=address-0x20000000
        if n!=92 or not 0<=offset<=len(ram)-n:raise ValueError('Admission RAM bounds')
        row['admission_capture']=decode_admission(ram[offset:offset+n])
        row['admission_quality']=dict(blocked=bool(row['admission_capture']['blocked']),
            trace_complete=row['idtrace_capture']['complete'],feedback_enabled=False,
            automatic_retry=False,physical_current_quality_proven=False)
        # Poor observation quality is retained as a result, not auto-retried.
    finally:
        if row.get('ram_capture'):
            row['outer_completion_trace']=outer.decode_trace(row,elf=ELF,elf_sha=ELF_SHA)
            row['readiness_capture']=readiness.decode_readiness(row,elf=ELF,elf_sha=ELF_SHA)


def execute(path,parent):
    ORIGINAL_EXECUTE(path,parent)
    parent['identification']=None
    parent['note']='DOB admission observation only; no mechanical fit, feedback or retries.'


def staged(path,data):
    source,raw=ORIGINAL_STAGED(path,data);r=json.loads(path.read_text())
    if (r.get('speeds_rpm')!=list(POINTS) or r.get('ka_a_per_rpm_s')!=low.KA or
        r.get('overspeed_trip_rpm')!=1000 or r.get('travel_limit_deg')!=30000 or
        r.get('activation') is not False or r.get('motor_commands')!=0 or
        r.get('final_outputs_off') is not True or r.get('final_cpu_halted') is not True):
        raise ValueError('Exact admission single-point OFF plan required')
    return source,raw


def setup(path):
    ORIGINAL_SETUP(ROOT_RESTORE);low.base.baseline() # Prove actual V1/B1051 restoration first.
    low.IMAGE,low.ELF,low.SHA,low.ELF_SHA,low.SIZE=IMAGE,ELF,SHA,ELF_SHA,SIZE
    low.image,low.run_point,low.MechanicalBoard=image,run_point,AdmissionBoard
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
