"""Four-profile, same-input trend scan: strict event matching and files audit.

All measurements are from software logs; no board or actuator interface.
"""
import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics

from report_dob_load_phase1 import CONTROL, mean_std
from report_dob_load_repair import FEATURES

TAIL = ['load_trend_state', 'load_trend_valid', 'load_trend_filtered_a_s',
        'load_trend_transitions', 'load_trend_dwell_ms', 'load_trend_proposal']
ALL_FEATURES = FEATURES + TAIL


def episode_onsets(t, state, valid, label, start, end):
    """Invalid held frames cannot create a second onset on quality recovery."""
    last, started, result = 0, False, []
    for x, s, good in zip(t, state, valid):
        inside = start <= x < end
        if inside and good and not started:
            started = True
            if good and s == label and last == label:
                result.append(x)  # Already-active episode crossing evaluation boundary.
        if s == 0:
            last = 0
        elif good:
            if inside and s == label and last != label:
                result.append(x)
            last = s
    return result


def match_events(detected, truth, max_delay):
    """At most one causal detection per independent event; extras are FP."""
    unused = list(truth)
    delays, false = [], 0
    for d in detected:
        eligible = [e for e in unused if 0 <= d-e <= max_delay+1e-9]
        if not eligible:
            false += 1
        else:
            event = min(eligible)
            unused.remove(event)
            delays.append(max(0, d-event))
    return {'hits': len(delays), 'false': false, 'misses': len(unused),
            'delays': delays, 'expected': len(truth)}


def high_clear_delay(t, level, valid, event):
    if event is None:
        return math.nan
    prior = [i for i, x in enumerate(t) if x < event and valid[i]]
    if not prior or level[prior[-1]] != 4:
        return math.nan
    for x, state, good in zip(t, level, valid):
        if x >= event and good and state != 4:
            return x-event
    return math.nan


def profile_metrics(data, cfg, scenario, seed, profile, index):
    t, truth = data['time_s'], data['load_ground_truth_a']
    start, end = cfg['scan']['eval_s']
    event = cfg['base']['event_s']
    unload = cfg['base']['unload_s']
    has_load = any(abs(v) > .005 for v in truth)
    has_unload = has_load and any(x >= unload and abs(v) < .001 for x, v in zip(t, truth))
    up = [event] if has_load else []
    down = [unload] if has_unload else []
    s, good = data['profiles'][index]['state'], data['profiles'][index]['valid']
    rising = episode_onsets(t, s, good, 2, start, end)
    falling = episode_onsets(t, s, good, 3, start, end)
    maximum = cfg['scan']['event_match_max_s']
    a, b = match_events(rising, up, maximum), match_events(falling, down, maximum)
    mask = [i for i, x in enumerate(t) if start <= x < end]
    mean = lambda v: statistics.mean(v) if v else math.nan
    previous = max((i for i, x in enumerate(t) if x < event), default=0)
    result = {'scenario': scenario, 'seed': seed, 'split': 'train' if seed <= 5 else 'heldout',
              'profile': profile, 'tau_ms': cfg['scan']['tau_ms'][index],
              'dwell_ms': cfg['scan']['dwell_ms'][index],
              'trend_valid_rate': mean([good[i] for i in mask]),
              'level_valid_rate': mean([data['load_label_valid'][i] for i in mask]),
              'level_transitions': data['level_transitions'],
              'trend_transitions': data['profiles'][index]['transitions'],
              'rise_hits': a['hits'], 'rise_fp': a['false'], 'rise_miss': a['misses'],
              'fall_hits': b['hits'], 'fall_fp': b['false'], 'fall_miss': b['misses'],
              'false_events': a['false']+b['false'], 'missed_events': a['misses']+b['misses'],
              'rise_delay_s': mean(a['delays']), 'fall_delay_s': mean(b['delays']),
              'max_delay_s': max(a['delays']+b['delays'], default=math.nan),
              'pre_event_rising': int(has_load and s[previous] == 2 and good[previous]),
              'pre_unload_falling': 0,
              'high_clear_s': high_clear_delay(t, data['load_state'], data['load_label_valid'],
                                             unload if has_unload else None)}
    if has_unload:
        k = max(i for i, x in enumerate(t) if x < unload)
        result['pre_unload_falling'] = int(s[k] == 3 and good[k])
    return result


