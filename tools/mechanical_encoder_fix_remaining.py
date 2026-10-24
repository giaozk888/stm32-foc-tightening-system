"""Finish 600x2,700x3,800x3 with the SAME encoder-fix A. Files-only default.

Preparation only reads the already installed image twice; never programs it.
Each point retains original preflight, single use, protections and STOP owner.
"""
import hashlib
import json
from pathlib import Path
import sys
import mechanical_encoder_fix_board as fixed

low=fixed.low
ROOT_RESTORE=low.TMP/'mechanical-ident-restore-1792672383329944900.json'
POINTS=(600,600,700,700,700,800,800,800)
ORIGINAL_SETUP=fixed.setup


def verify_existing_off(row,name,data):
    if row.get('physical_power_off') is not True:raise ValueError('Fresh drive OFF required')
    before=low.base.baseline()
    if before[0x8000:0x8000+len(data)]!=data:
        raise ValueError('Installed A differs; this read-only runner never programs firmware')
    capture=low.TMP/(name+'-existing-off.bin');second=low.TMP/(name+'-independent-off.bin')
    row['hardware_attempted']=True
    for dest in (capture,second):
        out=low.base.hw.debug(row,[*low.base.old.zero.off_gate(),
            'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected halted B baseline"}',
            *low.base.hw.full_compare_commands(dest,low.base.BASE),*low.base.hw.off_report(),'shutdown'])
        if dest.read_bytes()!=before:raise ValueError('Read-only complete Flash mismatch')
        row['outputs']=low.base.hw.check_off(out,(0x08040000,))
    row.update(pass_=True,staged_capture=str(capture),staged_sha256=hashlib.sha256(before).hexdigest(),
        independent_capture=str(second),independent_readback_pass=True,
        read_only_existing_verified_off=True,b_boot_private_metadata_unchanged=True,
        flash_programming=False,activation=False,motor_commands=0,
        final_cpu_halted=True,final_outputs_off=True)


def staged(path,data,*,expected_sha=None,expected_elf_sha=None,points=None):
    expected_sha=fixed.SHA if expected_sha is None else expected_sha
    expected_elf_sha=fixed.ELF_SHA if expected_elf_sha is None else expected_elf_sha
    points=POINTS if points is None else points
    r=json.loads(path.read_text());capture=Path(r.get('staged_capture','')).resolve()
    second=Path(r.get('independent_capture','')).resolve()
    if (path.resolve().parent!=low.TMP.resolve() or capture.parent!=low.TMP.resolve() or
        second.parent!=low.TMP.resolve() or r.get('mode')!='stage' or
        r.get('image_sha256')!=expected_sha or r.get('elf_sha256')!=expected_elf_sha or
        r.get('speeds_rpm')!=list(points) or r.get('ka_a_per_rpm_s')!=low.KA or
        r.get('overspeed_trip_rpm')!=1000 or r.get('travel_limit_deg')!=30000 or
        r.get('activation') is not False or r.get('flash_programming') is not False or
        r.get('motor_commands')!=0 or any(r.get(k) is not True for k in
            ('pass_','physical_power_off','read_only_existing_verified_off',
             'independent_readback_pass','final_outputs_off','final_cpu_halted')) or
        Path(r.get('baseline_restore_receipt','')).resolve()!=low.base.BASE_RESTORE_RECEIPT):
        raise ValueError('Exact read-only OFF point-plan readiness receipt required')
    before=low.base.baseline();raw=capture.read_bytes()
    if (raw!=before or second.read_bytes()!=raw or hashlib.sha256(raw).hexdigest()!=r.get('staged_sha256') or
        raw[0x8000:0x8000+len(data)]!=data):raise ValueError('Read-only full Flash identity mismatch')
    return capture,raw


def setup(path):
    ORIGINAL_SETUP(ROOT_RESTORE);low.base.baseline()
    if path.resolve()!=ROOT_RESTORE.resolve():low.base.configure_baseline(path)
    low.base.stage=verify_existing_off;low.base.staged=staged
    return fixed.image()


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if '--execute-eight' in args:args[args.index('--execute-eight')]='--execute-six'
    if '--baseline-restore' not in args and not any(x in args for x in ('--execute-six','--restore-b-drive-off')):
        args+=['--baseline-restore',str(ROOT_RESTORE)]
    low.setup=setup;low.POINTS=POINTS;low.TRIP_RPM=1000;low.TRAVEL_DEG=30000
    low.CLOSURE_SECONDS=11.;low.LIMITS_QUERY=True
    low.LIMITS_EXTRA=dict(PLAUSIBLE_RPM='1000',REJECT_BUSY='1')
    return low.main(args)


if __name__=='__main__':raise SystemExit(main())
