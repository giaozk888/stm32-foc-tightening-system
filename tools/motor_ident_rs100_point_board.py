"""Pinned unchanged identification A, one manual Rs100 point, OFF/ON/OFF."""
import motor_ident_rs75_board as previous

run=previous.run;base=run.base;TMP=run.TMP
IMAGE,ELF,SHA,ELF_SHA=previous.IMAGE,previous.ELF,previous.SHA,previous.ELF_SHA
RESTORE=TMP/'motor-ident-rs75-restore-1792556906074918500.json'
BASE_SHA='4343610e6a7f8844ce06ed2872cc5e1a1304e22c6ce395ce9c264aead22d97d0'
image=previous.image


def configure():
    previous.configure_from(RESTORE,BASE_SHA,852)


def extra_decode(row,ram,offset):
    previous.previous.extra_decode(row,ram,offset)
    if abs(row['ident_ram']['current_a']-.1)>1e-6:
        row['acquisition_pass']=False
        raise ValueError('Same-session Rs100 current reference not proven')


def install():
    previous.install()
    run.RESTORE,run.BASE_SHA=RESTORE,BASE_SHA
    run.configure=configure;run.RS_MA=100
    run.COMMAND='MOTOR TEST IDENT RS 100 LOCKED CONFIRM'
    run.EXTRA_DECODE=extra_decode


def main():
    install()
    return run.main()


if __name__=='__main__':raise SystemExit(main())
