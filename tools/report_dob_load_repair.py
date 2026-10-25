"""Files-only before/after audit. Never communicates with firmware/hardware."""
import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics

from report_dob_load_phase1 import CONTROL, mean_std, read_metrics

FEATURES = ('load_state load_label_valid load_mean_a load_trend_a_s load_coverage '
            'load_feature_updated load_reason load_accepted load_rejected load_quality_resets '
            'load_dwell_ms load_window_good load_directional_raw_a load_source_age_ms '
            'load_transitions load_proposal').split()
ACTUATOR_TRUTH = CONTROL[:10] + CONTROL[29:31] + CONTROL[33:] + ['id_raw_a', 'iq_meas_a']
# Declared before full trials, software acceptance, not safety settings.
ACCEPT = {'real_level_transition_ratio_max': .5, 'short_gap_unavailable_max_ms': 8,
          'no_load_false_high_max': .01, 'high_detect_max_s': .8}


def audit_pair(before, after, original):
    n = holds = confirms = quarantined = 0
    previous = None
    with gzip.open(before, 'rt', newline='') as a, gzip.open(after, 'rt', newline='') as b, \
            gzip.open(original, 'rt', newline='') as c:
        old, fixed, historical = csv.DictReader(a), csv.DictReader(b), csv.DictReader(c)
        for rb in old:
            rf, rh = next(fixed, None), next(historical, None)
            assert rf is not None and rh is not None
            assert all(rb[k] == rh[k] for k in CONTROL), 'Legacy baseline original signals drifted'
            assert all(rb['legacy_' + k] == rh[k] for k in FEATURES), 'Legacy classifier drifted'
            assert all(rb[k] == rf[k] for k in ACTUATOR_TRUTH), 'Control/truth/exogenous input changed'
            if not before.name.startswith(('short_gap_', 'long_gap_')):
                assert all(rb[k] == rf[k] for k in CONTROL), 'Non-source-gap estimator path changed'
            row = {k: float(v) for k, v in rf.items()}
            assert all(math.isfinite(v) for v in row.values())
            assert row['simulation_guard_fault'] == 0 and abs(row['iq_cmd_a']) <= .500001
            assert row['iq_dob_a'] == 0
            assert row['load_state'] in (0, 1, 2, 4) and row['load_trend_state'] in (0, 1, 2, 3)
            if previous:
                if row['dob_status'] in (4096, 8192):
                    holds += int(row['dob_status'] == 4096)
                    confirms += int(row['dob_status'] == 8192)
                    assert row['dob_valid'] == row['lpf_updated'] == row['load_feature_updated'] == 0
                    for key in ('abs_id_lpf_a', 'iq_matched_a', 'warmup_s', 'reset_count'):
                        assert row[key] == previous[key], 'Hold/recovery advanced an estimator state'
                if row['load_reason'] in (4, 5, 6, 9, 10, 11):
                    quarantined += 1
                    assert row['load_label_valid'] == row['load_trend_valid'] == 0
                    assert row['load_accepted'] == previous['load_accepted']
                    if row['load_quality_resets'] == previous['load_quality_resets']:
                        for key in ('load_mean_a', 'load_trend_a_s', 'load_dwell_ms',
                                    'load_trend_filtered_a_s', 'load_trend_dwell_ms'):
                            assert row[key] == previous[key], 'Rejected sample entered a feature/timer'
                if before.name.startswith('spike_') and abs(row['id_raw_a'] - .7) < .00001:
                    assert row['epoch_resets'] == row['lpf_updated'] == row['load_feature_updated'] == 0
                    assert row['abs_id_lpf_a'] == previous['abs_id_lpf_a']
            previous = row
            n += 1
        assert next(fixed, None) is None and next(historical, None) is None
    return {'rows': n, 'held_missing_epochs': holds, 'recovery_endpoints': confirms,
            'invalid_feature_epochs': quarantined, 'baseline_matches_historical': True,
            'control_truth_inputs_identical': True}


