"""One supervised 600rpm encoder-fix A retest. FILES ONLY by default."""
import hashlib
import json
from pathlib import Path
import sys
import mechanical_high_speed_board as previous

low=previous.low
ROOT_RESTORE=low.TMP/'mechanical-ident-restore-1792671261759797500.json'
IMAGE=low.base.old.ROOT/'foc2_app_a/build/MechanicalHighSpeedEncoderFixCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='212ebe9c5c3a8b09a29ed3279ac9c78c100ef80276dfc75de0439c982a7eb862'
ELF_SHA='dadb41e4dc5460c70bfce483b777abf7e0d85a4876ee97b059d816d247aac0e3'
SIZE=208524
ORIGINAL_SETUP=previous.setup


def image():
    return validate_image(IMAGE,ELF,SHA,ELF_SHA,SIZE)


def validate_image(image_path,elf_path,sha,elf_sha,size,extra_flags=(),extra_markers=()):
    data=image_path.read_bytes()
    cmd=next(c['command'] for c in json.loads((image_path.parent/'compile_commands.json').read_text())
             if c['file'].endswith('/Core/Src/main.c'))
    required=('FOC_ENCODER_CONTROL_ADMISSION_FIX=1','FOC_MECHANICAL_HIGH_SPEED_DIAG=1',
        'FOC_MECHANICAL_IDENT_DIAG=1','FOC_MECHANICAL_MOTION_DIAG=1',
        'FOC_FRICTION_CALIBRATION_DIAG=1','FOC_BEMF_CANDIDATE=1','FOC_BEMF_ENABLED_DEFAULT=1',
        'FOC_BEMF_PSI_WB=0.00034866f','SPEED_ACCEL_FF_KA_A_PER_RPM_S=0.000046875f',
        'SPEED_FRICTION_I_A=0.105f','FOC_FRICTION_ENABLED_DEFAULT=1',
        'FOC_CURRENT_PI_IDENTIFIED_ENABLE=1','FOC_PROTECTED_CLOSED_LOOP=1',
        'FOC_SPEED_PI_ANTI_WINDUP=1','FOC_ONE_CYCLE_PWM_PIPELINE=1',
        'FOC_PWM_PIPELINE_CLOSED_LOOP=1','AS5047P_DMA_FOC_FIRST=1')+tuple(extra_flags)
    forbidden=('FOC_PSI_IDENT','FOC_DQ_DECOUPLING_CANDIDATE','FOC_CURRENT_STEP_AB_DIAG',
        'FOC_FAST_REJECT_COMPUTE_ONLY','FOC_KA_SYNC_DIAG','FOC_KA_FULL_DIAG','FOC_ACCEL_FF_AUDIT')
    if (len(data)!=size or hashlib.sha256(data).hexdigest()!=sha or
        hashlib.sha256(elf_path.read_bytes()).hexdigest()!=elf_sha or low.base.hw.image_info(data)[0]!='A' or
        any('-D'+flag+' ' not in cmd for flag in required) or any('-D'+flag in cmd for flag in forbidden) or
        low.base.symbols(elf_path).get('mechanical_capture',(0,0))[1]!=low.analysis.SIZE):
        raise ValueError('Exact reviewed encoder-fix A image/flags required')
    for marker in (b'MECH_IDENT_DIAGNOSTIC: manual signed point; fixed compensation; no START',
        b'RUNDOWN240: RAM=240rpm TRIP=1000rpm SAVE=OFF',b'TRAVEL=30000deg RAM only',
        b'TRIP_MA=4000',b'METHOD=TWO_SAMPLE',b'PLAUSIBLE_RPM=%u REJECT_BUSY=1')+tuple(extra_markers):
        if marker not in data:raise ValueError('Encoder fix/manual/protection marker absent')
    low.base.support.support.require_baud(cmd)
    return data


def setup(path):
    # Prove the actual previous HIGH-SPEED A restoration with its old image
    # first. Install the new identity only AFTER full saved Flash verification.
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
    if '--execute-once' in args:args[args.index('--execute-once')]='--execute-six'
    if '--baseline-restore' not in args and not any(x in args for x in ('--execute-six','--restore-b-drive-off')):
        args+=['--baseline-restore',str(ROOT_RESTORE)]
    low.setup=setup
    low.POINTS=(600,);low.TRIP_RPM=1000;low.TRAVEL_DEG=30000
    low.CLOSURE_SECONDS=11.;low.LIMITS_QUERY=True
    low.LIMITS_EXTRA=dict(PLAUSIBLE_RPM='1000',REJECT_BUSY='1')
    return low.main(args)


if __name__=='__main__':raise SystemExit(main())
