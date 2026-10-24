"""Independent files-only audit of the consumed inputs and bounded outputs."""
import csv
import hashlib
import json
import math
from pathlib import Path

EXOGENOUS = ['time_s', 'target_rpm', 'load_ground_truth_a', 'speed_noise_rpm',
             'iq_noise_a', 'id_raw_a', 'physical_current_pulse_a', 'input_valid',
             'input_voltage_sat', 'input_encoder_age_us', 'input_running']


def audit(folder=None):
    folder = Path(folder or Path(__file__).parent / 'results')
    with (folder / 'metrics_per_trial.csv').open(newline='', encoding='utf-8-sig') as f:
        metrics = list(csv.DictReader(f))
    signatures, quarantined, matches, pulses = {}, 0, 0, 0
    for metric in metrics:
        name, seed, gain = metric['case_name'], int(metric['seed']), float(metric['gain'])
        if metric['profile'] != 'nominal':
            name += '__' + metric['profile']
        path = folder / f'{name}_seed{seed}_g{gain:g}_cap0.025.csv'
        h = hashlib.sha256()
        with path.open(newline='', encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 7001, (path, len(rows))
        for row in rows:
            h.update((','.join(row[k] for k in EXOGENOUS)+'\n').encode())
            assert all(math.isfinite(float(v)) for v in row.values())
            assert abs(float(row['iq_cmd_a'])) <= .5000001
            assert abs(float(row['iq_dob_a'])) <= .0250001
            assert float(row['simulation_guard_fault']) == 0
            assert abs(float(row['iq_true_a'])-float(row['iq_regulator_a'])-
                       float(row['physical_current_pulse_a'])) < 1e-10
            if float(row['physical_current_pulse_a']):
                pulses += 1
            if int(float(row['quality_reason'])) & 8 and float(row['lpf_updated']) == 0:
                quarantined += 1
                assert float(row['abs_id_lpf_a']) == float(row['id_lpf_before_a'])
        key = name, seed
        if gain == 0:
            signatures[key] = h.hexdigest()
        else:
            assert h.hexdigest() == signatures[key], ('OFF/ON unmatched exogenous', path)
            matches += 1
    assert quarantined > 0 and pulses > 0
    report = dict(passed=True, trials=len(metrics), matched_pairs=matches,
                  quarantined_frames_checked=quarantined, physical_pulse_frames=pulses,
                  exogenous_fields=EXOGENOUS, hardware_access=False,
                  physical_performance_validated=False)
    (folder / 'independent_audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    print(json.dumps(audit(), indent=2))