def audit_trace(file, reference, ids):
    data = {k: [] for k in ('time_s', 'load_ground_truth_a', 'load_state', 'load_label_valid')}
    data['profiles'] = [{'state': [], 'valid': [], 'transitions': 0} for _ in ids]
    previous = None
    invalid_checks = 0
    with gzip.open(file, 'rt', newline='') as a, gzip.open(reference, 'rt', newline='') as b:
        current, historical = csv.DictReader(a), csv.DictReader(b)
        for row in current:
            original = next(historical, None)
            assert original is not None
            assert all(row[k] == original[k] for k in CONTROL + ALL_FEATURES), 'Baseline drift'
            assert float(row['simulation_guard_fault']) == 0
            assert abs(float(row['iq_cmd_a'])) <= .500001 and float(row['iq_dob_a']) == 0
            prefixes = [''] + [name + '_' for name in ids[1:]]
            all_tail = []
            for j, prefix in enumerate(prefixes):
                assert all(row[prefix+k] == row[k] for k in FEATURES), 'Level/quality changed'
                tail = [float(row[prefix+k]) for k in TAIL]
                assert all(math.isfinite(x) for x in tail)
                assert tail[0] in range(4) and tail[1] in (0, 1)
                assert not tail[1] or float(row['load_label_valid']) == 1
                if previous and int(float(row['load_reason'])) in (4, 5, 6, 9, 10, 11):
                    invalid_checks += 1
                    assert tail[1] == 0
                    if row['load_quality_resets'] == previous[0]:
                        assert tail[2] == previous[1][j][2] and tail[4] == previous[1][j][4], \
                            'Rejected epoch advanced trend/filter dwell'
                p = data['profiles'][j]
                p['state'].append(int(tail[0]));p['valid'].append(bool(tail[1]));p['transitions'] = tail[3]
                all_tail.append(tail)
            for k in ('time_s', 'load_ground_truth_a', 'load_state', 'load_label_valid'):
                data[k].append(float(row[k]))
            data['level_transitions'] = float(row['load_transitions'])
            previous = row['load_quality_resets'], all_tail
        assert next(historical, None) is None
    return data, invalid_checks


def stats(rows, key):
    return mean_std([r[key] for r in rows])


def eligibility(rows, profile, baseline, cfg, split):
    scope = [r for r in rows if split == 'all' or r['split'] == split]
    tests = {}
    for scenario in cfg['classification']['scenarios']:
        a = [r for r in scope if r['scenario'] == scenario and r['profile'] == baseline]
        b = [r for r in scope if r['scenario'] == scenario and r['profile'] == profile]
        if not a:
            continue
        tests[scenario+'_no_extra_fp'] = sum(r['false_events'] for r in b) <= sum(r['false_events'] for r in a)
        tests[scenario+'_no_extra_miss'] = sum(r['missed_events'] for r in b) <= sum(r['missed_events'] for r in a)
        tests[scenario+'_no_less_valid_time'] = statistics.mean(r['trend_valid_rate'] for r in b) >= \
            statistics.mean(r['trend_valid_rate'] for r in a)-1e-12
        if scenario in ('real_measurement', 'real_torque'):
            tests[scenario+'_transition_bound'] = statistics.mean(r['trend_transitions'] for r in b) <= \
                cfg['scan']['accept']['real_transition_ratio_max'] * statistics.mean(r['trend_transitions'] for r in a)
    latency = [r[k] for r in scope if r['profile'] == profile
               for k in ('rise_delay_s', 'fall_delay_s') if math.isfinite(r[k])]
    has_data = any(r['profile'] == profile for r in scope)
    return {'eligible': has_data and all(tests.values()), 'checks': tests,
            'score_s': statistics.mean(latency) if latency else None}


