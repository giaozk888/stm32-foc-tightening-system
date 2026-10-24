"""Independent files-only OFF/ON exogenous matching and numerical audit."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

EXOGENOUS = ('time_s', 'target_rpm', 'load_ground_truth_a', 'speed_noise_rpm',
             'iq_noise_a', 'id_raw_a', 'input_valid', 'input_voltage_sat',
             'input_encoder_age_us', 'input_running')


def check(folder: Path):
    report = json.loads((folder / 'report.json').read_text())
    assert report['mode'] == 'full' and report['repeats'] >= 3
    assert report['estimator_passed'] and report['firmware_sources_unchanged']
    trials = list(csv.DictReader((folder / 'metrics_per_trial.csv').open()))
    reference = {}
    supplements = []
    for metric in trials:
        scenario, seed = metric['scenario'], int(metric['seed'])
        gain, cap = float(metric['gain']), float(metric['cap_a'])
        label = f'{scenario}_seed{seed}_' + ('OFF' if gain == 0 else f'gain{gain:g}_cap{cap:g}')
        h = hashlib.sha256()
        count = 0
        cap_time = warming_time = 0.0
        actual_iq_peak = 0.0
        with (folder / (label + '.csv')).open() as stream:
            for row in csv.DictReader(stream):
                h.update(('|'.join(row[k] for k in EXOGENOUS) + '\n').encode())
                count += 1
                for key in ('iq_cmd_a', 'iq_dob_a', 'speed_integrator_a', 'dob_estimate_a', 'rpm_true'):
                    assert math.isfinite(float(row[key])), (label, key)
                assert abs(float(row['iq_cmd_a'])) <= .5000001, label
                assert abs(float(row['iq_dob_a'])) <= cap + 1e-7, label
                assert abs(float(row['speed_integrator_a'])) <= .3500001, label
                assert row['simulation_guard_fault'] == '0', label
                cap_time += .001 * (abs(float(row['iq_dob_a'])) >= cap-1e-7)
                warming_time += .001 * bool(int(float(row['dob_status'])) & 8 and float(row['warmup_s']) > 0)
                actual_iq_peak = max(actual_iq_peak, abs(float(row['iq_true_a'])))
                if int(float(row['quality_reason'])) & 8 and row['lpf_updated'] == '0':
                    assert row['abs_id_lpf_a'] == row['id_lpf_before_a'], ('quarantine LPF pollution', label)
        assert count == 7001, (label, count)
        key = scenario, seed
        if gain == 0:
            reference[key] = h.hexdigest()
        else:
            assert key in reference and h.hexdigest() == reference[key], ('OFF/ON inputs differ', label)
        supplements.append(dict(scenario=scenario, seed=seed, gain=gain, cap_a=cap,
                                compensation_cap_s=cap_time, iq_actual_peak_a=actual_iq_peak,
                                explicit_warmup_status_s=warming_time))
    result = dict(passed=True, trials=len(trials), matched_pairs=len(trials)-len(reference),
                  exogenous_fields=EXOGENOUS, nan_inf_and_limits_passed=True,
                  hardware_access=False, physical_performance_validated=False)
    assert len(trials) == report['trials']
    with (folder / 'metrics_supplement.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=supplements[0])
        writer.writeheader()
        writer.writerows(supplements)
    (folder / 'independent_files_audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('folder', type=Path)
    print(json.dumps(check(p.parse_args().folder), indent=2))
