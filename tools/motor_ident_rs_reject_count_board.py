"""Pinned Rs current rejects count-only; one supervised Rs50, OFF/ON/OFF."""
import json
from pathlib import Path
import motor_ident_rs_gap_count_board as previous

run=previous.run;base=run.base;TMP=run.TMP
RESTORE=TMP/'motor-ident-rs50-restore-1792555800665025400.json'
BASE_SHA='d8f09dfee0d9ad5b812a3f1b04863ae5488a7d6bec661b48f66e5604641b63da'
IMAGE=base.old.ROOT/'foc2_app_a/build/MotorParameterIdentificationRsRejectCountDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='19021c8c5e784fe4325c9fb8bb81177bc2e6189e150fd5832fc3a9337c8db4af'
ELF_SHA='437dcaf5db263010313eb4b600bf60fb03d1350d804eb48655e1f140b26f6b46'


def image():
    data=previous.pinned_image(IMAGE,SHA,ELF_SHA,215132,('-DFOC_IDENT_RS_REJECT_COUNT_ONLY=1',))
    if b'RUN_STOP=%u RUN_SAT=255' not in data:raise ValueError('Explicit Rs reject count-only marker absent')
    return data


def configure():
    run.ORIGINAL_CONFIGURE(base.ROOT_RESTORE);root=base.baseline()
    r=json.loads(RESTORE.read_text('utf-8'));capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or
        r.get('image_sha256')!=previous.SHA or r.get('motor_commands')!=0 or
        any(r.get(k) is not True for k in ('pass_','all_app_private_unchanged',
            'b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Exact preserved B844 restore receipt required')
    raw=capture.read_bytes();meta=base.old.zero.latest_meta(raw);off=r.get('outputs',{})
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=BASE_SHA or r.get('final_sha256')!=BASE_SHA or
        list(meta)!=r.get('metadata') or meta[2:10]!=(2,0,0,844,215076,690845543,227964,627317606) or
        base.old.zero.digest(raw[0x8000:0x8000+215076])!=r['image_sha256'] or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or off.get('VTOR')!=0x08040000 or
        not off.get('DHCSR',0)&0x20000 or off.get('SD',0x40)&0x40 or
        off.get('BDTR',0xC000)&0xC000 or off.get('CCER',1)):
        raise ValueError('B844 image/B/boot/private/output mismatch')
    base.BASE=capture;base.BASE_SHA=BASE_SHA;base.EXPECT_META=meta
    base.BASE_RESTORE_RECEIPT=RESTORE.resolve()


def extra_readout(board,row):
    previous.extra_readout(board,row,run_reject_stop=False)


def extra_decode(row,ram,offset):
    row['encoder_terminal_saved']=previous.previous.previous.encoder_report.decode_saved(row,ELF)
    previous.reject_only.extra_decode(row,ram,offset,total_gap_stop=False,run_reject_stop=False)


def install():
    run.IMAGE,run.ELF,run.SHA,run.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    run.RESTORE,run.BASE_SHA=RESTORE,BASE_SHA
    run.image=image;run.configure=configure;run.IDENT_SIZE=1740;run.motion=previous.previous.motion
    run.EXTRA_READOUT=extra_readout;run.EXTRA_DECODE=extra_decode


def main():
    install()
    return run.main()


if __name__=='__main__':raise SystemExit(main())
