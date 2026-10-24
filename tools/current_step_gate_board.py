"""Explicit gate-evidence A profile; same OFF-stage / ON-once / OFF-B-restore.

FILES ONLY by default. No implicit replacement of the original step runner's
pinned firmware. Restored baselines must prove either that exact old image or
this exact new image, plus the unchanged B/boot/private root and halted outputs.
"""
import json
from pathlib import Path
import current_step_ab_board as step
from foc_output_gate_evidence_report import decode as decode_gate, SIZE

base=step.base
IMAGE=base.old.ROOT/'foc2_app_a/build/CurrentStepAbGateEvidence/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='9cb14e996ca42fddb6608d90d8eb7d3ea3aef9b58b31b78431c285a5222a2fb1'
ELF_SHA='3374f1577a6da5240af3b72f890f610531ae57e24bcdd36693d0c6f0f7d73418'
RESTORE=step.TMP/'current-step-ab-restore-1792572379371008800.json'
LEGACY={k:getattr(step,k) for k in ('IMAGE','ELF','SHA','ELF_SHA','image','configure','decode_capture')}

def image():
    data=IMAGE.read_bytes()
    command=next(x['command'] for x in json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
                 if x['file'].endswith('/Core/Src/main.c'))
    base.support.support.require_baud(command)
    required=('FOC_OUTPUT_GATE_EVIDENCE','FOC_CURRENT_STEP_AB_DIAG',
              'FOC_CURRENT_PI_IDENTIFIED_ENABLE','FOC_PWM_PIPELINE_CLOSED_LOOP',
              'FOC_STARTUP_TRACE','AS5047P_DMA_FOC_FIRST')
    if (len(data)!=213964 or base.old.zero.digest(data)!=SHA or
        base.old.zero.digest(ELF.read_bytes())!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        any(command.count('-D'+key+'=1')!=1 for key in required) or
        any('-D'+key+'=1' in command for key in ('FOC_FAST_REJECT_COMPUTE_ONLY',
            'FOC_TORQUE_CHAIN_DIAG','FOC_MOTOR_IDENTIFICATION_DIAG','FOC_FRICTION_CALIBRATION_DIAG'))):
        raise ValueError('Exact offline-tested gate-evidence A BIN/ELF/configuration required')
    for marker in (b'CURRENT_STEP_AB_DIAGNOSTIC: LOCK ROTOR',b'NAME=CURRENT_STEP_AB',
                   b'TRIP_MA=4000',b'METHOD=TWO_SAMPLE',b'STARTUP CONFIG ENABLED=1 ROWS=8'):
        if marker not in data:raise ValueError('Protected diagnostic marker absent')
    table=base.symbols(ELF)
    if (table['cl_output_gate_evidence'][1]!=SIZE or
        table['current_step_ab'][1]!=step.ctypes.sizeof(step.analysis.Capture) or
        'ProtectedLoop_GatesObserved' not in table):
        raise ValueError('Pre-closure evidence/step ABI missing')
    return data

def select_legacy():
    for k in ('IMAGE','ELF','SHA','ELF_SHA','image'):setattr(step,k,LEGACY[k])

def select_new():
    for k,value in dict(IMAGE=IMAGE,ELF=ELF,SHA=SHA,ELF_SHA=ELF_SHA,image=image).items():
        setattr(step,k,value);setattr(base,k,value)

def configure(path=None):
    path=Path(path or RESTORE)
    receipt=json.loads(path.read_text('utf-8'))
    # Explicitly whitelist exact old/new identities. configure_baseline still
    # verifies ALL bytes, metadata CRC, successful restore and root preservation.
    identity=(receipt.get('image_sha256'),receipt.get('elf_sha256'))
    select_legacy()
    if identity==(LEGACY['SHA'],LEGACY['ELF_SHA']):
        LEGACY['configure'](path)
    elif identity==(SHA,ELF_SHA):
        LEGACY['configure']()
        select_new();base.configure_baseline(path)
    else:
        raise ValueError('Unknown baseline image identity; no device access')
    select_new()

def decode_capture(row):
    LEGACY['decode_capture'](row)  # Original same-session/full-image proof first.
    row['gate_evidence']=decode_gate(Path(row['ram_capture']).read_bytes(),ELF)
    row['evidence_acquisition_pass']=bool(
        row['gate_evidence'].get('status')=='MEASURED_FAILED_PREDICATE' and
        row.get('final_cpu_halted') and row.get('final_outputs_off'))

def main(argv=None):
    # This separate executable opts into the new image; importing it is inert.
    try:
        step.configure=configure;step.decode_capture=decode_capture
        return step.main(argv)
    finally:
        for k,value in LEGACY.items():setattr(step,k,value)

if __name__=='__main__':raise SystemExit(main())
