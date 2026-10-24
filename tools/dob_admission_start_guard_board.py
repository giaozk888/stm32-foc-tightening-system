"""One supervised V3 +600rpm start-guard observation. Files-only by default."""
import json
from pathlib import Path
import struct
import sys
import dob_current_admission_board as previous
import mechanical_dob_board as shadow
import mechanical_encoder_fix_board as validator
import readiness_snapshot_batch as readiness
import outer_completion_board as outer
import dob_id_trace_report as report

low=previous.low
ROOT_RESTORE=low.TMP/'mechanical-ident-restore-1792723101035766500.json'
IMAGE=low.base.old.ROOT/'foc2_app_a/build/MechanicalDobAdmissionStartGuardCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='d8412b5629ff208f0549546cc526ef7e8e82a139c57c0fc2aaa67a5a4eaf7f98'
ELF_SHA='90439538958a1c4d1e707abe25a3ef5ae0789a1ed4a0a01c376a9ae3d03578e1'
SIZE=215508
POINTS=(600,)
ORIGINAL_SETUP=previous.setup
ORIGINAL_RUN=previous.ORIGINAL_RUN
ORIGINAL_STAGED=previous.ORIGINAL_STAGED
ORIGINAL_EXECUTE=previous.ORIGINAL_EXECUTE
CONFIG=previous.CONFIG
ARM_CONFIG=dict(V='1',CONFIRM_US='50000',MIN_W_MRAD_S='2094',ARMED='0',QUAL_US='0',
                PRE_N='0',ARM_US='0',FEEDBACK='0')
KEYS=previous.ADMIT_KEYS+['armed','qualify_us','prearm_samples','arm_us','qualify_sign']


def image():
    data=validator.validate_image(IMAGE,ELF,SHA,ELF_SHA,SIZE,
        extra_flags=('FOC_OUTER_OBSERVE_AFTER_ACK=1','FOC_READY_TIMESTAMP_SNAPSHOT=1',
            'FOC_MECHANICAL_DOB_SHADOW=1','FOC_DOB_ID_TRACE=1','FOC_DOB_SPIKE_ADMISSION=1',
            'FOC_DOB_ADMISSION_START_GUARD=1'),
        extra_markers=(b'OBS_AFTER_ACK=1',b'OK MECH READY FIX=1 VALID=%lu FAIL=0x%08lX',
            b'DOB_SHADOW=1 SIGNS=POS,NEG GRID_RPM=600 DOB_CONTROL=0',
            b'OK IDTRACE V=3 PRE=16 DENSE=32 TAIL=48 TAIL_US=4000',
            b'OK ADMIT ARM V=1 CONFIRM_US=50000 MIN_W_MRAD_S='))
    syms=low.base.symbols(ELF)
    for name,n in dict(outer_completion_trace=644,cl_ready_check=20,cl_ready_reject=32,
        cl_ready_attempts=4,mechanical_dob_monitor=856,mechanical_dob_identified_model=28,
        mechanical_capture=4712,dob_id_trace=96,dob_current_admission=112).items():
        if syms.get(name,(0,0))[1]!=n:raise ValueError('V3 ABI '+name)
    if 'id_steady_stats' in syms:raise ValueError('Exclusive V3 trace required')
    return data


def decode_admission(data):
    if len(data)!=112:raise ValueError('Guarded admission ABI')
    import math
    m=dict(zip(KEYS,struct.unpack('<4f23Ii',data)))
    if (not all(math.isfinite(m[k]) for k in KEYS[:4]) or
        any(m[k] not in (0,1) for k in ('seeded','pending','blocked','armed')) or
        m['decision']>9 or m['exit_reason']>4 or m['budget_exits']>1 or
        bool(m['blocked'])!=bool(m['budget_exits']) or
        m['passed']+m['held']>m['samples'] or m['window_samples']>32 or
        m['isolated']+m['transitions']>m['suspects'] or
        m['qualify_us']>52000 or m['qualify_sign'] not in (-1,0,1) or
        (m['armed'] and m['qualify_us']<50000) or
        (not m['armed'] and (m['samples'] or m['blocked']))):raise ValueError('Guarded admission counters')
    return m


