"""Files-only, source-verified empirical event library; never drives hardware.

Triggered windows are selection-biased. Their amplitude/shape are evidence;
their frequency, noise-only interpretation and true applied torque are NOT.
"""
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
import dob_id_trace_report as trace

SOURCES = [
    ('v7_100', '1792733225686577700', 'MechanicalDobPreLpfCandidate'),
    ('v7_200', '1792734456546723200', 'MechanicalDobPreLpf200Candidate'),
]


def export(destination=None):
    out = Path(destination or Path(__file__).parent / 'data')
    out.mkdir(parents=True, exist_ok=True)
    all_rows, sources = [], []
    for source_id, (name, run, preset) in enumerate(SOURCES, 1):
        receipt = ROOT / f'tmp/mechanical-ident-run-{run}.json'
        elf = ROOT / f'foc2_app_a/build/{preset}/foc2.elf'
        decoded = trace.decode(receipt, elf)  # original provenance + trace ABI audit
        rows = [r for r in decoded['rows'] if r['phase'] in ('pre', 'dense_post')]
        assert len(rows) == 40 and decoded['board_verified']
        iq = [r['iq_meas_a'] for r in rows]
        for i, r in enumerate(rows):
            # Five-point local median removes the changing operating current,
            # NOT a calibrated separation of ADC noise / real current dynamics.
            center = statistics.median(iq[max(0, i-2):min(len(iq), i+3)])
            all_rows.append(dict(source_id=source_id, source_name=name, source_row=i,
                original_us=r['timestamp_us'], relative_us=r['timestamp_us']-rows[0]['timestamp_us'],
                interval_us=r['interval_us'], id_raw_a=r['id_meas_a'], iq_raw_a=r['iq_meas_a'],
                iq_local_median_a=center, iq_residual_a=r['iq_meas_a']-center,
                original_speed_ref_rpm=r['speed_ref_rpm'], original_speed_meas_rpm=r['speed_meas_rpm'],
                original_quality_reason=r['quality_reason'], original_reset_reason=r['reset_reason'],
                original_lpf_before_a=r['abs_id_lpf_before_a'], original_lpf_after_a=r['abs_id_lpf_a']))
        sources.append(dict(source_id=source_id, name=name, receipt=str(receipt), elf=str(elf),
            receipt_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
            elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
            dense_samples=len(rows), sparse_samples_excluded=len(decoded['rows'])-len(rows),
            duration_us=rows[-1]['timestamp_us']-rows[0]['timestamp_us'],
            min_interval_us=min(r['interval_us'] for r in rows),
            max_interval_us=max(r['interval_us'] for r in rows),
            id_abs_peak_a=max(abs(r['id_meas_a']) for r in rows),
            iq_abs_peak_a=max(abs(v) for v in iq), board_provenance_verified=True))
    with (out/'events.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=all_rows[0])
        writer.writeheader();writer.writerows(all_rows)
    manifest = dict(sources=sources, dense_samples=len(all_rows),
        events_sha256=hashlib.sha256((out/'events.csv').read_bytes()).hexdigest(),
        sparse_interpolation=False, occurrence_rate_identified=False,
        current_spikes_proven_noise_only=False, load_ground_truth_available=False,
        note='Triggered startup windows, not representative steady/noise statistics. '
             'Iq residual = raw Iq - local median5; may include genuine current dynamics. '
             'Closed-loop embedding uses a declared synthetic schedule/grid, NOT a full real-run replay.')
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    print(json.dumps(export(), indent=2))