def report(root, historical):
    root, historical = Path(root), Path(historical)
    config = json.loads((root / 'config.json').read_text())
    trials = read_metrics(root / 'metrics_per_trial.csv')
    groups = {}
    for r in trials:
        groups.setdefault((r['scenario'], int(r['revision'])), []).append(r)
    checks = []
    for (name, revision), group in groups.items():
        assert len(group) == config['paired_repeats']
        if revision:
            continue
        for r in group:
            seed = int(r['seed'])
            prefix = f'{name}_seed{seed:03d}_'
            check = audit_pair(root / (prefix + 'revision0.csv.gz'),
                               root / (prefix + 'revision1.csv.gz'),
                               historical / (prefix + 'features1.csv.gz'))
            check.update(scenario=name, seed=seed)
            checks.append(check)
    columns = ('valid_rate', 'transitions', 'trend_transitions', 'max_unavailable_ms',
               'event_dob_resets', 'high_recall', 'false_high_rate', 'rise_delay_s',
               'high_delay_s', 'release_delay_s', 'return_light_delay_s',
               'pre_event_rising', 'pre_event_high', 'pre_unload_falling')
    summary = {f'{name}:{rev}': {k: mean_std([r.get(k, float('nan')) for r in group]) for k in columns}
               for (name, rev), group in groups.items()}
    gates = {}
    for name in ('real_measurement', 'real_torque'):
        if (name, 1) not in groups:
            continue
        old = statistics.mean(r['transitions'] for r in groups[(name, 0)])
        new = statistics.mean(r['transitions'] for r in groups[(name, 1)])
        gates[name + '_level_switches_halved'] = new <= old * ACCEPT['real_level_transition_ratio_max']
    if ('short_gap', 1) in groups:
        gates['short_gap_recovers_without_dob_reset'] = all(
            r['event_dob_resets'] == 0 and r['max_unavailable_ms'] <= ACCEPT['short_gap_unavailable_max_ms']
            for r in groups[('short_gap', 1)])
    if ('long_gap', 1) in groups:
        gates['long_gap_invalidates_and_resets_once'] = all(
            r['event_dob_resets'] == 1 and r['max_unavailable_ms'] >= 390
            for r in groups[('long_gap', 1)])
    for name in ('no_load', 'spike'):
        if (name, 1) in groups:
            gates[name + '_no_false_high'] = all(
                r['false_high_rate'] <= ACCEPT['no_load_false_high_max'] for r in groups[(name, 1)])
    for name in ('step', 'unload', 'negative_step'):
        if (name, 1) in groups:
            gates[name + '_high_detect_within_bound'] = all(
                math.isfinite(r['high_delay_s']) and r['high_delay_s'] <= ACCEPT['high_detect_max_s']
                for r in groups[(name, 1)])
    result = {'audit_pass': True, 'pairs': len(checks), 'rows_compared': sum(x['rows'] for x in checks),
              'pair_repeats': config['paired_repeats'], 'acceptance': ACCEPT, 'gates': gates,
              'all_declared_gates_pass': all(gates.values()), 'groups': summary, 'pairs_audit': checks,
              'control_adaptation': False, 'physical_performance_validated': False,
              'audit_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (root / 'independent_repair_audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    lines = ['# DOB分类与短来源缺口：修复前后', '',
             f"13类正式矩阵每组10对；本次实际{len(checks)}对，每组{config['paired_repeats']}次。",
             f"独立审计{result['rows_compared']}个对应采样点：控制/真值/输入不变；旧基线逐点匹配历史原结果。", '',
             '|场景|旧标签切换|新等级切换|新趋势切换|旧→新有效率 %|旧→新最长不可用 ms|旧→新原DOB复位|',
             '|---|---:|---:|---:|---:|---:|---:|']
    def fmt(s, scale=1, count=False):
        if s['mean'] is None:
            return 'N/A (0)'
        return (f"{s['mean']*scale:.3f}" +
                (f" ± {s['std']*scale:.3f}" if s['std'] is not None else '') +
                (f" (n={s['n_available']})" if count else ''))
    for name, rev in groups:
        if rev:
            continue
        a, b = summary[name + ':0'], summary[name + ':1']
        lines.append('|' + name + '|' + '|'.join((fmt(a['transitions']), fmt(b['transitions']),
                     fmt(b['trend_transitions']), fmt(a['valid_rate'], 100) + ' → ' + fmt(b['valid_rate'], 100),
                     fmt(a['max_unavailable_ms']) + ' → ' + fmt(b['max_unavailable_ms']),
                     fmt(a['event_dob_resets']) + ' → ' + fmt(b['event_dob_resets']))) + '|')
    lines += ['', '均值±样本标准差。切换次数按整个7s统计，不可用/事件复位按2.3～6.9s统计。', '',
              '## 延迟与召回的取舍', '',
              '|场景|旧→新上升检测 s|旧→新重载确认 s|旧→新卸载检测 s|旧→新HIGH召回 %|',
              '|---|---:|---:|---:|---:|']
    for name, rev in groups:
        if rev:
            continue
        a, b = summary[name + ':0'], summary[name + ':1']
        lines.append('|' + name + '|' + '|'.join(fmt(a[k], scale, True) + ' → ' + fmt(b[k], scale, True)
                     for k, scale in [('rise_delay_s', 1), ('high_delay_s', 1),
                                      ('release_delay_s', 1), ('high_recall', 100)]) + '|')
    lines += ['', '延迟括号为实际可计算试次数；真实事件前已激活的标签不当作0ms成功检测。', '',
              '|场景|旧→新轻载期间HIGH占比 %|旧→新事件前已RISING的试次比例 %|',
              '|---|---:|---:|']
    for name, rev in groups:
        if rev:
            continue
        a, b = summary[name + ':0'], summary[name + ':1']
        lines.append('|' + name + '|' + '|'.join(fmt(a[k], 100) + ' → ' + fmt(b[k], 100)
                     for k in ('false_high_rate', 'pre_event_rising')) + '|')
    lines += ['', '## 固定的软件检查', '']
    lines += [f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in gates.items()]
    lines += ['', '## 限制', '',
              '- 改动只在仿真副本：分类等级/趋势分离，短来源缺口适配不在MCU编译链中。',
              '- 短缺口保留估计内部记忆，但每个缺失/恢复确认点均无效，不更新LPF、不积分/预热，不允许当作新反馈。',
              '- 最多5ms的可信间隔含两个真实恢复点；超时仅一次重置并重新预热。持续Id、饱和、时间/编码器异常不走短缺口恢复。',
              '- 趋势增加100ms滤波、80ms确认和迟滞，延迟可能增加；幅值等级保留原10/25mA与30ms确认。',
              '- 卸载时等级可能暂时仍为HIGH而趋势已为FALLING；必须保留两个量和失效标志，不能只凭等级决定补偿/状态。',
              '- 旧单枚举切换与新等级/趋势分别统计，不能只报告较少的等级切换而隐藏趋势抖动。',
              '- 除来源缺口外，DOB估计逐点不变。HIGH召回变化主要来自等级/趋势拆分，不代表观察器本身估计更准确。',
              '- 五次实测短窗的两个噪声/真实电流假设都保留，没有真实负载或扭矩标定。',
              '- 本轮关闭DOB补偿，不验证补偿收益，不接入速度/Iq限幅/增益/FSM自适应，不代表实机性能已验证。']
    (root / 'RESULTS_ZH.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('groups', 'pairs_audit')},
                     indent=2, ensure_ascii=False))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('results', type=Path)
    p.add_argument('--historical', type=Path, default=Path('simulation/dob_simulink/phase1_results/20261024_105548'))
    args = p.parse_args()
    report(args.results, args.historical)
