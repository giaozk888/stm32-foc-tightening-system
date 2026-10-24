"""Supervised 500/600/700/800 rpm x3. Files-only default; A only, no DOB."""
import hashlib
import json
from pathlib import Path
import sys
import mechanical_identification_board as low

ROOT_RESTORE=low.TMP/'mechanical-ident-restore-1792670081409480900.json'
IMAGE=low.base.old.ROOT/'foc2_app_a/build/MechanicalIdentificationHighSpeedCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
# Filled only after the reviewed offline build, never derived to waive identity.
SHA='442cef6ca8476b15e99e373b01394f881672e89fb5a2ff5a176323e0e3fcec1e'
ELF_SHA='22cf6efdeb090b2358c2f6d29942b68cd10601c87455160ead4dbbc1eef65490'
SIZE=208436
POINTS=(500,500,500,600,600,600,700,700,700,800,800,800)
ORIGINAL_SETUP=low.setup


def image():
    data=IMAGE.read_bytes()
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text())
             if c['file'].endswith('/Core/Src/main.c'))
    required=('FOC_MECHANICAL_HIGH_SPEED_DIAG=1','FOC_MECHANICAL_IDENT_DIAG=1',
        'FOC_MECHANICAL_MOTION_DIAG=1','FOC_FRICTION_CALIBRATION_DIAG=1',
        'FOC_BEMF_CANDIDATE=1','FOC_BEMF_ENABLED_DEFAULT=1','FOC_BEMF_PSI_WB=0.00034866f',
        'SPEED_ACCEL_FF_KA_A_PER_RPM_S=0.000046875f','SPEED_FRICTION_I_A=0.105f',
        'FOC_FRICTION_ENABLED_DEFAULT=1','FOC_CURRENT_PI_IDENTIFIED_ENABLE=1',
        'FOC_PROTECTED_CLOSED_LOOP=1','FOC_SPEED_PI_ANTI_WINDUP=1',
        'FOC_ONE_CYCLE_PWM_PIPELINE=1','FOC_PWM_PIPELINE_CLOSED_LOOP=1','AS5047P_DMA_FOC_FIRST=1')
    forbidden=('FOC_PSI_IDENT','FOC_DQ_DECOUPLING_CANDIDATE','FOC_CURRENT_STEP_AB_DIAG',
        'FOC_FAST_REJECT_COMPUTE_ONLY','FOC_KA_SYNC_DIAG','FOC_KA_FULL_DIAG','FOC_ACCEL_FF_AUDIT')
    if (len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or
        hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA or low.base.hw.image_info(data)[0]!='A' or
        any('-D'+flag+' ' not in cmd for flag in required) or any('-D'+flag in cmd for flag in forbidden) or
        low.base.symbols(ELF).get('mechanical_capture',(0,0))[1]!=low.analysis.SIZE):
        raise ValueError('Exact reviewed high-speed mechanical A image required')
    for marker in (b'MECH_IDENT_DIAGNOSTIC: manual signed point; fixed compensation; no START',
        b'RUNDOWN240: RAM=240rpm TRIP=1000rpm SAVE=OFF',b'TRAVEL=30000deg RAM only',
        b'TRIP_MA=4000',b'METHOD=TWO_SAMPLE',b'STOP_MS=%u LEASE_US=%u'):
        if marker not in data:raise ValueError('Manual/protection/closure marker absent')
    low.base.support.support.require_baud(cmd)
    return data


def setup(path):
    # Prove the ACTUAL prior mechanical restore with its original image first.
    # Never reinterpret the old receipt under new hashes or skip full Flash.
    ORIGINAL_SETUP(ROOT_RESTORE)
    low.base.baseline()
    low.IMAGE,low.ELF,low.SHA,low.ELF_SHA,low.SIZE=IMAGE,ELF,SHA,ELF_SHA,SIZE
    low.image=image
    for obj in (low.base,low.previous.gain,low.fitted):
        obj.IMAGE,obj.ELF,obj.SHA,obj.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
        obj.image=image
    low.previous.gain.SIZE=SIZE;low.fitted.SIZE=SIZE
    if path.resolve()!=ROOT_RESTORE.resolve():low.base.configure_baseline(path)
    return image()


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    # Explicit high-speed spelling; do not change the historical six-point CLI.
    if '--execute-twelve' in args:args[args.index('--execute-twelve')]='--execute-six'
    if '--baseline-restore' not in args and not any(x in args for x in ('--execute-six','--restore-b-drive-off')):
        args+=['--baseline-restore',str(ROOT_RESTORE)]
    low.setup=setup
    low.POINTS=POINTS;low.TRIP_RPM=1000;low.TRAVEL_DEG=30000
    low.CLOSURE_SECONDS=11.;low.LIMITS_QUERY=True
    return low.main(args)


if __name__=='__main__':raise SystemExit(main())