class StartGuardBoard(shadow.DobBoard):
    def command(self,command,timeout=2):
        if command.startswith('MOTOR TEST MECH RUN '):
            if command!='MOTOR TEST MECH RUN POS 600':raise ValueError('Single +600rpm V3 test only')
            self.record['admission_config']=shadow.check_values(
                super().command('MOTOR TEST MECH DOB ADMIT CFG',.8),CONFIG,'Admission config')
            self.record['admission_unused']=shadow.check_values(
                super().command('MOTOR TEST MECH DOB ADMIT',.8),
                dict(V='1',DEC='0',BLOCK='0',WHY='0',N='0',HOLD='0',EXIT='0',FEEDBACK='0'),'Unused admission')
            self.record['admission_arm_config']=shadow.check_values(
                super().command('MOTOR TEST MECH DOB ADMIT ARM',.8),ARM_CONFIG,'Unused start guard')
            self.record['idtrace_initial']=shadow.check_values(
                super().command('MOTOR TEST MECH IDTRACE',.8),
                dict(V='3',PRE='16',DENSE='32',TAIL='48',TAIL_US='4000',STATE='0',POST='0',NT='0',RESET='0',FEEDBACK='0'),
                'Unused V3 trace')
        return super().command(command,timeout)


def run_point(row,*args):
    try:
        ORIGINAL_RUN(row,*args)
        row['idtrace_capture']=report.decode(Path(row['receipt_path']),ELF)
        if row['idtrace_capture']['meta']['abi']!=3:raise ValueError('V3 trace required')
        row['dob_capture']=row['idtrace_capture']['dob_capture']
        ram=Path(row['ram_capture']).read_bytes();address,n=low.base.symbols(ELF)['dob_current_admission']
        offset=address-0x20000000
        if n!=112 or not 0<=offset<=len(ram)-n:raise ValueError('V3 admission RAM bounds')
        row['admission_capture']=decode_admission(ram[offset:offset+n])
        row['admission_quality']=dict(armed=bool(row['admission_capture']['armed']),
            blocked=bool(row['admission_capture']['blocked']),trace_complete=row['idtrace_capture']['complete'],
            feedback_enabled=False,automatic_retry=False,physical_current_quality_proven=False)
    finally:
        if row.get('ram_capture'):
            row['outer_completion_trace']=outer.decode_trace(row,elf=ELF,elf_sha=ELF_SHA)
            row['readiness_capture']=readiness.decode_readiness(row,elf=ELF,elf_sha=ELF_SHA)


def execute(path,parent):
    ORIGINAL_EXECUTE(path,parent)
    parent['identification']=None
    parent['note']='V3 one-way start qualification/first-event capture; no DOB feedback or retries.'


def staged(path,data):
    source,raw=ORIGINAL_STAGED(path,data);r=json.loads(path.read_text())
    if (r.get('speeds_rpm')!=list(POINTS) or r.get('ka_a_per_rpm_s')!=low.KA or
        r.get('overspeed_trip_rpm')!=1000 or r.get('travel_limit_deg')!=30000 or
        r.get('activation') is not False or r.get('motor_commands')!=0 or
        r.get('final_outputs_off') is not True or r.get('final_cpu_halted') is not True):
        raise ValueError('Exact V3 single-point OFF plan required')
    return source,raw


def setup(path):
    ORIGINAL_SETUP(ROOT_RESTORE);low.base.baseline() # Actual V2/B1055 proof first.
    low.IMAGE,low.ELF,low.SHA,low.ELF_SHA,low.SIZE=IMAGE,ELF,SHA,ELF_SHA,SIZE
    low.image,low.run_point,low.MechanicalBoard=image,run_point,StartGuardBoard
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
