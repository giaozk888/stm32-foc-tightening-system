"""Original 240rpm runtime, separate OFF stage/powered single run/OFF restore.

Only bridges the exact newly restored B920 to the old validated runtime owner.
No automatic actuation/default devices, no added diagnostic ISR or threshold.
"""
import sys
from pathlib import Path
import dq_decoupling_fsm_board as original
import dq_audit_board as audit

ROOT_RECEIPT=audit.TMP/'dq-audit-restore-1792583167104102100.json'
ROOT_SHA='2d3bc6f2565c19db748c560af104df14e2eea28d59cc79f15d47cfc9c4144577'
CONFIGURE=original.configure


def configure(path):
    path=path.resolve()
    if path==ROOT_RECEIPT.resolve():
        # Validate the full actual stopped audit/B920 receipt, not a renamed
        # old-image receipt. Includes original B/boot/private root comparison.
        audit.configure(path)
        base=original.base
        if base.BASE_SHA!=ROOT_SHA or base.EXPECT_META[5]!=920:
            raise ValueError('Exact B920 return from diagnostic run required')
        base.IMAGE=original.IMAGE;base.ELF=original.ELF
        base.SHA=original.SHA;base.ELF_SHA=original.ELF_SHA;base.image=original.image
        base.FRICTION_A=.105;base.motion=original.motion;base.decode_cm=original.decode
    else:
        CONFIGURE(path)  # Original same-runtime successful B restoration checks.
    # Tokenized logs still decoded; no additional alternating DQ UART queries.
    original.base.TokenRecordedBoard=original.ORIGINAL_BOARD


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    original.IMAGE=original.base.old.ROOT/'foc2_app_a/build/DqOriginalRuntime/foc2.bin'
    original.ELF=original.IMAGE.with_suffix('.elf')
    original.configure=configure
    if '--baseline-restore' not in args and not any(x in args for x in ('--execute-powered','--restore-b-drive-off')):
        args+=['--baseline-restore',str(ROOT_RECEIPT)]
    return original.main(args)


if __name__=='__main__':raise SystemExit(main())
