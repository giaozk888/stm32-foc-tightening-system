"""Pinned Rs-only gap-admission RS50; OFF/ON/OFF, no retry or next stage."""
import json
from pathlib import Path
import struct
import motor_ident_timing_board as previous

run=previous.run; base=run.base; TMP=run.TMP
RESTORE=TMP/'motor-ident-rs50-restore-1792499463782223100.json'
BASE_SHA='a886ee7cdad8cb2d60254e02a30bdf8ec9d5579f39022a7a75aff0c88950c097'
IMAGE=base.old.ROOT/'foc2_app_a/build/MotorParameterIdentificationRsGapDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='9f0bf902af96699fde1d817b486588a228b71e830a291ffb49cf5f015f220676'
ELF_SHA='5f1fb840e744ed20a6935183902d902405e7266498384ef7a667b28e741e3e2a'


def image():
    data=IMAGE.read_bytes()
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
             if c['file'].endswith('/Core/Src/main.c'))
    base.support.support.require_baud(cmd)
    if (len(data)!=214452 or base.old.zero.digest(data)!=SHA or
        base.old.zero.digest(ELF.read_bytes())!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        base.symbols(ELF).get('motor_ident',(0,0))[1]!=1740 or
        any(k not in cmd for k in ('-DFOC_MOTOR_IDENTIFICATION_DIAG=1',
          '-DFOC_IDENT_CURRENT_REJECT_ENABLE=1','-DFOC_IDENT_TIMING_TRACE_ENABLE=1',
          '-DFOC_IDENT_RS_GAP_ADMISSION_ENABLE=1','-DMID_TRAVEL_EXIT_ENABLE=0',
          '-DFOC_PWM_PIPELINE_CLOSED_LOOP=1','-DSPEED_FRICTION_I_A=0.105f')) or
        any(k in cmd for k in ('-DFOC_FRICTION_CALIBRATION_DIAG','-DFOC_TORQUE_CHAIN_DIAG')) or
        any(k not in data for k in (b'MOTOR_IDENT_DIAGNOSTIC: LOCK ROTOR; manual one-shot; no START',
            b'TRAVEL_EXIT=OFF',b'REJECT_MAX=16 RUN_LIMIT=3',b'TRIP_MA=4000',b'OK MID RS_GAPS='))):
        raise ValueError('Exact offline-tested Rs-gap A BIN/ELF/1740 ABI required')
    return data


def configure():
    run.ORIGINAL_CONFIGURE(base.ROOT_RESTORE); root=base.baseline()
    r=json.loads(RESTORE.read_text('utf-8')); capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or
        r.get('image_sha256')!=previous.SHA or r.get('motor_commands')!=0 or
        any(r.get(k) is not True for k in ('pass_','all_app_private_unchanged',
            'b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Exact preserved B820 restore receipt required')
    raw=capture.read_bytes(); meta=base.old.zero.latest_meta(raw); off=r.get('outputs',{})
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=BASE_SHA or r.get('final_sha256')!=BASE_SHA or
        list(meta)!=r.get('metadata') or meta[2:10]!=(2,0,0,820,214156,241545312,227964,627317606) or
        base.old.zero.digest(raw[0x8000:0x8000+214156])!=r['image_sha256'] or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or off.get('VTOR')!=0x08040000 or
        not off.get('DHCSR',0)&0x20000 or off.get('SD',0x40)&0x40 or
        off.get('BDTR',0xC000)&0xC000 or off.get('CCER',1)):
        raise ValueError('B820 image/B/boot/private/output mismatch')
    base.BASE=capture; base.BASE_SHA=BASE_SHA; base.EXPECT_META=meta
    base.BASE_RESTORE_RECEIPT=RESTORE.resolve()


def extra_readout(board,row):
    previous.extra_readout(board,row)
    line=board.command('MOTOR TEST IDENT RS GAPS');row['rs_gap_reply']=line
    row['ident_replies'].append(line);wire=base.hw.fields(line)
    if wire.get('BUDGET')!='16' or wire.get('RUN_LIMIT')!='2':
        raise RuntimeError('Rs gap budget revision mismatch')


def extra_decode(row,ram,offset,*,max_dt_us=55,total_reject_stop=True,total_gap_stop=True,run_reject_stop=True):
    previous.extra_decode(row,ram,offset,max_dt_us=max_dt_us,total_reject_stop=total_reject_stop,
                          run_reject_stop=run_reject_stop)
    values=struct.unpack_from('<4I',ram,offset+1724)
    stats=dict(zip(('hold_delta','events','skipped','max_skipped'),values));row['rs_gap_ram']=stats
    wire=base.hw.fields(row.get('rs_gap_reply',''))
    if (wire.get('BUDGET')!=('16' if total_gap_stop else '0') or wire.get('RUN_LIMIT')!='2' or
        wire.get('TOTAL_STOP','1')!=('1' if total_gap_stop else '0') or
        any(wire.get(k)!=str(stats[v]) for k,v in
            (('RS_GAPS','events'),('SKIPPED','skipped'),('MAX_GAP','max_skipped')))):
        raise ValueError('Frozen UART/RAM Rs gap mismatch')
    gaps=dict(RS_GAPS=stats['events'],SKIPPED=stats['skipped'],MAX_GAP=stats['max_skipped'],
              BUDGET=16 if total_gap_stop else 0,RUN_LIMIT=2)
    if not total_gap_stop:gaps['TOTAL_STOP']=0
    row['ident_run']['rs_gap_admission']=gaps
    if not (stats['events']<=stats['skipped']<=2*stats['events'] and
            stats['skipped']<=(16 if total_gap_stop else 8000) and
            0<=stats['max_skipped']<=2 and (stats['skipped']==0)==(stats['max_skipped']==0)):
        raise ValueError('Invalid frozen Rs gap counters')


def install():
    run.IMAGE,run.ELF,run.SHA,run.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    run.RESTORE,run.BASE_SHA=RESTORE,BASE_SHA
    run.image=image;run.configure=configure;run.IDENT_SIZE=1740
    run.EXTRA_READOUT=extra_readout;run.EXTRA_DECODE=extra_decode


def main():
    install()
    return run.main()


if __name__=='__main__':raise SystemExit(main())
