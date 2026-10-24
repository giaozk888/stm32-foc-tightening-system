"""Files-only decoder for the A-only DOB SHADOW monitor. No device access.

The ring holds decimated instantaneous observations, NOT 64 ms averages.
Recorded VALID is historical sample validity, never permission to drive Iq.
"""
import argparse
import json
import math
from pathlib import Path
import struct

CAPACITY = 16
FRAME_SIZE = 44
SIZE = 856
FRAME_KEYS = ('sample_us adc_seq adc_source_us adc_published_us status valid '
              'omega_rad_s iq_a iq_matched_a id_a disturbance_a').split()
META_KEYS = ('version head count observations valid_samples rejected_samples '
             'last_seq last_encoder_us last_stored_us running frozen have_sample '
             'iq_lpf abs_id_lpf disturbance_abs_peak positive_sum negative_sum '
             'positive_n negative_n max_compute_us').split()
REASONS = {1: 'UNCONFIGURED', 2: 'BAD_SAMPLE', 4: 'ZERO_SPEED', 8: 'WARMUP',
           16: 'FAULT', 32: 'OFF', 64: 'TIME', 128: 'SATURATED', 256: 'ID',
           512: 'SEQUENCE', 1024: 'CURRENT'}


def reasons(status):
    if status & ~2047:
        raise ValueError('Unknown DOB status bits')
    return [name for flag, name in REASONS.items() if status & flag]


def frame(data, offset):
    row = dict(zip(FRAME_KEYS, struct.unpack_from('<6I5f', data, offset)))
    if row['valid'] not in (0, 1):
        raise ValueError('DOB validity ABI')
    if not all(math.isfinite(row[k]) for k in FRAME_KEYS[6:]):
        raise ValueError('Nonfinite DOB frame')
    row['reasons'] = reasons(row['status'])
    # ADC pair-read may occur AFTER encoder receive in the same outer epoch.
    # Runtime checks both against captured observed_us (not stored in this ABI):
    # 0<=observed-encoder<=2000 and 0<=observed-source<=200 us. Consequently
    # source-encoder may be [-200,+2000], not a nonnegative encoder-age.
    relative = ((row['adc_source_us']-row['sample_us']+0x80000000) & 0xffffffff)-0x80000000
    row['adc_relative_to_encoder_us'] = relative
    if row['valid'] and (row['status'] or
            not -200 <= relative <= 2000 or
            (row['adc_published_us'] - row['adc_source_us']) & 0xffffffff > 100):
        raise ValueError('Valid DOB frame contradicts quality metadata')
    return row


def decode_bytes(data):
    if len(data) != SIZE:
        raise ValueError('DOB monitor ABI mismatch')
    meta = dict(zip(META_KEYS, struct.unpack_from('<12I5f3I', data, 776)))
    if meta['version'] & 1:
        raise ValueError('DOB write in progress; not a coherent snapshot')
    if (meta['head'] >= CAPACITY or meta['head'] != meta['count'] % CAPACITY or
            meta['count'] > meta['observations'] or
            bool(meta['count']) != bool(meta['observations']) or
            meta['valid_samples'] + meta['rejected_samples'] > meta['observations'] or
            meta['positive_n'] + meta['negative_n'] != meta['valid_samples'] or
            any(meta[k] not in (0, 1) for k in ('running', 'have_sample')) or
            meta['frozen'] not in (0, 16, 32) or (meta['frozen'] and meta['running'])):
        raise ValueError('DOB ring/counter metadata mismatch')
    if not all(math.isfinite(meta[k]) for k in META_KEYS[12:17]):
        raise ValueError('Nonfinite DOB aggregate')
    if meta['abs_id_lpf'] < 0 or meta['disturbance_abs_peak'] < 0:
        raise ValueError('Invalid absolute aggregate')
    current = frame(data, 732)
    if (meta['frozen'] or not meta['running']) and current['valid']:
        raise ValueError('Inactive monitor claims a valid current sample')
    n = min(meta['count'], CAPACITY)
    start = (meta['head'] - n) % CAPACITY
    rows = [frame(data, 28 + ((start + i) % CAPACITY) * FRAME_SIZE) for i in range(n)]
    elapsed = 0
    for i, row in enumerate(rows):
        if i:
            delta = (row['sample_us'] - rows[i-1]['sample_us']) & 0xffffffff
            if not 64000 <= delta < 0x80000000:
                raise ValueError('DOB ring timestamp order mismatch')
            elapsed += delta
        row['tail_elapsed_s'] = elapsed * 1e-6
    if rows and rows[-1]['sample_us'] != meta['last_stored_us']:
        raise ValueError('DOB last stored timestamp mismatch')
    return dict(meta=meta, current=current, rows=rows, tail_span_s=elapsed * 1e-6,
                positive_mean_a=meta['positive_sum']/meta['positive_n'] if meta['positive_n'] else None,
                negative_mean_a=meta['negative_sum']/meta['negative_n'] if meta['negative_n'] else None,
                feedback_enabled=False, live=False,
                note='Historical capture only. 16 instantaneous samples spaced >=64 ms, not bin means; '
                     'full-session aggregates cover valid task observations. Max compute time is an '
                     'independent wall-clock maximum including IRQ preemption, not a per-frame field. '
                     'ADC software pair-read may follow encoder receive; signed relative time is not '
                     'analog aperture age. observed_us is not retained, so exact runtime age checks '
                     'cannot be reconstructed from these frames alone. REJECT counts quality failures, '
                     'not low speed/warmup. No Nm or absolute Kt claim.')


def decode(receipt, elf):
    import mechanical_identification_report as original
    from foc_path_profile_report import symbols
    # Reuse exact ELF/BIN/Flash/RAM provenance and existing protection/stop closure.
    capture = original.decode(receipt, elf)
    if not capture['board_verified']:
        raise ValueError('Board provenance / protection / shutdown checks failed')
    r = json.loads(receipt.read_text())
    ram = Path(r['ram_capture']).read_bytes()
    flash = Path(r['final_capture']).read_bytes()
    sym = symbols(elf)
    address, size = sym['mechanical_dob_monitor']
    offset = address - 0x20000000
    if size != SIZE or not 0 <= offset <= len(ram) - SIZE:
        raise ValueError('DOB RAM symbol/bounds mismatch')
    address, size = sym['mechanical_dob_identified_model']
    offset_model = address - 0x08000000
    if size != 28 or not 0 <= offset_model <= len(flash) - size:
        raise ValueError('DOB model Flash symbol/bounds mismatch')
    values = struct.unpack_from('<6fI', flash, offset_model)
    if not all(math.isfinite(v) for v in values[:6]) or values[6] != 1:
        raise ValueError('Unqualified/nonfinite DOB model')
    result = decode_bytes(ram[offset:offset+SIZE])
    if result['meta']['running'] or not result['meta']['frozen']:
        raise ValueError('DOB monitor not stopped/frozen')
    result.update(model=dict(zip(('j_over_kt', 'b_over_kt', 'coulomb_over_kt', 'bias_a',
                                 'bandwidth_rad_s', 'min_speed_rad_s', 'qualified'), values)),
                  session_hash=capture['session_hash'], board_verified=True,
                  measurements_are_not_control_feedback=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--elf', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(decode(args.receipt, args.elf), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
