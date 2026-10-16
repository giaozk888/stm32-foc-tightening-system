"""Replay exact saved OFF pairs through actual C filters. No hardware access."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from switch_feedback_off_capture import analyze
SOURCE = ROOT/'safety_backups/switch-feedback-20261012/off-repaired-a-1791801336398511500.json'
C = ROOT/'tests/foc_filter_saved_replay.c'
EXE = ROOT/'tests/foc_current_zero_build/saved_switch_filter_compare.exe'

def compare():
    data = SOURCE.read_bytes()
    evidence = json.loads(data)
    if (evidence.get('pass_') is not True or evidence.get('mode') != 'OUTPUT_OFF' or
            evidence.get('bridge_enabled') is not False or evidence.get('pwm_enabled') is not False):
        raise RuntimeError('Exact saved output-OFF capture required')
    samples = evidence['samples']
    analysis = analyze(samples, evidence['capture'])  # checks actual ISR raw/median totals
    if analysis['sample_pairs'] != 3600:
        raise RuntimeError('Wrong complete source capture')
    EXE.parent.mkdir(exist_ok=True)
    subprocess.run([r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe', '-std=c11', '-O2',
                    '-Wall', '-Wextra', '-Werror', '-pedantic', '-DFOC_PROTECTION_HOST_TEST=1',
                    '-I', str(ROOT/'firmware_common'), str(C), '-o', str(EXE)], check=True)
    p = subprocess.run([str(EXE)], input=''.join(f'{u} {v}\n' for u,v in samples),
                       capture_output=True, text=True, check=True)
    result = json.loads(p.stdout)
    if any(result[key]['pairs'] != 3597 for key in ('raw','median3','trend4')):
        raise RuntimeError('Unaligned filter comparison')
    result.update(source=str(SOURCE), source_sha256=hashlib.sha256(data).hexdigest(),
                  source_capture_generation=423, reference_adc_counts=[1560,1560],
                  reference_is_nominal_not_new_calibration=True,
                  conversion_is_configured_not_measured=True,
                  replay_only=True, new_acquisition=False)
    return result

if __name__ == '__main__':
    print(json.dumps(compare(), ensure_ascii=False, indent=2))
