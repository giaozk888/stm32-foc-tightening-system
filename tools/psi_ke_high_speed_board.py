"""Explicit supervised 300/400 rpm PSI batch, A only, 500 rpm trip.

Default is FILES ONLY. Reuse the existing shutdown/protection/restore owners;
never relax health gates, retry a protected run, apply flux, or touch B code.
"""
import hashlib
import json
from pathlib import Path
import sys
import psi_ke_board as low

ROOT_RESTORE=low.TMP/'psi-ke-restore-1792588592105201500.json'
IMAGE=low.base.old.ROOT/'foc2_app_a/build/PsiKeHighSpeedDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
# Exact independently reviewed offline build; never recomputed to bypass checks.
SHA='ae86125e772e65599fcdbf424bd449f38f649c6aff472f5c17a1c136b1a8e53d'
ELF_SHA='b1773b0eba83a04c49e20f61ae5f0723afa11f896a11c221ee1a9cc4056b6bc4'
SIZE=215860
LOW_CONFIGURE=low.configure


def image():
    data=IMAGE.read_bytes()
    command=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text())
        if c['file'].endswith('/Core/Src/main.c'))
    required=('FOC_PSI_IDENT_DIAG=1','FOC_PSI_IDENT_TRIP500=1','FOC_PSI_IDENT_API400=1',
        'FOC_BEMF_CANDIDATE=1','FOC_BEMF_ENABLED_DEFAULT=0','FOC_BEMF_PSI_WB=0.0f',
        'FOC_CURRENT_PI_IDENTIFIED_ENABLE=1','FOC_ONE_CYCLE_PWM_PIPELINE=1',
        'FOC_PWM_PIPELINE_CLOSED_LOOP=1','AS5047P_DMA_FOC_FIRST=1',
        'FOC_SPEED_PI_ANTI_WINDUP=1','FOC_FRICTION_ENABLED_DEFAULT=1')
    if (len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or
        hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA or
        low.base.hw.image_info(data)[0]!='A' or
        any('-D'+flag+' ' not in command for flag in required) or
        any('-D'+flag in command for flag in ('FOC_DQ_DECOUPLING_CANDIDATE',
            'DECOUPLING_SIGN_TEST','FOC_FAST_REJECT_COMPUTE_ONLY')) or
        low.base.symbols(ELF).get('psi_ident',(0,0))[1]!=168 or
        b'RUNDOWN240: RAM=240rpm TRIP=500rpm SAVE=OFF' not in data or
        b'PSI_IDENT_DIAGNOSTIC: manual point; no normal START; BEMF unchanged OFF' not in data):
        raise ValueError('Exact offline-tested high-speed PSI image/ELF/flags required')
    low.base.support.support.require_baud(command)
    return data


def configure(path):
    # Validate the previous low-speed B936 restoration with its ORIGINAL image
    # verifier first. Do not reinterpret an old receipt as the new image.
    LOW_CONFIGURE(ROOT_RESTORE)
    low.base.baseline()
    low.IMAGE,low.ELF,low.SHA,low.ELF_SHA,low.SIZE=IMAGE,ELF,SHA,ELF_SHA,SIZE
    low.image=image
    low.base.IMAGE,low.base.ELF,low.base.SHA,low.base.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    low.base.image=image
    if path.resolve()!=ROOT_RESTORE.resolve():
        low.base.configure_baseline(path)
    return image()


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if '--baseline-restore' not in args and not any(x in args for x in ('--execute-batch','--restore-b-drive-off')):
        args+=['--baseline-restore',str(ROOT_RESTORE)]
    low.configure=configure
    low.API_LIMIT,low.TRIP_LIMIT,low.POINTS=400,500,(300,400)
    return low.main(args)


if __name__=='__main__':
    raise SystemExit(main())
