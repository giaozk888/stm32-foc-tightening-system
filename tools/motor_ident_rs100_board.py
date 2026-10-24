"""Pinned Rs100us RS50 only: supervised OFF/ON/OFF, never auto retry/advance."""
import json
from pathlib import Path
import motor_ident_rs_gap_board as previous

run=previous.run; base=run.base; TMP=run.TMP
ORIGINAL_MOTION=run.motion
RESTORE=TMP/'motor-ident-rs50-restore-1792500005710633900.json'
BASE_SHA='44993de53cece5f9faaac48570ba5a077612bb7ab34bfd289a80656f0062ba7f'
IMAGE=base.old.ROOT/'foc2_app_a/build/MotorParameterIdentificationRs100usDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='3f38586c511f688da8b66862d9a27ea8dce11b9c4b869f7bdc526a53bc1bae3e'
ELF_SHA='3c62c253b0dc4c7dd796889db9d4d274ec77d6c7b1c93b85a058f913286cef47'


def image():
    data=IMAGE.read_bytes()
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
             if c['file'].endswith('/Core/Src/main.c'))
    base.support.support.require_baud(cmd)
    if (len(data)!=214596 or base.old.zero.digest(data)!=SHA or
        base.old.zero.digest(ELF.read_bytes())!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        base.symbols(ELF).get('motor_ident',(0,0))[1]!=1740 or
        any(k not in cmd for k in ('-DFOC_MOTOR_IDENTIFICATION_DIAG=1',
          '-DFOC_IDENT_CURRENT_REJECT_ENABLE=1','-DFOC_IDENT_TIMING_TRACE_ENABLE=1',
          '-DFOC_IDENT_RS_GAP_ADMISSION_ENABLE=1','-DMID_TRAVEL_EXIT_ENABLE=0',
          '-DMID_RS_SOFT_DT_MAX_US=100U','-DFOC_PWM_PIPELINE_CLOSED_LOOP=1','-DSPEED_FRICTION_I_A=0.105f')) or
        any(k in cmd for k in ('-DFOC_FRICTION_CALIBRATION_DIAG','-DFOC_TORQUE_CHAIN_DIAG')) or
        any(k not in data for k in (b'MOTOR_IDENT_DIAGNOSTIC: LOCK ROTOR; manual one-shot; no START',
            b'TRAVEL_EXIT=OFF',b'REJECT_MAX=16 RUN_LIMIT=3',b'TRIP_MA=4000',b'OK MID RS_DT_MAX='))):
        raise ValueError('Exact offline-tested Rs100 A BIN/ELF/1740 ABI required')
    return data


def configure():
    run.ORIGINAL_CONFIGURE(base.ROOT_RESTORE); root=base.baseline()
    r=json.loads(RESTORE.read_text('utf-8')); capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or
        r.get('image_sha256')!=previous.SHA or r.get('motor_commands')!=0 or
        any(r.get(k) is not True for k in ('pass_','all_app_private_unchanged',
            'b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Exact preserved B824 restore receipt required')
    raw=capture.read_bytes(); meta=base.old.zero.latest_meta(raw); off=r.get('outputs',{})
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=BASE_SHA or r.get('final_sha256')!=BASE_SHA or
        list(meta)!=r.get('metadata') or meta[2:10]!=(2,0,0,824,214452,3168559771,227964,627317606) or
        base.old.zero.digest(raw[0x8000:0x8000+214452])!=r['image_sha256'] or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or off.get('VTOR')!=0x08040000 or
        not off.get('DHCSR',0)&0x20000 or off.get('SD',0x40)&0x40 or
        off.get('BDTR',0xC000)&0xC000 or off.get('CCER',1)):
        raise ValueError('B824 image/B/boot/private/output mismatch')
    base.BASE=capture; base.BASE_SHA=BASE_SHA; base.EXPECT_META=meta
    base.BASE_RESTORE_RECEIPT=RESTORE.resolve()


def policy(line):
    f=base.hw.fields(line)
    if any(f.get(k)!=v for k,v in dict(RS_DT_MAX='100',L_DT_MAX='55',DT_MIN='45',
                                     GAP_DT_PER_SEQ_MAX='55').items()):
        raise ValueError('Explicit Rs100/L55 timing policy required before excitation')
    return f


def motion(board,row):
    row['time_policy_pre']=policy(board.command('MOTOR TEST IDENT TIME POLICY'))
    ORIGINAL_MOTION(board,row)


def extra_readout(board,row):
    previous.extra_readout(board,row)
    line=board.command('MOTOR TEST IDENT TIME POLICY');row['time_policy_reply']=line
    row['time_policy_post']=policy(line);row['ident_replies'].append(line)


def extra_decode(row,ram,offset,*,total_reject_stop=True,total_gap_stop=True,run_reject_stop=True):
    policy(row.get('time_policy_reply',''))
    previous.extra_decode(row,ram,offset,max_dt_us=100,total_reject_stop=total_reject_stop,
                          total_gap_stop=total_gap_stop,run_reject_stop=run_reject_stop)
    row['ident_run']['time_policy']=row['time_policy_post']


def install():
    run.IMAGE,run.ELF,run.SHA,run.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    run.RESTORE,run.BASE_SHA=RESTORE,BASE_SHA
    run.image=image;run.configure=configure;run.IDENT_SIZE=1740;run.motion=motion
    run.EXTRA_READOUT=extra_readout;run.EXTRA_DECODE=extra_decode


def main():
    install()
    return run.main()


if __name__=='__main__':raise SystemExit(main())
