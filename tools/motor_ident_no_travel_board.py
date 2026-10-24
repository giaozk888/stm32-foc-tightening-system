"""Pinned no-travel-exit RS50 only; explicit OFF/ON/OFF, no automatic retry."""
import json
from pathlib import Path
import motor_ident_reject_board as reject

run=reject.run; base=run.base; TMP=run.TMP
RESTORE=TMP/'motor-ident-rs50-restore-1792498009113579300.json'
BASE_SHA='94813bd8ffa0a748dcfbcac2c6684880a8e96011a9fbe625545f3767801a0d91'
IMAGE=base.old.ROOT/'foc2_app_a/build/MotorParameterIdentificationNoTravelDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='dedb650aa982ab0b565141e02ec311f6891e6d53a4644c476237268a87e9c8c0'
ELF_SHA='3878b129ca61a51e60d3b67c3f15ffb3fc9602be41de29812cc881d28fc5c250'


def image():
    # Reuse the full independent ABI/protection checks, without changing old pins.
    from unittest.mock import patch
    with patch.multiple(reject,IMAGE=IMAGE,ELF=ELF,SHA=SHA,ELF_SHA=ELF_SHA):
        data=reject.image()
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
             if c['file'].endswith('/Core/Src/main.c'))
    if '-DMID_TRAVEL_EXIT_ENABLE=0' not in cmd or b'TRAVEL_EXIT=OFF' not in data:
        raise ValueError('Exact no-travel-exit diagnostic required')
    return data


def configure():
    run.ORIGINAL_CONFIGURE(base.ROOT_RESTORE); root=base.baseline()
    r=json.loads(RESTORE.read_text('utf-8')); capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or
        r.get('image_sha256')!=reject.SHA or r.get('motor_commands')!=0 or
        any(r.get(k) is not True for k in ('pass_','all_app_private_unchanged',
            'b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Exact preserved B812 restore receipt required')
    raw=capture.read_bytes(); meta=base.old.zero.latest_meta(raw); off=r.get('outputs',{})
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=BASE_SHA or r.get('final_sha256')!=BASE_SHA or
        list(meta)!=r.get('metadata') or meta[2:10]!=(2,0,0,812,213580,2523570381,227964,627317606) or
        base.old.zero.digest(raw[0x8000:0x8000+213580])!=r['image_sha256'] or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or off.get('VTOR')!=0x08040000 or
        not off.get('DHCSR',0)&0x20000 or off.get('SD',0x40)&0x40 or
        off.get('BDTR',0xC000)&0xC000 or off.get('CCER',1)):
        raise ValueError('B812 image/B/boot/private/output mismatch')
    base.BASE=capture; base.BASE_SHA=BASE_SHA; base.EXPECT_META=meta
    base.BASE_RESTORE_RECEIPT=RESTORE.resolve()


def extra_readout(board,row):
    geometry=board.command('MOTOR TEST IDENT GEOMETRY')
    row['no_travel_geometry']=geometry; row['ident_replies'].append(geometry)
    if base.hw.fields(geometry).get('TRAVEL_EXIT')!='OFF':
        raise RuntimeError('No-travel-exit firmware readout mismatch')
    reject.extra_readout(board,row)


def install():
    run.IMAGE,run.ELF,run.SHA,run.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    run.RESTORE,run.BASE_SHA=RESTORE,BASE_SHA
    run.image=image; run.configure=configure; run.IDENT_SIZE=1660
    run.EXTRA_READOUT=extra_readout; run.EXTRA_DECODE=reject.extra_decode


def main():
    install()
    return run.main()


if __name__=='__main__':raise SystemExit(main())
