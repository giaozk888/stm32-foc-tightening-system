"""Health-expectation fix builds/tests only; preserve all board evidence images."""
import json
import os
import re
import sys
import time
import encoder_foc_first_offline as previous

prior = previous.prior
ROOT = previous.ROOT
OUT = ROOT/'tests/foc_adaptive_build/encoder_health_evidence'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    prior.OUT = OUT
    builds = []
    for app, profile in previous.MATRIX:
        name = app+'-'+profile
        build = ROOT/app/'build/EncoderHealthReview'/profile
        preset = profile.removesuffix('Light')
        flags = ['-DFOC_HEAVY_PROFILE_ENABLE=OFF'] if profile.endswith('Light') else []
        print('BUILD '+name, flush=True)
        prior.run(['cmake','--preset',preset,'-B',build,*flags], ROOT/app, OUT/(name+'-configure.log'))
        log = prior.run(['cmake','--build',build,'-j','8'], ROOT/app, OUT/(name+'-build.log'))
        elf = build/'foc2.elf'
        image = elf.with_suffix('.bin')
        builds.append(dict(app=app, profile=profile, build_dir=str(build),
            bin_sha256=prior.digest(image) if image.exists() else None,
            elf_sha256=prior.digest(elf), memory=prior.memory_from_elf(build,elf,name),
            warnings=sorted(set(re.findall(r'warning: (.*)',log)))))
    historic = json.loads((previous.OUT/'receipt.json').read_text('utf-8'))
    legacy_verified = 0
    for row in builds:
        if not row['bin_sha256'] or row['profile'].startswith('EncoderFocFirst'):
            continue
        old = next(b for b in historic['builds'] if
                   (b['app'],b['profile']) == (row['app'],row['profile']))
        if row['bin_sha256'] != old['bin_sha256']:
            raise RuntimeError('Unexpected historic profile binary change: '+str(row))
        legacy_verified += 1
    tests = []
    # Only this child workflow selects new build paths. Historic runner image
    # pins and receipts keep referring to the previous, untouched directories.
    os.environ['FOC_ENCODER_REVIEW_DIR'] = 'EncoderHealthReview'
    for module in prior.TESTS + ['test_foc_deadline_attribution','test_encoder_foc_first',
                                'test_deadline_attribution_board_test',
                                'test_encoder_foc_first_board_test']:
        print('TEST '+module, flush=True)
        log = prior.run([sys.executable,'-m','unittest','discover','-s','tests',
                         '-p',module+'.py','-v'], ROOT, OUT/(module+'.log'))
        tests.append(dict(module=module, passed=int(re.search(r'Ran (\d+) tests?',log)[1])))
    receipt = dict(offline_only=True, hardware_access=False, boot_selection_changed=False,
        motor_started=False, created_unix=time.time(), builds=builds, tests=tests,
        test_count=sum(t['passed'] for t in tests),
        legacy_bin_unchanged_count=legacy_verified)
    path = OUT/'receipt.json'
    path.write_text(json.dumps(receipt,indent=2)+'\n', encoding='utf-8')
    print(f'PASS: {len(builds)} builds; {receipt["test_count"]} tests; '+str(path), flush=True)


if __name__ == '__main__': main()
