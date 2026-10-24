"""Pinned bounded-reject RS50 repeat only; explicit OFF/ON/OFF, no auto retry."""
import json
from pathlib import Path
import struct
import motor_identification_board as run

base=run.base;TMP=run.TMP
RESTORE=TMP/'motor-ident-rs50-restore-1792496559180754300.json'
BASE_SHA='f13fb3154b9e7863fa3d838bbf73f3f578fc6455bbf3ef4d473bc66f58b8f859'
IMAGE=base.old.ROOT/'foc2_app_a/build/MotorParameterIdentificationRejectDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='04cc4387e53614432c0671f6e7106763e5040789cbd6d8c6b6259606d6c41a6d'
ELF_SHA='4bc20b2393e1c23912930aaa4ca6b6a115e04771846ad9058c72b08eb401e09e'


def image():
    data=IMAGE.read_bytes()
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
        if c['file'].endswith('/Core/Src/main.c'))
    base.support.support.require_baud(cmd)
    if (len(data)!=213580 or base.old.zero.digest(data)!=SHA or
        base.old.zero.digest(ELF.read_bytes())!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        base.symbols(ELF).get('motor_ident',(0,0))[1]!=1660 or
        any(k not in cmd for k in ('-DFOC_MOTOR_IDENTIFICATION_DIAG=1',
          '-DFOC_IDENT_CURRENT_REJECT_ENABLE=1','-DFOC_PWM_PIPELINE_CLOSED_LOOP=1',
          '-DSPEED_FRICTION_I_A=0.105f')) or
        any(k in cmd for k in ('-DFOC_FRICTION_CALIBRATION_DIAG','-DFOC_TORQUE_CHAIN_DIAG')) or
        b'MOTOR_IDENT_DIAGNOSTIC: LOCK ROTOR; manual one-shot; no START' not in data or
        b'REJECT_MAX=16 RUN_LIMIT=3' not in data or b'TRIP_MA=4000' not in data):
        raise ValueError('Exact offline-tested bounded-reject A BIN/ELF/ABI required')
    return data


def configure():
    run.ORIGINAL_CONFIGURE(base.ROOT_RESTORE);root=base.baseline()
    r=json.loads(RESTORE.read_text('utf-8'));capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or
        r.get('image_sha256')!='15511c9bd4c3bb579773928bb70a2ffc5e08250b6ddf899bbfda6c10a3d81e4d' or
        r.get('motor_commands')!=0 or any(r.get(k) is not True for k in
            ('pass_','all_app_private_unchanged','b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Exact preserved B808 restore receipt required')
    raw=capture.read_bytes();meta=base.old.zero.latest_meta(raw);off=r.get('outputs',{})
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=BASE_SHA or r.get('final_sha256')!=BASE_SHA or
        list(meta)!=r.get('metadata') or meta[2:10]!=(2,0,0,808,212732,1150164752,227964,627317606) or
        base.old.zero.digest(raw[0x8000:0x8000+212732])!=r['image_sha256'] or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or off.get('VTOR')!=0x08040000 or
        not off.get('DHCSR',0)&0x20000 or off.get('SD',0x40)&0x40 or
        off.get('BDTR',0xC000)&0xC000 or off.get('CCER',1)):
        raise ValueError('B808 image/B/boot/private/output mismatch')
    base.BASE=capture;base.BASE_SHA=BASE_SHA;base.EXPECT_META=meta;base.BASE_RESTORE_RECEIPT=RESTORE.resolve()


def extra_readout(board,row):
    row['current_reject_reply']=board.command('MOTOR TEST IDENT REJECT')
    stats=base.hw.fields(row['current_reject_reply'])
    if stats.get('REJECT_MAX')!='16' or stats.get('RUN_LIMIT')!='3':
        raise RuntimeError('Bounded current admission revision mismatch')
    row['ident_replies'].append(row['current_reject_reply'])
    if stats.get('FIRST')=='1':
        first=board.command('MOTOR TEST IDENT REJECT ROW')
        row['first_reject_reply']=first;row['ident_replies'].append(first)


def extra_decode(row,ram,offset,*,total_reject_stop=True,run_reject_stop=True):
    # Existing 1596-byte prefix retained; new 64-byte extension is explicit.
    keys='us seq pending_before id_ref iq_ref id iq vd vq angle speed mode status reason reserved'.split()
    frame=dict(zip(keys,struct.unpack_from('<3I8f4B',ram,offset+1596)))
    values=struct.unpack_from('<2I2H4B',ram,offset+1596+48)
    stats=dict(zip(('reject','good','raw_u','raw_v','run','max_run','sample_rejected','first_valid'),values))
    row['current_admission_ram']=stats
    row['first_current_reject']=dict(frame,raw_u=stats['raw_u'],raw_v=stats['raw_v'],
        voltage_semantics='Previous calculated Vdq before this frame PI/STOP, not phase voltage') if stats['first_valid'] else None
    row['ident_run']['current_admission']=dict(REJECT=stats['reject'],GOOD=stats['good'],
        MAX_RUN=stats['max_run'],REJECT_MAX=16,RUN_LIMIT=3)
    if not total_reject_stop:
        row['ident_run']['current_admission'].update(REJECT_MAX=0,TOTAL_STOP=0)
    if not run_reject_stop:
        if total_reject_stop:raise ValueError('Count-only Rs requires total-stop disabled')
        row['ident_run']['current_admission'].update(RUN_LIMIT=0,RUN_STOP=0,RUN_SAT=255)
    row['ident_run']['first_current_reject']=row['first_current_reject']
    if row.get('acquisition_pass') and ((total_reject_stop and stats['reject']>16) or
                                      (run_reject_stop and stats['max_run']>=3)):
        row['acquisition_pass']=False
    wire=base.hw.fields(row.get('current_reject_reply',''))
    if not total_reject_stop and (wire.get('TOTAL_STOP')!='0' or wire.get('REJECT_MAX')!='0' or
                                 wire.get('RUN_LIMIT')!=('3' if run_reject_stop else '0')):
        raise ValueError('Explicit Rs total-stop-disabled admission required')
    if not run_reject_stop and (wire.get('RUN_STOP')!='0' or wire.get('RUN_SAT')!='255'):
        raise ValueError('Explicit Rs run-stop-disabled saturated statistics required')
    if wire and any(wire.get(k)!=str(stats[v]) for k,v in
        (('REJECT','reject'),('GOOD','good'),('MAX_RUN','max_run'),('FIRST','first_valid'))):
        raise ValueError('Frozen UART/RAM admission mismatch')


def install():
    run.IMAGE,run.ELF,run.SHA,run.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    run.RESTORE,run.BASE_SHA=RESTORE,BASE_SHA
    run.image=image;run.configure=configure;run.IDENT_SIZE=1660
    run.EXTRA_READOUT=extra_readout;run.EXTRA_DECODE=extra_decode


def main():
    install()
    return run.main()


if __name__=='__main__':raise SystemExit(main())
