"""Pinned encoder timing-policy A: one supervised Rs50 attempt, OFF/ON/OFF."""
import json
from pathlib import Path
import motor_ident_encoder_terminal_board as previous

run=previous.run; base=run.base; TMP=run.TMP
RESTORE=TMP/'motor-ident-rs50-restore-1792502360728781200.json'
BASE_SHA='f94488739e12c03319ef24c1823904f3262ae6bd4b75ef1ea08e406c8cbba02f'
IMAGE=base.old.ROOT/'foc2_app_a/build/MotorParameterIdentificationEncoderTimingDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='09ac2082aec995fd6be5e826a887aba2513521319cf13783119157c460fda661'
ELF_SHA='0fff84c68c506b25b9ec0ca956ede8cb5cfe52ff38d54274065bad7859e881ad'


def image():
    data=IMAGE.read_bytes()
    commands=json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
    cmd=next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
    driver=next(c['command'] for c in commands if c['file'].endswith('/as5047p_dma_stm32.c'))
    base.support.support.require_baud(cmd); symbols=base.symbols(ELF)
    if (len(data)!=215060 or base.old.zero.digest(data)!=SHA or
        base.old.zero.digest(ELF.read_bytes())!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        symbols.get('motor_ident',(0,0))[1]!=1740 or
        symbols.get('defer_terminal_claimed',(0,0))[1]!=4 or
        any(k not in cmd for k in ('-DFOC_MOTOR_IDENTIFICATION_DIAG=1',
          '-DFOC_IDENT_CURRENT_REJECT_ENABLE=1','-DFOC_IDENT_TIMING_TRACE_ENABLE=1',
          '-DFOC_IDENT_RS_NO_TOTAL_REJECT_EXIT=1','-DFOC_IDENT_RS_GAP_ADMISSION_ENABLE=1',
          '-DMID_TRAVEL_EXIT_ENABLE=0','-DMID_RS_SOFT_DT_MAX_US=100U',
          '-DFOC_PWM_PIPELINE_CLOSED_LOOP=1','-DSPEED_FRICTION_I_A=0.105f')) or
        any(k not in c for c in (cmd,driver) for k in
            ('-DAS5047P_DMA_TIMING_POLICY_V2=1','-DAS_DMA_TRANSACTION_US=400U')) or
        any(k not in driver for k in ('-DAS5047P_DMA_TERMINAL_FIX=1','-DAS5047P_DMA_FOC_FIRST=1')) or
        any(k in cmd for k in ('-DFOC_FRICTION_CALIBRATION_DIAG','-DFOC_TORQUE_CHAIN_DIAG')) or
        any(k not in data for k in (b'MOTOR_IDENT_DIAGNOSTIC: LOCK ROTOR; manual one-shot; no START',
            b'TRAVEL_EXIT=OFF',b'TOTAL_STOP=%u',b'TRIP_MA=4000',b'OK MID RS_DT_MAX=',b'OK ENC POLICY='))):
        raise ValueError('Exact offline-tested encoder timing-policy A BIN/ELF/ABI required')
    return data


def configure():
    run.ORIGINAL_CONFIGURE(base.ROOT_RESTORE); root=base.baseline()
    r=json.loads(RESTORE.read_text('utf-8')); capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or
        r.get('image_sha256')!=previous.SHA or r.get('motor_commands')!=0 or
        any(r.get(k) is not True for k in ('pass_','all_app_private_unchanged',
            'b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Exact preserved B836 restore receipt required')
    raw=capture.read_bytes(); meta=base.old.zero.latest_meta(raw); off=r.get('outputs',{})
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=BASE_SHA or r.get('final_sha256')!=BASE_SHA or
        list(meta)!=r.get('metadata') or meta[2:10]!=(2,0,0,836,214764,257713228,227964,627317606) or
        base.old.zero.digest(raw[0x8000:0x8000+214764])!=r['image_sha256'] or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or off.get('VTOR')!=0x08040000 or
        not off.get('DHCSR',0)&0x20000 or off.get('SD',0x40)&0x40 or
        off.get('BDTR',0xC000)&0xC000 or off.get('CCER',1)):
        raise ValueError('B836 image/B/boot/private/output mismatch')
    base.BASE=capture; base.BASE_SHA=BASE_SHA; base.EXPECT_META=meta
    base.BASE_RESTORE_RECEIPT=RESTORE.resolve()


def policy(line):
    f=base.hw.fields(line)
    expected=dict(POLICY='2',WARN_US='200',DEADLINE_US='400',SCHED_US='200',
                  PERIOD_US='1000',AGE_US='1500',CONTROL_US='2500')
    if any(f.get(k)!=v for k,v in expected.items()):
        raise ValueError('Explicit encoder policy2/400us required before excitation')
    for key in ('SLOW_N','OK_MAX_US'):
        if not f.get(key,'').isdigit():raise ValueError('Missing encoder timing statistic')
    return f


def motion(board,row):
    row['encoder_time_pre']=policy(board.command('MOTOR TEST IDENT ENCODER TIME'))
    previous.previous.previous.motion(board,row)


def extra_readout(board,row,*,run_reject_stop=True):
    # Original runner has already stopped and proved SD/MOE off here.
    line=board.command('MOTOR TEST IDENT ENCODER TIME')
    row['encoder_time_reply']=line;row['ident_replies'].append(line)
    row['encoder_time_post']=policy(line)
    row['encoder_slow_delta_including_readout']=(int(row['encoder_time_post']['SLOW_N'])-
        int(row['encoder_time_pre']['SLOW_N'])) & 0xffffffff
    previous.previous.extra_readout(board,row,run_reject_stop=run_reject_stop)


def extra_decode(row,ram,offset):
    # Keep same-session encoder evidence even if estimator quality rejects rows.
    row['encoder_terminal_saved']=previous.encoder_report.decode_saved(row,ELF)
    previous.previous.extra_decode(row,ram,offset)


def install():
    run.IMAGE,run.ELF,run.SHA,run.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    run.RESTORE,run.BASE_SHA=RESTORE,BASE_SHA
    run.image=image;run.configure=configure;run.IDENT_SIZE=1740;run.motion=motion
    run.EXTRA_READOUT=extra_readout;run.EXTRA_DECODE=extra_decode


def main():
    install()
    return run.main()


if __name__=='__main__':raise SystemExit(main())
