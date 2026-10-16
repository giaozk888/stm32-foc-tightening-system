"""Offline saved-data replay only. No serial, programmer, reset or actuation."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
GCC = r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'
EXE = ROOT / 'tests/foc_current_zero_build/feedback_saved_replay.exe'
EXE_2X = ROOT / 'tests/foc_current_zero_build/feedback_saved_replay_2x.exe'

def compile_kernel(exe=EXE, repair_budget=(3,2)):
    if (len(repair_budget)!=2 or any(type(x) is not int or not 1<=x<=32 for x in repair_budget)):
        raise ValueError('Bounded integer repair budget required')
    exe.parent.mkdir(exist_ok=True)
    subprocess.run([GCC, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-DFOC_PROTECTION_HOST_TEST=1', '-DFOC_CURRENT_TREND4=1',
                    '-DFOC_CURRENT_SPIKE_ONLY=1', '-I', str(ROOT / 'firmware_common'),
                    '-DFOC_REPLAY_WINDOW_MAX='+str(repair_budget[0]),
                    '-DFOC_REPLAY_STREAK_MAX='+str(repair_budget[1]),
                    str(ROOT / 'tests/foc_feedback_saved_replay.c'), '-o', str(exe)], check=True)

def replay(samples, zero, exe=EXE):
    if (not isinstance(samples, list) or not 4 <= len(samples) <= 1000000 or
            len(zero) != 2 or any(type(x) is not int or not 0 <= x <= 4095 for x in zero) or
            any(not isinstance(pair, (list, tuple)) or len(pair) != 2 or
                any(type(x) is not int or not 0 <= x <= 4095 for x in pair) for pair in samples)):
        raise ValueError('Complete bounded 12-bit integer pairs and two zeros required')
    p = subprocess.run([str(exe), *map(str, zero)],
                       input=''.join(f'{u} {v}\n' for u, v in samples),
                       text=True, capture_output=True, check=True)
    result = json.loads(p.stdout)
    result.update(zero=list(zero), soft_limit_A=4,
                  gain_assumed_mV_per_A=120, reference_assumed_mV=3300,
                  timestamps='SYNTHETIC_50_US', angle='SYNTHETIC_ZERO',
                  acquisition_timing_verified=False, electrical_accuracy_verified=False)
    return result

def saved_capture(path, exe=EXE):
    raw = Path(path).read_bytes()
    capture = json.loads(raw)
    if capture.get('mode') not in ('OUTPUT_OFF', 'SD_LOW_PWM_SIGNALS'):
        raise ValueError('Only identified power-OFF historical captures admitted')
    if capture.get('bridge_enabled') is not False or capture.get('motion_commands') is not False:
        raise ValueError('Historical power/command scope not explicit')
    line = capture.get('capture_line', '')
    def field(name):
        hits = re.findall(r'(?:^|\s)'+re.escape(name)+r'=([^\s]+)', line)
        if len(hits) != 1: raise ValueError('Missing/duplicate capture field '+name)
        return hits[0]
    samples = capture['samples']
    if int(field('N')) != len(samples) or field('SD') != '0':
        raise ValueError('Incomplete capture or SD not OFF')
    zero = list(map(int, field('ZERO').split(',')))
    result = replay(samples, zero, exe)
    result.update(capture_file_sha256=hashlib.sha256(raw).hexdigest(),
                  capture_mode=capture['mode'], historical=True,
                  # The old pass_ field applies to old qualifications, not this replay.
                  original_acceptance_pass=capture.get('pass_'))
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('captures', nargs='+', type=Path)
    parser.add_argument('--doubled-repair-budget',action='store_true')
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    exe=EXE_2X if args.doubled_repair_budget else EXE
    compile_kernel(exe,(6,4) if args.doubled_repair_budget else (3,2))
    report=json.dumps([saved_capture(p,exe) for p in args.captures],ensure_ascii=False,indent=2)
    if args.output:
        destination=args.output.resolve()
        if not destination.is_relative_to(ROOT) or destination.exists():
            raise ValueError('New workspace evidence file only; preserve previous results')
        destination.write_text(report+'\n',encoding='utf-8')
    print(report)

if __name__ == '__main__': main()
