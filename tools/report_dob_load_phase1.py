"""Independent files-only audit/report for phase-1 Simulink paired trials.

No MATLAB, firmware transport or numerical dependencies required.
"""
import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics

CONTROL = ('speed_ref_rpm speed_meas_rpm accel_ref_rpm_s iq_pi_a iq_acc_ff_a '
           'iq_friction_a iq_raw_a iq_cmd_a speed_integrator_a iq_dob_a '
           'dob_estimate_a dob_valid dob_status abs_id_lpf_a id_lpf_before_a '
           'lpf_updated quality_reason admission_decision reset_count epoch_resets '
           'reset_reason warmup_s id_bad_us observer_age_us observer_source_us '
           'feedback_state adc_seq id_raw_a iq_meas_a simulation_guard_fault '
           'travel_deg observer_omega_rad_s iq_matched_a time_s target_rpm '
           'rpm_true iq_true_a load_ground_truth_a speed_noise_rpm iq_noise_a '
           'input_valid input_voltage_sat physical_current_pulse_a source_window').split()


def read_metrics(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for key in r.keys() - {'scenario'}:
            r[key] = float(r[key])
    return rows


def mean_std(values):
    v = [x for x in values if math.isfinite(x)]
    return {'n_available': len(v), 'mean': statistics.mean(v) if v else None,
            'std': statistics.stdev(v) if len(v) > 1 else None}


def audit_pair(off, on):
    count = rejected = spike_checks = 0
    gap = longest_gap = unavailable = dob_resets = feature_clears = 0
    previous = None
    with gzip.open(off, 'rt', encoding='utf-8-sig', newline='') as a, \
            gzip.open(on, 'rt', encoding='utf-8-sig', newline='') as b:
        ra, rb = csv.DictReader(a), csv.DictReader(b)
        for original in ra:
            current = next(rb, None)
            assert current is not None, 'Missing enabled sample'
            assert all(original[k] == current[k] for k in CONTROL), 'Control/truth/input changed'
            row = {k: float(v) for k, v in current.items()}
            assert all(math.isfinite(v) for v in row.values()), 'Nonfinite trace'
            assert abs(row['iq_cmd_a']) <= .500001 and row['iq_dob_a'] == 0
            assert row['simulation_guard_fault'] == 0
            assert 0 <= row['load_coverage'] <= 1
            assert row['load_state'] in range(6)
            assert float(original['load_state']) == 0
            if 2.3 <= row['time_s'] < 6.9:
                if not row['load_label_valid']:
                    unavailable += 1
                    gap += 1
                    longest_gap = max(longest_gap, gap)
                else:
                    gap = 0
                dob_resets += int(row['epoch_resets'])
                if previous:
                    feature_clears += int(row['load_quality_resets'] - previous['load_quality_resets'])
            if previous:
                accepted = row['load_accepted'] - previous['load_accepted']
                if accepted:
                    assert accepted == 1 and row['dob_valid'] and row['lpf_updated']
                    assert -.0001 <= row['load_source_age_ms'] <= 2
                if row['load_reason'] in (4, 5, 6, 9, 10, 11):
                    rejected += 1
                    assert accepted == 0, 'Invalid evidence credited'
                    assert row['load_feature_updated'] == 0 and row['load_label_valid'] == 0
                    if row['load_quality_resets'] == previous['load_quality_resets']:
                        for key in ('load_mean_a', 'load_trend_a_s', 'load_dwell_ms'):
                            assert row[key] == previous[key], 'Rejected evidence polluted features'
                if on.name.startswith('spike_') and abs(row['id_raw_a'] - .7) < .00001:
                    spike_checks += 1
                    assert row['lpf_updated'] == 0 and row['load_feature_updated'] == 0
                    assert row['abs_id_lpf_a'] == previous['abs_id_lpf_a']
                    assert row['epoch_resets'] == 0, 'Single isolated spike hard-reset original DOB'
            previous = row
            count += 1
        assert next(rb, None) is None, 'Extra enabled sample'
    return {'rows': count, 'rejected_frames_checked': rejected,
            'single_spike_checks': spike_checks, 'exact_control_truth_input_match': True,
            'unavailable_ms': unavailable, 'longest_unavailable_ms': longest_gap,
            'dob_event_resets': dob_resets, 'feature_event_clears': feature_clears}


def report(root):
    root = Path(root)
    manifest = json.loads((root / 'report.json').read_text())
    config = json.loads((root / 'config.json').read_text())
    accept = config['classification']['accept']
    per = read_metrics(root / 'metrics_per_trial.csv')
    groups = {}
    pairs = []
    for r in per:
        if r['features_enabled'] != 1:
            continue
        scenario, seed = r['scenario'], int(r['seed'])
        a = root / f'{scenario}_seed{seed:03d}_features0.csv.gz'
        b = root / f'{scenario}_seed{seed:03d}_features1.csv.gz'
        checked = audit_pair(a, b)
        checked.update(scenario=scenario, seed=seed)
        for key in ('unavailable_ms', 'longest_unavailable_ms', 'dob_event_resets', 'feature_event_clears'):
            r[key] = checked[key]
        pairs.append(checked)
        groups.setdefault(scenario, []).append(r)
    assert len(pairs) == manifest['pairs']
    assert all(len(g) == config['paired_repeats'] for g in groups.values())
    metrics = ('valid_rate', 'unknown_rate', 'high_recall', 'false_high_rate',
               'load_rmse_a', 'rise_delay_s', 'high_delay_s', 'release_delay_s',
               'return_light_delay_s', 'quality_reset_count', 'dob_reset_count',
               'unavailable_ms', 'longest_unavailable_ms', 'dob_event_resets', 'feature_event_clears')
    summary = {s: {k: mean_std([r[k] for r in g]) for k in metrics} for s, g in groups.items()}
    # Predeclared qualitative readiness gates, not motor safety thresholds.
    # Empirical windows are not independent mechanical load calibration.
    gates = {}
    for scenario in ('no_load', 'spike'):
        if scenario in groups:
            gates[scenario + '_false_high_below_1pct'] = all(
                r['false_high_rate'] <= accept['false_high_max'] for r in groups[scenario])
    for scenario in ('step', 'unload', 'negative_step'):
        if scenario in groups:
            gates[scenario + '_high_detect_within_800ms'] = all(
                math.isfinite(r['high_delay_s']) and r['high_delay_s'] <= accept['high_detect_max_s']
                for r in groups[scenario])
    output = {'independent_audit_pass': True, 'pairs': len(pairs),
              'rows_compared': sum(x['rows'] for x in pairs),
              'invalid_frames_checked': sum(x['rejected_frames_checked'] for x in pairs),
              'single_spike_checks': sum(x['single_spike_checks'] for x in pairs),
              'paired_repeats': config['paired_repeats'], 'groups': summary,
              'classification_readiness_gates': gates,
              'all_classification_readiness_gates_pass': all(gates.values()),
              'audit_pairs': pairs, 'hardware_access': False,
              'physical_performance_validated': False, 'control_adaptation': False}
    output['audit_source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    output['input_summary_sha256'] = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ('config.json', 'report.json', 'metrics_per_trial.csv', 'metrics_mean_std.csv')}
    (root / 'independent_phase1_audit.json').write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding='utf-8')
    with (root / 'availability_per_trial.csv').open('w', encoding='utf-8', newline='') as f:
        keys = ('scenario', 'seed', 'unavailable_ms', 'longest_unavailable_ms',
                'dob_event_resets', 'feature_event_clears')
        w = csv.DictWriter(f, keys)
        w.writeheader()
        w.writerows({k: r[k] for k in keys} for r in pairs)
    lines = ['# DOB 负载识别第1阶段：Simulink 对照', '',
             f"每组 {config['paired_repeats']} 次成对试验，共 {len(pairs)} 对 / {len(pairs)*2} 次仿真。",
             '仅启停只读分类分支；两侧 DOB 补偿均 OFF，未调速、未调整限幅或 FSM。', '',
             f"独立逐点审计通过：{output['rows_compared']} 对应帧，原控制、观察器、输入及机械真值完全一致；"
             f"检查 {output['invalid_frames_checked']} 个不可用分类帧。", '',
             '|场景|分类有效率 %|轻载误判重载 %|重载召回 %|上升检测 s|重载检测 s|卸载检测 s|回到轻载 s|',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    def fmt(stats, scale=1):
        if stats['mean'] is None:
            return 'N/A (0)'
        sd = stats['std']
        return (f"{stats['mean']*scale:.3f}" +
                (f" ± {sd*scale:.3f}" if sd is not None else '') +
                f" ({stats['n_available']})")
    for s, g in summary.items():
        cells = [fmt(g[k], 100 if k in ('valid_rate', 'false_high_rate', 'high_recall') else 1)
                 for k in ('valid_rate', 'false_high_rate', 'high_recall', 'rise_delay_s',
                           'high_delay_s', 'release_delay_s', 'return_light_delay_s')]
        lines.append('|' + s + '|' + '|'.join(cells) + '|')
    lines += ['', '数值为均值 ± 样本标准差，括号为实际可计算次数；无事件或未检测不填0。', '',
              '## 评估窗口中的不可用与复位', '',
              '|场景|累计不可用 ms|最长连续不可用 ms|原DOB复位事件|分类状态清空|',
              '|---|---:|---:|---:|---:|']
    for s, g in summary.items():
        lines.append('|' + s + '|' + '|'.join(fmt(g[k]) for k in
                     ('unavailable_ms', 'longest_unavailable_ms', 'dob_event_resets', 'feature_event_clears')) + '|')
    lines += ['', '以上只统计2.3～6.9秒，排除启动及最终STOP清空。分类清空不调用底层DOB Reset。', '',
              '## 预先声明的分类准入检查', '']
    lines += [f"- {name}: {'PASS' if passed else 'FAIL'}" for name, passed in gates.items()]
    lines += ['', '## 限制', '',
              '- 10/25 mA 分级、20 mA/s趋势、30 ms驻留、100 ms窗口为软件起始设置，未作真实负载标定。',
              '- HIGH召回包括阶跃后估计/窗口/驻留的延迟；趋势阶段可标为RISING而非HIGH。',
              '- 负扰动/助力当前归入轻载数值区间，未单独实现助力类别；日志仍保留有符号值。',
              '- 重放五次实测短窗只提供测量/电流扰动假设，不提供真实负载标签；两种假设均需保留。',
              '- 原monitor对来源无效/时间/序号/饱和异常直接复位；3ms来源无效可能引起约0.5s分类不可用，不能与跳变隔离短缺口混为一谈。本阶段原样保留并报告。',
              '- 全时域CSV保留启动、无效帧和停机；主分类指标使用2.3～6.9秒窗口。',
              '- 动态调速、电流上限调度、增益调度及DOB辅助FSM尚未实现。',
              '- 软件审计通过不代表分类门全部通过，更不代表实际电机/工件性能已验证。']
    (root / 'RESULTS_ZH.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in output.items() if k not in ('groups', 'audit_pairs')},
                     indent=2, ensure_ascii=False))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('results', type=Path)
    report(parser.parse_args().results)
