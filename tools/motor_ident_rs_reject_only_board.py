"""Pinned Rs50 reject-only candidate: one supervised 400ms attempt, OFF/ON/OFF."""
import json
from pathlib import Path
import motor_ident_rs100_board as previous

run=previous.run; base=run.base; TMP=run.TMP
RESTORE=TMP/'motor-ident-rs50-restore-1792500618687820400.json'
BASE_SHA='fb1d6d7218ed772473cdae38eecb8b599f340b7eb3206a4ee36c6c5f3eea2c8f'
IMAGE=base.old.ROOT/'foc2_app_a/build/MotorParameterIdentificationRsRejectOnlyDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='c0be6a0d65a1aefa52e30b4b036005ab8787ea96be5f4f720b723f61f820d9d4'
ELF_SHA='c83291d4f565294e30da369a374ceba48bce9c36e04876deae82751331139857'


def image():
    data=IMAGE.read_bytes()
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
             if c['file'].endswith('/Core/Src/main.c'))
    base.support.support.require_baud(cmd)
    if (len(data)!=214628 or base.old.zero.digest(data)!=SHA or
        base.old.zero.digest(ELF.read_bytes())!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        base.symbols(ELF).get('motor_ident',(0,0))[1]!=1740 or
        any(k not in cmd for k in ('-DFOC_MOTOR_IDENTIFICATION_DIAG=1',
          '-DFOC_IDENT_CURRENT_REJECT_ENABLE=1','-DFOC_IDENT_TIMING_TRACE_ENABLE=1',
          '-DFOC_IDENT_RS_NO_TOTAL_REJECT_EXIT=1','-DFOC_IDENT_RS_GAP_ADMISSION_ENABLE=1',
          '-DMID_TRAVEL_EXIT_ENABLE=0','-DMID_RS_SOFT_DT_MAX_US=100U',
          '-DFOC_PWM_PIPELINE_CLOSED_LOOP=1','-DSPEED_FRICTION_I_A=0.105f')) or
        any(k in cmd for k in ('-DFOC_FRICTION_CALIBRATION_DIAG','-DFOC_TORQUE_CHAIN_DIAG')) or
        any(k not in data for k in (b'MOTOR_IDENT_DIAGNOSTIC: LOCK ROTOR; manual one-shot; no START',
            b'TRAVEL_EXIT=OFF',b'TOTAL_STOP=%u',b'TRIP_MA=4000',b'OK MID RS_DT_MAX='))):
        raise ValueError('Exact offline-tested Rs reject-only A BIN/ELF/1740 ABI required')
    return data


def configure():
    run.ORIGINAL_CONFIGURE(base.ROOT_RESTORE); root=base.baseline()
    r=json.loads(RESTORE.read_text('utf-8')); capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or
        r.get('image_sha256')!=previous.SHA or r.get('motor_commands')!=0 or
        any(r.get(k) is not True for k in ('pass_','all_app_private_unchanged',
            'b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Exact preserved B828 restore receipt required')
    raw=capture.read_bytes(); meta=base.old.zero.latest_meta(raw); off=r.get('outputs',{})
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=BASE_SHA or r.get('final_sha256')!=BASE_SHA or
        list(meta)!=r.get('metadata') or meta[2:10]!=(2,0,0,828,214596,3009682717,227964,627317606) or
        base.old.zero.digest(raw[0x8000:0x8000+214596])!=r['image_sha256'] or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or off.get('VTOR')!=0x08040000 or
        not off.get('DHCSR',0)&0x20000 or off.get('SD',0x40)&0x40 or
        off.get('BDTR',0xC000)&0xC000 or off.get('CCER',1)):
        raise ValueError('B828 image/B/boot/private/output mismatch')
    base.BASE=capture; base.BASE_SHA=BASE_SHA; base.EXPECT_META=meta
    base.BASE_RESTORE_RECEIPT=RESTORE.resolve()


def extra_readout(board,row,*,run_reject_stop=True):
    # All bulk observation only after the original runner proves output OFF.
    for key,cmd in (('no_travel_geometry','MOTOR TEST IDENT GEOMETRY'),
                    ('current_reject_reply','MOTOR TEST IDENT REJECT'),
                    ('timing_failure_reply','MOTOR TEST IDENT TIMING'),
                    ('timing_context_reply','MOTOR TEST IDENT TIMING CONTEXT'),
                    ('rs_gap_reply','MOTOR TEST IDENT RS GAPS'),
                    ('time_policy_reply','MOTOR TEST IDENT TIME POLICY')):
        line=board.command(cmd);row[key]=line;row['ident_replies'].append(line)
    wire=base.hw.fields(row['current_reject_reply'])
    if (wire.get('REJECT_MAX')!='0' or wire.get('TOTAL_STOP')!='0' or
        wire.get('RUN_LIMIT')!=('3' if run_reject_stop else '0') or
        (not run_reject_stop and (wire.get('RUN_STOP')!='0' or wire.get('RUN_SAT')!='255')) or
        base.hw.fields(row['no_travel_geometry']).get('TRAVEL_EXIT')!='OFF'):
        raise ValueError('Explicit Rs reject-only / continuous-stop policy mismatch')
    if wire.get('FIRST')=='1':
        line=board.command('MOTOR TEST IDENT REJECT ROW');row['first_reject_reply']=line
        row['ident_replies'].append(line)
    row['time_policy_post']=previous.policy(row['time_policy_reply'])


def extra_decode(row,ram,offset,*,total_gap_stop=True,run_reject_stop=True):
    previous.extra_decode(row,ram,offset,total_reject_stop=False,total_gap_stop=total_gap_stop,
                          run_reject_stop=run_reject_stop)
    # Do not confuse successful bounded acquisition with a qualified Rs fit.
    if row.get('acquisition_pass'):
        run.analysis.guard(row['ident_run'])


def install():
    run.IMAGE,run.ELF,run.SHA,run.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    run.RESTORE,run.BASE_SHA=RESTORE,BASE_SHA
    run.image=image;run.configure=configure;run.IDENT_SIZE=1740;run.motion=previous.motion
    run.EXTRA_READOUT=extra_readout;run.EXTRA_DECODE=extra_decode


def main():
    install()
    return run.main()


if __name__=='__main__':raise SystemExit(main())
