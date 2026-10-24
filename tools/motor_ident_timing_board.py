"""Pinned RS50 continuity snapshot; explicit OFF/ON/OFF, one command, no retry."""
import json
from pathlib import Path
import motor_ident_no_travel_board as previous
import motor_ident_timing_report as report

run=previous.run; base=run.base; TMP=run.TMP
RESTORE=TMP/'motor-ident-rs50-restore-1792498798399003500.json'
BASE_SHA='6a04e0d69a676fd184c9599d832bde2edb4057f0909913dc581781629028475c'
IMAGE=base.old.ROOT/'foc2_app_a/build/MotorParameterIdentificationTimingDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='ecb4b77584e4d589f2881719a1741907335b2e2264d480ee16b815385d9e899c'
ELF_SHA='19c5654714df2a9abf641d94f891fee8425ac181c1ae7155073efba66f8faf49'


def image():
    data=IMAGE.read_bytes()
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
             if c['file'].endswith('/Core/Src/main.c'))
    base.support.support.require_baud(cmd)
    if (len(data)!=214156 or base.old.zero.digest(data)!=SHA or
        base.old.zero.digest(ELF.read_bytes())!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        base.symbols(ELF).get('motor_ident',(0,0))[1]!=1724 or
        any(k not in cmd for k in ('-DFOC_MOTOR_IDENTIFICATION_DIAG=1',
          '-DFOC_IDENT_CURRENT_REJECT_ENABLE=1','-DFOC_IDENT_TIMING_TRACE_ENABLE=1',
          '-DMID_TRAVEL_EXIT_ENABLE=0','-DFOC_PWM_PIPELINE_CLOSED_LOOP=1','-DSPEED_FRICTION_I_A=0.105f')) or
        any(k in cmd for k in ('-DFOC_FRICTION_CALIBRATION_DIAG','-DFOC_TORQUE_CHAIN_DIAG')) or
        any(k not in data for k in (b'MOTOR_IDENT_DIAGNOSTIC: LOCK ROTOR; manual one-shot; no START',
            b'TRAVEL_EXIT=OFF',b'REJECT_MAX=16 RUN_LIMIT=3',b'TRIP_MA=4000',b'OK MID TV='))):
        raise ValueError('Exact offline-tested timing A BIN/ELF/1724 ABI required')
    return data


def configure():
    run.ORIGINAL_CONFIGURE(base.ROOT_RESTORE); root=base.baseline()
    r=json.loads(RESTORE.read_text('utf-8')); capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or
        r.get('image_sha256')!=previous.SHA or r.get('motor_commands')!=0 or
        any(r.get(k) is not True for k in ('pass_','all_app_private_unchanged',
            'b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Exact preserved B816 restore receipt required')
    raw=capture.read_bytes(); meta=base.old.zero.latest_meta(raw); off=r.get('outputs',{})
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=BASE_SHA or r.get('final_sha256')!=BASE_SHA or
        list(meta)!=r.get('metadata') or meta[2:10]!=(2,0,0,816,213580,700774388,227964,627317606) or
        base.old.zero.digest(raw[0x8000:0x8000+213580])!=r['image_sha256'] or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or off.get('VTOR')!=0x08040000 or
        not off.get('DHCSR',0)&0x20000 or off.get('SD',0x40)&0x40 or
        off.get('BDTR',0xC000)&0xC000 or off.get('CCER',1)):
        raise ValueError('B816 image/B/boot/private/output mismatch')
    base.BASE=capture; base.BASE_SHA=BASE_SHA; base.EXPECT_META=meta
    base.BASE_RESTORE_RECEIPT=RESTORE.resolve()


def extra_readout(board,row):
    previous.extra_readout(board,row)
    for key,cmd in (('timing_failure_reply','MOTOR TEST IDENT TIMING'),
                    ('timing_context_reply','MOTOR TEST IDENT TIMING CONTEXT')):
        line=board.command(cmd);row[key]=line;row['ident_replies'].append(line)
        required='TV' if key=='timing_failure_reply' else 'CV'
        if required not in base.hw.fields(line):raise RuntimeError('Timing snapshot readout absent')


def extra_decode(row,ram,offset,*,max_dt_us=55,total_reject_stop=True,run_reject_stop=True):
    previous.reject.extra_decode(row,ram,offset,total_reject_stop=total_reject_stop,
                                 run_reject_stop=run_reject_stop)
    decoded=report.decode(ram,offset,max_dt_us=max_dt_us);row['ident_timing_failure']=decoded
    snapshot=decoded['snapshot']
    wire={**base.hw.fields(row.get('timing_failure_reply','')),
          **base.hw.fields(row.get('timing_context_reply',''))}
    keys=dict(TV='valid',PS='prev_seq',PU='prev_us',S='seq',U='us',DS='delta_seq',
              DT='delta_us',WHY='flags',CV='context_valid',ADC='adc_seq',FRAME='frame_seq',
              PAIR_US='pair_us',HB='hold_before',HN='hold_now',PATH='path')
    if any(wire.get(k)!=str(snapshot[v]) for k,v in keys.items()):
        raise ValueError('Frozen UART/RAM timing snapshot mismatch')


def install():
    run.IMAGE,run.ELF,run.SHA,run.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    run.RESTORE,run.BASE_SHA=RESTORE,BASE_SHA
    run.image=image;run.configure=configure;run.IDENT_SIZE=1724
    run.EXTRA_READOUT=extra_readout;run.EXTRA_DECODE=extra_decode


def main():
    install()
    return run.main()


if __name__=='__main__':raise SystemExit(main())
