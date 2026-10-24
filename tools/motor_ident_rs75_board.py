"""Pinned unchanged identification A, one manual Rs75 point, OFF/ON/OFF."""
import json
from pathlib import Path
import motor_ident_rs_reject_count_board as previous

run=previous.run;base=run.base;TMP=run.TMP
IMAGE,ELF,SHA,ELF_SHA=previous.IMAGE,previous.ELF,previous.SHA,previous.ELF_SHA
RESTORE=TMP/'motor-ident-rs50-restore-1792556545056346300.json'
BASE_SHA='233c938c8f2e7a53418359d6f31049cd0f6a833f233fc28329b629d8d04c6710'
image=previous.image


def configure_from(restore,base_sha,generation):
    run.ORIGINAL_CONFIGURE(base.ROOT_RESTORE);root=base.baseline()
    r=json.loads(restore.read_text('utf-8'));capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or
        r.get('image_sha256')!=SHA or r.get('motor_commands')!=0 or
        any(r.get(k) is not True for k in ('pass_','all_app_private_unchanged',
            'b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Exact preserved B%d restore receipt required'%generation)
    raw=capture.read_bytes();meta=base.old.zero.latest_meta(raw);off=r.get('outputs',{})
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=base_sha or r.get('final_sha256')!=base_sha or
        list(meta)!=r.get('metadata') or meta[2:10]!=(2,0,0,generation,215132,3383293039,227964,627317606) or
        raw[0x8000:0x8000+len(image())]!=image() or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or off.get('VTOR')!=0x08040000 or
        not off.get('DHCSR',0)&0x20000 or off.get('SD',0x40)&0x40 or
        off.get('BDTR',0xC000)&0xC000 or off.get('CCER',1)):
        raise ValueError('B%d image/B/boot/private/output mismatch'%generation)
    base.BASE=capture;base.BASE_SHA=base_sha;base.EXPECT_META=meta
    base.BASE_RESTORE_RECEIPT=restore.resolve()


def configure():
    configure_from(RESTORE,BASE_SHA,848)


def extra_decode(row,ram,offset):
    previous.extra_decode(row,ram,offset)
    if abs(row['ident_ram']['current_a']-.075)>1e-6:
        row['acquisition_pass']=False
        raise ValueError('Same-session Rs75 current reference not proven')


def install():
    previous.install()
    run.RESTORE,run.BASE_SHA=RESTORE,BASE_SHA
    run.configure=configure;run.RS_MA=75
    run.COMMAND='MOTOR TEST IDENT RS 75 LOCKED CONFIRM'
    run.EXTRA_DECODE=extra_decode


def main():
    install()
    return run.main()


if __name__=='__main__':raise SystemExit(main())
