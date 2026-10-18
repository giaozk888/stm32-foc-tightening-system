"""Offline build/test receipt. No serial, debugger, Flash or network access.

Run from any directory: python tools/verify_foc_timeout_diagnostics.py
Generated logs/JSON are local build evidence, not board-test evidence.
"""
import hashlib
import json
import re
import subprocess
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tests/foc_adaptive_build/timeout_diagnostics_evidence'
ARM = Path('D:/software/arm/bin')
BASELINE = {
    'a/FastCurrentReject': (226884, 125728),
    'b/FastCurrentReject': (225852, 125712),
    'a/FastCurrentRejectComputeOnly': (225068, 125560),
    'b/FastCurrentRejectComputeOnly': (224020, 125544),
}


def run(name, args, cwd=ROOT):
    command=args if isinstance(args,str) else [str(x) for x in args]
    p = subprocess.run(command, cwd=cwd, capture_output=True,
                       text=True, encoding='utf-8', errors='replace', timeout=300)
    log = p.stdout + p.stderr
    (OUT / (name + '.log')).write_text(log, encoding='utf-8')
    print(name, 'PASS' if p.returncode == 0 else 'FAIL', flush=True)
    if p.returncode:
        raise RuntimeError(log[-10000:])
    return log


def main():
    global OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--incremental',action='store_true',help='Reuse prior clean build objects')
    parser.add_argument('--output',type=Path,help='Separate offline receipt/log directory')
    options=parser.parse_args()
    if options.output is not None: OUT=options.output.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    receipt = {'scope': 'OFFLINE_ONLY_NO_HARDWARE', 'builds': [], 'tests': []}
    for slot, preset in [('main', 'Debug')] + [
            (s, p) for s in 'ab' for p in ('FastCurrentReject', 'FastCurrentRejectComputeOnly')]:
        source = ROOT / ('foc2' if slot == 'main' else 'foc2_app_' + slot)
        name = slot + '-' + preset
        args=['cmake', '--build', '--preset', preset, '-j4']
        if not options.incremental: args.append('--clean-first')
        log = run(name, args, source)
        build = source / 'build' / preset
        commands=json.loads((build/'compile_commands.json').read_text('utf-8'))
        syntax=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
        syntax=re.sub(r' -o \S+ -c ', ' -fsyntax-only ',syntax)
        warnings=run(name+'-main-warnings',syntax,build)
        image = build / 'foc2.bin'
        if slot == 'main':
            image = OUT/'main-Debug.bin'
            run(name+'-bin', [ARM/'arm-none-eabi-objcopy.exe', '-O', 'binary',
                             build/'foc2.elf', image])
        binary = image.read_bytes()
        sizes = run(name + '-sections', [ARM/'arm-none-eabi-size.exe', '-A', build/'foc2.elf'])
        sections = {s: int(n) for s, n in re.findall(r'^([.\w]+)\s+(\d+)\s+\d+', sizes, re.M)}
        ram = sum(sections.get(s, 0) for s in ('.data', '.tdata', '.tbss', '.bss', '._user_heap_stack'))
        row = {'slot': slot, 'preset': preset, 'flash_bytes': len(binary), 'ram_bytes': ram,
               'sha256': hashlib.sha256(binary).hexdigest(),
               'warnings': sorted(set(re.findall(r'warning: (.*)', log+warnings)))}
        if slot != 'main':
            bf, br = BASELINE[slot + '/' + preset]
            row.update(flash_delta_bytes=len(binary)-bf, ram_delta_bytes=ram-br,
                       flash_remaining_bytes=224*1024-len(binary))
            assert len(binary) <= 224*1024 and ram <= 131008, row
            assert b'FAULT SNAPSHOT TIMEOUT_SUBREASON=' in binary, row
        receipt['builds'].append(row)
    # Existing pure host cases and current ARM-linked image checks only.
    for module in ('test_foc_cur_confirm_cycles', 'test_foc_timeout_diagnostics', 'test_foc_fast_current_reject',
                   'test_current_protection_layers', 'test_filtered_protection_candidate',
                   'test_protection_selftest', 'test_protected_closed_loop'):
        log = run(module, [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests',
                           '-p', module + '.py', '-v'])
        match = re.search(r'Ran (\d+) tests?', log)
        receipt['tests'].append({'module': module, 'count': int(match[1]) if match else 0,
                                 'passed': True})
    receipt['snapshot_bytes'] = 204
    receipt['discriminator_sha256'] = hashlib.sha256(
        (ROOT/'firmware_common/foc_current_fast_reject.h').read_bytes()).hexdigest()
    receipt['hardware_test_performed'] = False
    run('owned-source-audit',['rg','-n','-i',
        r'timeout|elapsed|deadline|stall|rundown|stop|settle|contact|watchdog',
        'foc2/Core/Src/main.c','foc2_app_a/Core/Src','foc2_app_a/Core/Inc',
        'foc2_app_b/Core/Src','foc2_app_b/Core/Inc','firmware_common',
        '-g','*.c','-g','*.h','-g','*.inc','-g','*.cpp','-g','*.cc'])
    (OUT/'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
