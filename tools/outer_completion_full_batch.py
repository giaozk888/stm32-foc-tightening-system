"""Same outer-completion A: 500/600/700/800rpm x3, read-only preparation.

FILES ONLY default. Explicit fresh OFF and powered supervision gates remain.
No firmware changes, automatic retries, parameter application or DOB control.
"""
import sys
import outer_completion_board as previous
import mechanical_encoder_fix_remaining as readonly

low=previous.low
ROOT_RESTORE=low.TMP/'mechanical-ident-restore-1792673660935323300.json'
POINTS=(500,500,500,600,600,600,700,700,700,800,800,800)
ORIGINAL_SETUP=previous.setup


def staged(path,data):
    return readonly.staged(path,data,expected_sha=previous.SHA,
        expected_elf_sha=previous.ELF_SHA,points=POINTS)


def setup(path):
    ORIGINAL_SETUP(ROOT_RESTORE);low.base.baseline()
    if path.resolve()!=ROOT_RESTORE.resolve():low.base.configure_baseline(path)
    low.base.stage=readonly.verify_existing_off;low.base.staged=staged
    return previous.image()


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if '--execute-twelve' in args:args[args.index('--execute-twelve')]='--execute-six'
    if '--baseline-restore' not in args and not any(x in args for x in ('--execute-six','--restore-b-drive-off')):
        args+=['--baseline-restore',str(ROOT_RESTORE)]
    low.setup=setup;low.POINTS=POINTS;low.TRIP_RPM=1000;low.TRAVEL_DEG=30000
    low.CLOSURE_SECONDS=11.;low.LIMITS_QUERY=True
    low.LIMITS_EXTRA=dict(PLAUSIBLE_RPM='1000',REJECT_BUSY='1',OBS_AFTER_ACK='1')
    return low.main(args)


if __name__=='__main__':raise SystemExit(main())
