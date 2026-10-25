"""Decode first/last fallback evidence from stopped RAM and matching audit ELF.

Files only: no connection, reset, flash or motor action.
"""
import argparse
import json
import math
from pathlib import Path
import struct

REASONS = {0: 'none', 1: 'low_longer_than100ms', 2: 'source_or_quality',
           3: 'direction_or_return_to_low', 4: 'return_deadline_or_cold_ready', 5: 'lifecycle_stop_or_fault'}
SITES = {1: 'input_or_quality_rejected', 2: 'direction_reversed', 3: 'low_exceeded100ms',
         4: 'fell_below10rpm_again', 5: 'saturated_after_state_projection',
         6: 'original_cold_observer_already_ready', 7: 'return_exceeded200ms', 8: 'stopped_or_faulted'}
U32_NAMES = ('timestamp_us reason site mode status input_valid filter_updated decision quality_reason '
             'quiet_n quiet_age_us low_start_us return_start_us low_elapsed_us return_elapsed_us '
             'source_us published_us accepted_gap_us').split()
FLOAT_NAMES = 'omega_rad_s id_a iq_a abs_id_lpf_a omega_range_rad_s drive_range_a'.split()


def decode_tail(tail):
    if len(tail) != 200:
        raise ValueError('Expected the exact200-byte window75 value/stamp tail')
    magic, count = struct.unpack_from('<2I', tail, 192)
    if magic != 0xD10A0001 and any(tail):
        raise ValueError('Unknown audit footer or uninitialized recorder data')
    if bool(count) != bool(magic):
        raise ValueError('Audit footer/count mismatch')
    result = {}
    for slot, name in enumerate(('first', 'last')):
        raw = tail[slot * 96:slot * 96 + 96]
        if not count:
            result[name] = None
            continue
        item = dict(zip(U32_NAMES + FLOAT_NAMES, struct.unpack('<18I6f', raw)))
        if item['reason'] not in REASONS or item['site'] not in SITES or item['mode'] not in (1, 2, 3):
            raise ValueError('Unknown fallback event ABI/corrupt RAM')
        item['reason_name'] = REASONS[item['reason']]
        item['site_name'] = SITES[item['site']]
        item['timestamp_basis'] = 'last_actual_sample' if item['site'] == 8 else 'current_encoder_epoch'
        item['nonfinite_fields'] = [k for k in FLOAT_NAMES if not math.isfinite(item[k])]
        for k in item['nonfinite_fields']:
            item[k] = None
        item['mechanical_rpm'] = item['omega_rad_s'] * 30 / math.pi if item['omega_rad_s'] is not None else None
        result[name] = item
    return dict(abi=1, event_count=count, snapshots=result, missing_means='no_recorded_fallback_not_a_success_claim',
                scope='First and last events only; intermediate events may be overwritten; no motor performance claim')


def load(ram, elf):
    from foc_path_profile_report import symbols
    syms = symbols(elf)
    if 'DobLowAudit_Record' not in syms or syms.get('dob_low_recovery', (0, 0))[1] != 100:
        raise ValueError('Matching audit-candidate ELF required; old firmware did not record these bytes')
    raw = Path(ram).read_bytes()
    address, size = syms['mechanical_capture']
    pointer_address, pointer_size = syms['dob_trend_continuous_arena']
    base = address - 0x20000000
    pointer_offset = pointer_address - 0x20000000
    if size != 4712 or pointer_size != 4 or not 0 <= base <= len(raw) - size or not 0 <= pointer_offset <= len(raw) - 4:
        raise ValueError('Arena/RAM bounds')
    if struct.unpack_from('<I', raw, pointer_offset)[0] != address:
        raise ValueError('Recorder not bound to expected capture; no fabricated fallback evidence')
    return decode_tail(raw[base + 300:base + 400] + raw[base + 700:base + 800])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ram', type=Path, required=True)
    parser.add_argument('--elf', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    text = json.dumps(load(args.ram, args.elf), ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text)
