"""Offline replay of saved A460 OFF/PWM data through the B457 C guardian.

No serial/programmer access, new sampling or activation. A replay passes only
numeric sample processing; synthetic 50-us timestamps/zero angle do not prove
real bridge switching, shutdown timing, encoder alignment or motor readiness.
"""
import argparse
import hashlib
import json
from pathlib import Path

from feedback_safety_replay import compile_kernel, replay, EXE_2X
from switch_feedback_off_capture import analyze
from six_signal_acceptance import ROOT, SHA, signal_status


def validate_capture(row):
    if (row.get('pass_') is not True or row.get('mode') != 'SD_LOW_SIX_SIGNALS' or
            row.get('image_sha256') != SHA or row.get('generation') != '460' or
            row.get('bridge_enabled') is not False or row.get('final_safe_locked') is not True or
            row.get('all_flash_unchanged') is not True):
        raise ValueError('Exact complete A460 saved signal capture required')
    for key,mode in (('off',1),('pwm',2)):
        part = row[key]
        if part.get('complete') is not True: raise ValueError('Incomplete '+key+' batch')
        measured = signal_status(part['capture_line'],mode=mode,complete=True)
        if measured != part['capture']: raise ValueError('Saved status differs from original line')
        analyze(part['samples'],measured)
    if row['pwm']['capture'] != row['capture']: raise ValueError('Top-level capture mismatch')


def report(path):
    raw = path.read_bytes(); captured = json.loads(raw); validate_capture(captured)
    compile_kernel(EXE_2X,(6,4))
    result = dict(source=str(path.resolve()),source_sha256=hashlib.sha256(raw).hexdigest(),
                  image_sha256=SHA,repair_budget=[6,4],bridge_admitted=False,motor_qualified=False,
                  actual_bridge_switched=False,zero_qualification=captured['zero_qualification'],batches={})
    for key in ('off','pwm'):
        part = captured[key]
        zero = list(map(int,part['capture']['ZERO'].split(',')))
        replayed = replay(part['samples'],zero,EXE_2X)
        replayed['numerical_feedback_pass'] = replayed['trip_seq'] == 0 and replayed['reason'] == 0
        result['batches'][key] = replayed
    result['all_numerical_feedback_pass'] = all(r['numerical_feedback_pass'] for r in result['batches'].values())
    result['limitations'] = [
        'Saved ADC values only; sequence/timestamps are synthetic and angle is zero',
        'Stand-alone signal fixture, not complete FreeRTOS/FOC concurrency',
        'SD stayed low; this is not energized bridge feedback',
        'User six-signal confirmation is not an automated waveform measurement',
        'No hardware overcurrent or motor accuracy qualification']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT) or output.exists(): parser.error('New workspace evidence output only')
    result = report(args.input)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key: {k:r[k] for k in ('input_pairs','consumed','repaired','trip_seq','reason',
                       'window_repairs','repair_streak','numerical_feedback_pass')}
                      for key,r in result['batches'].items()},ensure_ascii=True,indent=2))
    print('NUMERICAL REPLAY '+('PASS' if result['all_numerical_feedback_pass'] else 'FAIL')+
          ': actual bridge/motor NOT qualified')
    print('Evidence: '+str(output))


if __name__ == '__main__': main()
