"""Pinned terminal-arbitration Rs50 candidate; one attempt, OFF/ON/OFF."""
import json
from pathlib import Path
import motor_ident_rs_reject_only_board as previous
import encoder_saved_fault_report as encoder_report

run=previous.run; base=run.base; TMP=run.TMP
RESTORE=TMP/'motor-ident-rs50-restore-1792501184846342900.json'
BASE_SHA='d59a9683671dad1382224054d96ea47c4df1d7d5aec9b5a27aebef5a825248c0'
IMAGE=base.old.ROOT/'foc2_app_a/build/MotorParameterIdentificationEncoderTerminalDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='2e0661646b6bedc372c7d7f4209e4dc4f5279f23a1082f0d9992c680b11c7b2f'
ELF_SHA='6a55c7148828a5eb613dcb26dfa969b24eed9d7ec99091b5cb021c47bd1d261a'


def image():
    data=IMAGE.read_bytes()
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
             if c['file'].endswith('/Core/Src/main.c'))
    driver_cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
                    if c['file'].endswith('/as5047p_dma_stm32.c'))
    base.support.support.require_baud(cmd);symbols=base.symbols(ELF)
    if (len(data)!=214764 or base.old.zero.digest(data)!=SHA or
        base.old.zero.digest(ELF.read_bytes())!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        symbols.get('motor_ident',(0,0))[1]!=1740 or symbols.get('defer_terminal_claimed',(0,0))[1]!=4 or
        any(k not in cmd for k in ('-DFOC_MOTOR_IDENTIFICATION_DIAG=1',
          '-DFOC_IDENT_CURRENT_REJECT_ENABLE=1','-DFOC_IDENT_TIMING_TRACE_ENABLE=1',
          '-DFOC_IDENT_RS_NO_TOTAL_REJECT_EXIT=1','-DFOC_IDENT_RS_GAP_ADMISSION_ENABLE=1',
          '-DMID_TRAVEL_EXIT_ENABLE=0','-DMID_RS_SOFT_DT_MAX_US=100U',
          '-DFOC_PWM_PIPELINE_CLOSED_LOOP=1','-DSPEED_FRICTION_I_A=0.105f')) or
        '-DAS5047P_DMA_TERMINAL_FIX=1' not in driver_cmd or '-DAS5047P_DMA_FOC_FIRST=1' not in driver_cmd or
        any(k in cmd for k in ('-DFOC_FRICTION_CALIBRATION_DIAG','-DFOC_TORQUE_CHAIN_DIAG')) or
        any(k not in data for k in (b'MOTOR_IDENT_DIAGNOSTIC: LOCK ROTOR; manual one-shot; no START',
            b'TRAVEL_EXIT=OFF',b'TOTAL_STOP=%u',b'TRIP_MA=4000',b'OK MID RS_DT_MAX='))):
        raise ValueError('Exact offline-tested encoder-terminal A BIN/ELF/ABI required')
    return data


def configure():
    run.ORIGINAL_CONFIGURE(base.ROOT_RESTORE); root=base.baseline()
    r=json.loads(RESTORE.read_text('utf-8')); capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or
        r.get('image_sha256')!=previous.SHA or r.get('motor_commands')!=0 or
        any(r.get(k) is not True for k in ('pass_','all_app_private_unchanged',
            'b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Exact preserved B832 restore receipt required')
    raw=capture.read_bytes(); meta=base.old.zero.latest_meta(raw); off=r.get('outputs',{})
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=BASE_SHA or r.get('final_sha256')!=BASE_SHA or
        list(meta)!=r.get('metadata') or meta[2:10]!=(2,0,0,832,214628,169658418,227964,627317606) or
        base.old.zero.digest(raw[0x8000:0x8000+214628])!=r['image_sha256'] or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or off.get('VTOR')!=0x08040000 or
        not off.get('DHCSR',0)&0x20000 or off.get('SD',0x40)&0x40 or
        off.get('BDTR',0xC000)&0xC000 or off.get('CCER',1)):
        raise ValueError('B832 image/B/boot/private/output mismatch')
    base.BASE=capture; base.BASE_SHA=BASE_SHA; base.EXPECT_META=meta
    base.BASE_RESTORE_RECEIPT=RESTORE.resolve()


def extra_decode(row,ram,offset):
    # Saved RAM only. Preserve encoder evidence even if estimator quality fails.
    row['encoder_terminal_saved']=encoder_report.decode_saved(row,ELF)
    previous.extra_decode(row,ram,offset)


def install():
    run.IMAGE,run.ELF,run.SHA,run.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    run.RESTORE,run.BASE_SHA=RESTORE,BASE_SHA
    run.image=image;run.configure=configure;run.IDENT_SIZE=1740;run.motion=previous.previous.motion
    run.EXTRA_READOUT=previous.extra_readout;run.EXTRA_DECODE=extra_decode


def main():
    install()
    return run.main()


if __name__=='__main__':raise SystemExit(main())
