"""Three supervised +600rpm steady Id/Iq captures. FILES ONLY by default.

No protection/PI/angle/Id-gate changes and no DOB feedback. Fresh OFF stage
and fresh whole-batch ON/no-alarm confirmation; independent faults stop all.
"""
import json
from pathlib import Path
import sys
import time
import mechanical_dob_board as previous
import mechanical_encoder_fix_board as validator
import readiness_snapshot_batch as readiness
import outer_completion_board as outer
import id_steady_report as report

low=previous.low
ROOT_RESTORE=low.TMP/'mechanical-ident-restore-1792715560592626800.json'
IMAGE=low.base.old.ROOT/'foc2_app_a/build/MechanicalIdSteadyCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='f76db9f86b4d3719f8d85349338b1ae8a3e3f0141aa0799700bda1638257b2b6'
ELF_SHA='d5e8d1db65236ceb08932f87803c421491fda18a99a5851e3e581d961b14b6df'
SIZE=215620
POINTS=(600,600,600)
ORIGINAL_SETUP=previous.setup
ORIGINAL_RUN=previous.ORIGINAL_RUN
ORIGINAL_STAGED=previous.ORIGINAL_STAGED
CONFIG=dict(V='1',TARGET_RPM='600',CONFIRM_US='500000',WINDOW_US='1000000',
            THRESH_UA='50000',TOL_RPM='12',ACCEL_TOL_RPM_S='1',FEEDBACK='0')


def image():
    data=validator.validate_image(IMAGE,ELF,SHA,ELF_SHA,SIZE,
        extra_flags=('FOC_OUTER_OBSERVE_AFTER_ACK=1','FOC_READY_TIMESTAMP_SNAPSHOT=1',
                     'FOC_MECHANICAL_DOB_SHADOW=1','FOC_ID_STEADY_STATS=1'),
        extra_markers=(b'OBS_AFTER_ACK=1',b'OK MECH READY FIX=1 VALID=%lu FAIL=0x%08lX',
                       b'DOB_SHADOW=1 SIGNS=POS,NEG GRID_RPM=600 DOB_CONTROL=0',
                       b'OK IDSTATS V=1 TARGET_RPM=600 CONFIRM_US=500000 WINDOW_US=1000000 THRESH_UA=50000'))
    sizes=dict(outer_completion_trace=644,cl_ready_check=20,cl_ready_reject=32,
               cl_ready_attempts=4,mechanical_dob_monitor=856,mechanical_dob_identified_model=28,
               id_steady_stats=report.SIZE)
    symbols=low.base.symbols(ELF)
    if any(symbols.get(k,(0,0))[1]!=size for k,size in sizes.items()):raise ValueError('Id stats ABI mismatch')
    return data


class IdStatsBoard(previous.DobBoard):
    def command(self,command,timeout=2):
        if command.startswith('MOTOR TEST MECH RUN '):
            if command!='MOTOR TEST MECH RUN POS 600':raise ValueError('Fixed +600rpm only')
            cfg=super().command('MOTOR TEST MECH IDSTATS CFG',.8)
            self.record['idstats_config']=previous.check_values(cfg,CONFIG,'Id stats')
            initial=super().command('MOTOR TEST MECH IDSTATS',.8)
            self.record['idstats_initial']=previous.check_values(initial,
                dict(V='1',STATE='0',N='0',GOOD_US='0',BAD_US='0',FEEDBACK='0'),'Id stats unused')
        reply=super().command(command,timeout)
        if command=='MOTOR TEST MECH STATUS' and getattr(self,'dob_started',False) and time.monotonic()>=getattr(self,'idstats_next',0.):
            status=super().command('MOTOR TEST MECH IDSTATS',.8)
            self.record.setdefault('idstats_samples',[]).append(dict(at=time.monotonic(),reply=status,
                values=previous.check_values(status,dict(V='1',FEEDBACK='0'),'Id stats readonly')))
            self.idstats_next=time.monotonic()+.25
        return reply


def run_point(row,*args):
    try:
        ORIGINAL_RUN(row,*args)
        row['id_steady_capture']=report.decode(Path(row['receipt_path']),ELF)
        row['dob_capture']=row['id_steady_capture']['dob_capture']
        row['id_steady_quality']=dict(window_complete=row['id_steady_capture']['fixed_window_complete'],
            steady_throughout=row['id_steady_capture']['steady_throughout'],
            current_data_coverage=row['id_steady_capture']['current_data_coverage'],
            threshold_changed=False,feedback_enabled=False)
        # Quality is reported even if poor. It never causes retries, hidden
        # sample selection or rewriting the model; original safety gates remain.
    finally:
        if row.get('ram_capture'):
            row['outer_completion_trace']=outer.decode_trace(row,elf=ELF,elf_sha=ELF_SHA)
            row['readiness_capture']=readiness.decode_readiness(row,elf=ELF,elf_sha=ELF_SHA)


def staged(path,data):
    source,raw=ORIGINAL_STAGED(path,data);r=json.loads(path.read_text())
    if (r.get('speeds_rpm')!=list(POINTS) or r.get('ka_a_per_rpm_s')!=low.KA or
        r.get('overspeed_trip_rpm')!=1000 or r.get('travel_limit_deg')!=30000 or
        r.get('activation') is not False or r.get('motor_commands')!=0 or
        r.get('final_outputs_off') is not True or r.get('final_cpu_halted') is not True):
        raise ValueError('Exact Id statistics three-point OFF plan required')
    return source,raw


def setup(path):
    ORIGINAL_SETUP(ROOT_RESTORE);low.base.baseline() # Prove actual old DOB/B1043 restore first.
    low.IMAGE,low.ELF,low.SHA,low.ELF_SHA,low.SIZE=IMAGE,ELF,SHA,ELF_SHA,SIZE
    low.image,low.run_point,low.MechanicalBoard=image,run_point,IdStatsBoard
    low.base.staged=staged
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
    low.setup,low.POINTS=setup,POINTS
    low.TRIP_RPM,low.TRAVEL_DEG,low.CLOSURE_SECONDS,low.LIMITS_QUERY=1000,30000,11.,True
    low.LIMITS_EXTRA=dict(PLAUSIBLE_RPM='1000',REJECT_BUSY='1',OBS_AFTER_ACK='1')
    return low.main(args)


if __name__=='__main__':raise SystemExit(main())
