"""Pinned Rs explained-gap count-only A; one supervised Rs50, OFF/ON/OFF."""
import json
from pathlib import Path
import motor_ident_encoder_timing_board as previous

run=previous.run; base=run.base; TMP=run.TMP
RESTORE=TMP/'motor-ident-rs50-restore-1792554819544503300.json'
BASE_SHA='7d5d7eeab10c7d9c1f33ca1a1604dd962de19c1e9f64a7b03d4a37f18b62c061'
IMAGE=base.old.ROOT/'foc2_app_a/build/MotorParameterIdentificationRsGapCountDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='68f066ad4fad8df0737271f0b0eec3937266f05ebea253de83f78eea8b212c06'
ELF_SHA='c085819200ad4c7bd345e68b5d0483ed344fccb9cd7674d268dc18f1e9fb3c57'
reject_only=previous.previous.previous


def pinned_image(path,sha,elf_sha,size,extra_flags=()):
    data=path.read_bytes()
    commands=json.loads((path.parent/'compile_commands.json').read_text('utf-8'))
    cmd=next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
    driver=next(c['command'] for c in commands if c['file'].endswith('/as5047p_dma_stm32.c'))
    base.support.support.require_baud(cmd);symbols=base.symbols(path.with_suffix('.elf'))
    if (len(data)!=size or base.old.zero.digest(data)!=sha or
        base.old.zero.digest(path.with_suffix('.elf').read_bytes())!=elf_sha or base.hw.image_info(data)[0]!='A' or
        symbols.get('motor_ident',(0,0))[1]!=1740 or symbols.get('defer_terminal_claimed',(0,0))[1]!=4 or
        any(k not in cmd for k in ('-DFOC_MOTOR_IDENTIFICATION_DIAG=1',
          '-DFOC_IDENT_CURRENT_REJECT_ENABLE=1','-DFOC_IDENT_TIMING_TRACE_ENABLE=1',
          '-DFOC_IDENT_RS_NO_TOTAL_REJECT_EXIT=1','-DFOC_IDENT_RS_GAP_ADMISSION_ENABLE=1',
          '-DFOC_IDENT_RS_GAP_COUNT_ONLY=1','-DMID_TRAVEL_EXIT_ENABLE=0',
          '-DMID_RS_SOFT_DT_MAX_US=100U','-DFOC_PWM_PIPELINE_CLOSED_LOOP=1','-DSPEED_FRICTION_I_A=0.105f')) or
        any(k not in cmd for k in extra_flags) or
        any(k not in c for c in (cmd,driver) for k in
            ('-DAS5047P_DMA_TIMING_POLICY_V2=1','-DAS_DMA_TRANSACTION_US=400U')) or
        any(k not in driver for k in ('-DAS5047P_DMA_TERMINAL_FIX=1','-DAS5047P_DMA_FOC_FIRST=1')) or
        any(k in cmd for k in ('-DFOC_FRICTION_CALIBRATION_DIAG','-DFOC_TORQUE_CHAIN_DIAG')) or
        any(k not in data for k in (b'MOTOR_IDENT_DIAGNOSTIC: LOCK ROTOR; manual one-shot; no START',
          b'TRAVEL_EXIT=OFF',b'BUDGET=%u RUN_LIMIT=2 TOTAL_STOP=%u',b'TRIP_MA=4000',b'OK ENC POLICY='))):
        raise ValueError('Exact offline-tested Rs gap count-only A BIN/ELF/ABI required')
    return data


def image():
    return pinned_image(IMAGE,SHA,ELF_SHA,215076)


def configure():
    run.ORIGINAL_CONFIGURE(base.ROOT_RESTORE);root=base.baseline()
    r=json.loads(RESTORE.read_text('utf-8'));capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or
        r.get('image_sha256')!=previous.SHA or r.get('motor_commands')!=0 or
        any(r.get(k) is not True for k in ('pass_','all_app_private_unchanged',
            'b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Exact preserved B840 restore receipt required')
    raw=capture.read_bytes();meta=base.old.zero.latest_meta(raw);off=r.get('outputs',{})
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=BASE_SHA or r.get('final_sha256')!=BASE_SHA or
        list(meta)!=r.get('metadata') or meta[2:10]!=(2,0,0,840,215060,1355042686,227964,627317606) or
        base.old.zero.digest(raw[0x8000:0x8000+215060])!=r['image_sha256'] or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or off.get('VTOR')!=0x08040000 or
        not off.get('DHCSR',0)&0x20000 or off.get('SD',0x40)&0x40 or
        off.get('BDTR',0xC000)&0xC000 or off.get('CCER',1)):
        raise ValueError('B840 image/B/boot/private/output mismatch')
    base.BASE=capture;base.BASE_SHA=BASE_SHA;base.EXPECT_META=meta
    base.BASE_RESTORE_RECEIPT=RESTORE.resolve()


def extra_readout(board,row,*,run_reject_stop=True):
    previous.extra_readout(board,row,run_reject_stop=run_reject_stop)
    wire=base.hw.fields(row['rs_gap_reply'])
    if any(wire.get(k)!=v for k,v in dict(BUDGET='0',RUN_LIMIT='2',TOTAL_STOP='0').items()):
        raise ValueError('Explicit count-only Rs gap policy required')


def extra_decode(row,ram,offset):
    row['encoder_terminal_saved']=previous.previous.encoder_report.decode_saved(row,ELF)
    reject_only.extra_decode(row,ram,offset,total_gap_stop=False)


def install():
    run.IMAGE,run.ELF,run.SHA,run.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    run.RESTORE,run.BASE_SHA=RESTORE,BASE_SHA
    run.image=image;run.configure=configure;run.IDENT_SIZE=1740;run.motion=previous.motion
    run.EXTRA_READOUT=extra_readout;run.EXTRA_DECODE=extra_decode


def main():
    install()
    return run.main()


if __name__=='__main__':raise SystemExit(main())