def report(root):
    root = Path(root)
    cfg = json.loads((root/'config.json').read_text())
    completion = json.loads((root/'report.json').read_text())
    ids = cfg['scan']['ids']
    historical = Path(cfg['base']['root'])/'load_repair_results'/cfg['scan']['baseline_results']
    rows, audit = [], []
    for run in completion['runs']:
        scenario, seed = run['scenario'], int(run['seed'])
        file = root/f'{scenario}_seed{seed:03d}.csv.gz'
        data, invalid = audit_trace(file, historical/f'{scenario}_seed{seed:03d}_revision1.csv.gz', ids)
        assert len(data['time_s']) == run['rows'] == 7001
        for j, name in enumerate(ids):
            rows.append(profile_metrics(data, cfg, scenario, seed, name, j))
        audit.append({'scenario': scenario, 'seed': seed, 'rows': run['rows'],
                      'invalid_profile_frames': invalid, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
    assert len(audit) == completion['model_runs']
    assert len(rows) == completion['classification_evaluations']
    for scenario in cfg['classification']['scenarios']:
        for name in ids:
            assert sum(r['scenario'] == scenario and r['profile'] == name for r in rows) == cfg['repeats']
    with (root/'metrics_per_trial.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, list(rows[0]));w.writeheader();w.writerows(rows)
    columns = ['trend_transitions', 'false_events', 'missed_events', 'rise_delay_s', 'fall_delay_s',
               'max_delay_s', 'trend_valid_rate', 'high_clear_s', 'pre_event_rising', 'pre_unload_falling']
    summaries = []
    for scenario in cfg['classification']['scenarios']:
        for name in ids:
            group = [r for r in rows if r['scenario'] == scenario and r['profile'] == name]
            summaries.append({'scenario': scenario, 'profile': name,
                              **{k: stats(group, k) for k in columns},
                              'rise_hits': sum(r['rise_hits'] for r in group),
                              'fall_hits': sum(r['fall_hits'] for r in group),
                              'false_events_sum': sum(r['false_events'] for r in group),
                              'missed_events_sum': sum(r['missed_events'] for r in group)})
    flattened = []
    for r in summaries:
        flat = {'scenario': r['scenario'], 'profile': r['profile']}
        for k, v in r.items():
            if isinstance(v, dict):
                for stat, value in v.items():
                    flat[k+'_'+stat] = value
            elif k not in flat:
                flat[k] = v
        flattened.append(flat)
    with (root/'metrics_mean_std.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, list(flattened[0]));w.writeheader();w.writerows(flattened)
    selection = {name: {split: eligibility(rows, name, ids[0], cfg, split)
                        for split in ('train', 'heldout', 'all')} for name in ids}
    eligible = [name for name in ids if selection[name]['train']['eligible']]
    winner = min(eligible, key=lambda name: selection[name]['train']['score_s']
                 if selection[name]['train']['score_s'] is not None else math.inf)
    heldout_pass = selection[winner]['heldout']['eligible']
    recommendation = winner if heldout_pass else ids[0]
    result = {'audit_pass': True, 'model_runs': len(audit), 'profile_evaluations': len(rows),
              'repeats': cfg['repeats'], 'rows_compared': sum(r['rows'] for r in audit),
              'four_profile_level_and_quality_identical': True, 'baseline_matches_previous': True,
              'selection': selection, 'train_winner': winner, 'heldout_pass': heldout_pass,
              'recommendation': recommendation, 'parameters_applied': False,
              'summaries': summaries, 'trace_audit': audit, 'hardware_access': False,
              'physical_performance_validated': False,
              'audit_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (root/'independent_trend_audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    write_report(root, cfg, rows, summaries, result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('selection','summaries','trace_audit')}, indent=2))
    return result


def write_report(root, cfg, rows, summaries, result):
    ids = cfg['scan']['ids']
    lines = ['# 趋势滤波/确认时间：四组参数对照', '',
             f"{result['model_runs']}次Simulink运行，四路共享同一轨迹，得到{result['profile_evaluations']}份分类评估。",
             f"每场景每参数{cfg['repeats']}次；独立审计{result['rows_compared']}个采样点，基线匹配上轮、等级/质量和控制不变。", '',
             '|参数组|滤波常数 ms|确认 ms|全场景误激活事件|漏检事件|匹配事件延迟均值 ms|P95 ms|最慢 ms|',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for j, name in enumerate(ids):
        group = [r for r in rows if r['profile'] == name]
        delay = sorted(r[k]*1000 for r in group for k in ('rise_delay_s','fall_delay_s') if math.isfinite(r[k]))
        lines.append('|'+name+f"|{cfg['scan']['tau_ms'][j]}|{cfg['scan']['dwell_ms'][j]}|"+
                     f"{sum(r['false_events'] for r in group)}|{sum(r['missed_events'] for r in group)}|"+
                     (f"{statistics.mean(delay):.2f}|{delay[math.ceil(.95*len(delay))-1]:.2f}|{max(delay):.2f}|" if delay else 'N/A|N/A|N/A|'))
    lines += ['', 'P95为这批有限样本的经验分位数；均值仅匹配事件，漏检不计0且单独列出。', '',
              '## 逐场景：均值±样本标准差', '',
              '|场景/参数|趋势切换|误激活事件|漏检|上升延迟 ms|卸载延迟 ms|卸载HIGH清除 ms|',
              '|---|---:|---:|---:|---:|---:|---:|']
    def fmt(s, scale=1):
        return 'N/A (0)' if s['mean'] is None else f"{s['mean']*scale:.2f} ± {(s['std'] or 0)*scale:.2f} (n={s['n_available']})"
    for r in summaries:
        lines.append('|'+r['scenario']+'/'+r['profile']+'|'+'|'.join(fmt(r[k], scale) for k,scale in
                     [('trend_transitions',1),('false_events',1),('missed_events',1),
                      ('rise_delay_s',1000),('fall_delay_s',1000),('high_clear_s',1000)])+'|')
    lines += ['', '## 选择规则与结果', '',
              '- 所有参数预先固定。只用前5种子选择，后5种子验证；验证失败保持原基线，不用验证集另挑参数。',
              '- 每场景误激活/漏检不增加，两个实测假设的趋势切换均值不超过基线1.25倍，才满足选择资格。',
              '- 有资格者按匹配事件平均延迟选择；不通过减少有效帧、漏检或过滤失败试次换取更小延迟。',
              f"- 训练选择：{result['train_winner']}；留出验证：{'PASS' if result['heldout_pass'] else 'FAIL'}。",
              f"- 本批建议：{result['recommendation']}。未自动应用到任何默认配置或固件。", '',
              '## 解释边界', '',
              '- 每个真实事件最多匹配一次，0～800ms内的新鲜趋势进入算检测；提前激活、重复进入、事件外进入算额外事件，未匹配真事件算漏检。',
              '- 真事件时间采用模拟器预设3.0s施加载荷、4.6s卸载；斜坡也从开始变化计时，不从跨过5mA计时。',
              '- 误激活是相对于合成外部载荷真值的操作定义，不证明实测尖峰的物理成因。两种假设均保留。',
              '- 这次只改变趋势滤波与确认时间，等级、统计窗口、DOB估计、有效率和HIGH滞留应保持相同。',
              '- 四路是并行的只读分类分支，共用同一次控制/模型运行，不能宣称四倍独立电机实验。',
              '- 只验证软件分类；无闭环自适应、无硬件运行，不代表实机性能已验证。']
    (root/'RESULTS_ZH.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')


if __name__ == '__main__':
    p = argparse.ArgumentParser();p.add_argument('results', type=Path)
    report(p.parse_args().results)
