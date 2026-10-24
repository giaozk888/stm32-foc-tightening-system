"""Pinned identification-policy step A, OFF stage / one ON batch / OFF restore.

Files-only default. Policy200-warning/400-cutoff must be read back before the
single diagnostic command. Existing protections, first-fault evidence and
full-image/root-preservation checks are not bypassed. No normal START/retry.
"""
import json
from pathlib import Path
import struct
import current_step_gate_board as gate
import encoder_saved_fault_report as encoder_report

step=gate.step;base=step.base
IMAGE=base.old.ROOT/'foc2_app_a/build/CurrentStepAbIdentPolicy/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='20398c4906f1b1a6ba1fc6902cde68c0e1988fd0b64f6e091ff885c22e48f9d1'
ELF_SHA='5db4b36d06688ecc30fc0a011625be2d3a6245adf9f02f63f991df4bc4d0776e'
RESTORE=step.TMP/'current-step-ab-restore-1792573553886125200.json'
POLICY_COMMAND='MOTOR TEST CURRENT STEP ENCODER TIME'
ORIGINAL_MOTION=step.motion
ORIGINALS={k:getattr(step,k) for k in ('IMAGE','ELF','SHA','ELF_SHA','image','configure','decode_capture','motion')}

def image():
    data=IMAGE.read_bytes()
    command=next(x['command'] for x in json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
                 if x['file'].endswith('/Core/Src/main.c'))
    base.support.support.require_baud(command)
    required=('FOC_CURRENT_STEP_IDENT_POLICY=1','AS5047P_DMA_TERMINAL_FIX=1',
              'AS5047P_DMA_TIMING_POLICY_V2=1','AS_DMA_TRANSACTION_US=400U',
              'FOC_OUTPUT_GATE_EVIDENCE=1','FOC_CURRENT_STEP_AB_DIAG=1',
              'FOC_CURRENT_PI_IDENTIFIED_ENABLE=1','FOC_PWM_PIPELINE_CLOSED_LOOP=1',
              'FOC_STARTUP_TRACE=1','AS5047P_DMA_FOC_FIRST=1')
    if (len(data)!=214340 or base.old.zero.digest(data)!=SHA or
        base.old.zero.digest(ELF.read_bytes())!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        any(command.count('-D'+key)!=1 for key in required) or
        any('-D'+key+'=1' in command for key in ('FOC_FAST_REJECT_COMPUTE_ONLY',
            'FOC_TORQUE_CHAIN_DIAG','FOC_MOTOR_IDENTIFICATION_DIAG','FOC_FRICTION_CALIBRATION_DIAG'))):
        raise ValueError('Exact tested identification-policy step BIN/ELF/configuration required')
    for marker in (b'CURRENT_STEP_AB_DIAGNOSTIC: LOCK ROTOR',b'NAME=CURRENT_STEP_AB',
                   b'TRIP_MA=4000',b'METHOD=TWO_SAMPLE',b'STARTUP CONFIG ENABLED=1 ROWS=8',
                   b'ENC POLICY=2 TERMINAL_FIX=1'):
        if marker not in data:raise ValueError('Protected policy diagnostic marker missing')
    table=base.symbols(ELF)
    if (table['cl_output_gate_evidence'][1]!=gate.SIZE or table['transaction_timing'][1]!=8 or
        table['current_step_ab'][1]!=step.ctypes.sizeof(step.analysis.Capture)):
        raise ValueError('Policy, gate or step capture ABI mismatch')
    return data

def select_new():
    for key,value in dict(IMAGE=IMAGE,ELF=ELF,SHA=SHA,ELF_SHA=ELF_SHA,image=image).items():
        setattr(step,key,value);setattr(base,key,value)

def configure(path=None):
    path=Path(path or RESTORE);r=json.loads(path.read_text('utf-8'))
    identity=(r.get('image_sha256'),r.get('elf_sha256'))
    if identity==(SHA,ELF_SHA):
        gate.select_legacy();gate.LEGACY['configure']()
        select_new();base.configure_baseline(path)
    else:
        gate.configure(path)  # Exact old/gate image + complete B/boot/private proof.
    select_new()

def policy(line):
    return step.expect(line,dict(POLICY=2,TERMINAL_FIX=1,WARN_US=200,DEADLINE_US=400,
        SCHED_US=200,PERIOD_US=1000,AGE_US=1500,CONTROL_US=2500),'Identification encoder policy')

def motion(board,row,clock=step.time.monotonic):
    row['encoder_policy_before']=policy(board.command(POLICY_COMMAND))
    try:
        ORIGINAL_MOTION(board,row,clock)
    finally:
        if row.get('excitation_attempts'):
            try:
                row['encoder_policy_after']=policy(board.command(POLICY_COMMAND))
                row['encoder_slow_count_delta']=(int(row['encoder_policy_after']['SLOW_N'])-
                    int(row['encoder_policy_before']['SLOW_N']))&0xffffffff
            except Exception as error:
                row['stop_error']=row.get('stop_error','')+'; policy readback failed: '+str(error)

def decode_capture(row):
    gate.LEGACY['decode_capture'](row)  # Existing full-image + same-session proof.
    ram=Path(row['ram_capture']).read_bytes()
    row['gate_evidence']=gate.decode_gate(ram,ELF)
    address,size=base.symbols(ELF)['transaction_timing']
    if size!=8 or not 0<=address-0x20000000<=len(ram)-8:raise ValueError('Policy stats SRAM bounds')
    slow,maximum=struct.unpack_from('<2I',ram,address-0x20000000)
    row['encoder_policy_saved']=dict(warn_us=200,deadline_us=400,slow_completed_count=slow,
                                    ok_max_us=maximum,semantics='successful transactions since boot')
    try:row['encoder_saved']=encoder_report.decode_saved(row,ELF)
    except (ValueError,KeyError) as error:row['encoder_decode_error']=str(error)

def main(argv=None):
    try:
        step.configure=configure;step.decode_capture=decode_capture;step.motion=motion
        return step.main(argv)
    finally:
        for key,value in ORIGINALS.items():setattr(step,key,value)

if __name__=='__main__':raise SystemExit(main())
