"""Reduce saved paired Simulink trials; no control/parameter/hardware writes."""
import csv
import gzip
import hashlib
import json
import math
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / 'simulation/dob_simulink/real_five'
OUT = ENV / 'feedback_aware_results'
METRICS = [
    'true_load_speed_mae_rpm', 'load_speed_mae_rpm', 'speed_dip_rpm',
    'speed_recovery_s', 'unload_overshoot_rpm', 'iq_peak_a',
    'integrator_peak_a', 'iq_saturation_s', 'false_comp_unloaded_rms_a',
    'compensation_cap_s', 'estimate_rmse_a', 'valid_rate', 'reset_calls',
    'feedback_recovery_s', 'feedback_confirmed_s',
]


def read_metrics(path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    text = {'scenario', 'case_name', 'profile', 'split'}
    return [{k: v if k in text else float(v) for k, v in r.items()} for r in rows]


def pair_stats(on, base, field):
    raw = [(r[field], base[r['case_name'], int(r['seed'])][field]) for r in on]
    # Failure to recover is an explicit missing metric, never replaced by a
    # favorable zero or silently removed from the trial population.
    pairs = [(a, b) for a, b in raw if math.isfinite(a) and math.isfinite(b)]
    if not pairs:
        return dict(n=len(raw), finite_pairs=0, missing_pairs=len(raw),
                    off_mean=math.nan, off_std=math.nan, on_mean=math.nan, on_std=math.nan,
                    delta_mean=math.nan, delta_std=math.nan, improved=0, worsened=0, tied=0)
    a, b = zip(*pairs)
    delta = [x - y for x, y in pairs]
    sd = lambda x: st.stdev(x) if len(x) > 1 else 0.0
    return dict(n=len(raw), finite_pairs=len(pairs), missing_pairs=len(raw)-len(pairs),
                off_mean=st.mean(b), off_std=sd(b), on_mean=st.mean(a), on_std=sd(a),
                delta_mean=st.mean(delta), delta_std=sd(delta),
                improved=sum(x < -1e-9 for x in delta),
                worsened=sum(x > 1e-9 for x in delta),
                tied=sum(abs(x) <= 1e-9 for x in delta))


def summarize(rows):
    base = {(r['case_name'], int(r['seed'])): r for r in rows if r['gain'] == 0}
    assert len(base) == 200
    summary = []
    for hyp in ['measurement', 'torque']:
        for split in ['all', 'tune', 'heldout']:
            for event in ['both', 'step', 'ramp']:
                for gain in [.15, .25, .5]:
                    for cap in [.00625, .0125, .025]:
                        rr = [r for r in rows if r['case_name'] == hyp and r['gain'] == gain and
                              r['cap_a'] == cap and
                              (split == 'all' or (r['seed'] <= 60) == (split == 'tune')) and
                              (event == 'both' or (int(r['seed']) % 2 == 1) == (event == 'step'))]
                        assert len(rr) == ({'all': 100, 'tune': 60, 'heldout': 40}[split] // (1 if event == 'both' else 2))
                        header = dict(hypothesis=hyp, split=split, event=event, gain=gain, cap_a=cap)
                        for field in METRICS:
                            summary.append(dict(**header, metric=field, **pair_stats(rr, base, field)))
    return summary


def select_tuning_candidate(rows):
    """Descriptive primary-MAE choice; never uses heldout seeds for selection.

    Require every tune trial to meet estimator/guard/limit gates. Minimize the
    worst hypothesis ratio of mean physical-speed MAE to its paired OFF mean.
    This is NOT a claim of all-metric dominance or a production calibration.
    """
    tune = [r for r in rows if r['seed'] <= 60]
    base = {(r['case_name'], int(r['seed'])): r for r in tune if r['gain'] == 0}
    candidates = []
    for gain in [.15, .25, .5]:
        for cap in [.00625, .0125, .025]:
            rr = [r for r in tune if r['gain'] == gain and r['cap_a'] == cap]
            eligible = all(r['feedback_gate_pass'] and not r['guard_faults'] and r['cap_obeyed'] and
                           r['total_limit_obeyed'] and r['finite'] for r in rr)
            ratios = {}
            for hyp in ['measurement', 'torque']:
                pp = [r for r in rr if r['case_name'] == hyp]
                v = pair_stats(pp, base, 'true_load_speed_mae_rpm')
                ratios[hyp] = v['on_mean'] / v['off_mean']
            candidates.append(dict(gain=gain, cap_a=cap, eligible=eligible,
                                   primary_worst_ratio=max(ratios.values()), hypothesis_ratios=ratios))
    allowed = [c for c in candidates if c['eligible']]
    selected = min(allowed, key=lambda c: (c['primary_worst_ratio'], c['cap_a'], c['gain'])) if allowed else None
    return dict(criterion='Tune seeds1..60 only; all estimator/limit/guard gates, then minimize worst-hypothesis ratio of mean physical-speed load MAE. No claim of Pareto dominance.',
                candidates=candidates, selected=selected)


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


def fmt(v):
    return f"{v['on_mean']:.4g} ± {v['on_std']:.3g}"


def make_report(rows, summary, choice, audit):
    selected = choice['selected']
    run = json.loads((OUT/'report.json').read_text())
    text = ['# DOB恢复指标放宽与100次/组软件扫描', '',
            '## 结论边界', '',
            '五轮实机固定短窗已采完，12V已关闭、原B启动选择已恢复。此后只运行MATLAB/Simulink，不烧录、不启动电机，不修改固件默认参数或保护。',
            '本轮复用200次原OFF，新增1800次ON：两种扰动假设 × 3种增益 × 3种补偿限幅 × 100种子。不是2000次实机实验，也不是100份独立实测负载。', '',
            '## 放宽了什么', '',
            '原“连续100ms每点有效”结果完整保留在../results；新指标单独保存。新鲜度≤2ms；缺口≤5ms允许原反馈保持并累计合格时间；5～20ms衰减期间暂停累计；≥20ms清空本次合格计时。新鲜但误差>8mA的估计仍清空计时。',
            '缺失/被隔离样本仍无效，绝不补记为有效测量；原DOB有效率分母、质量门控、预热、重置和控制反馈完全未变。8项回归通过，包括单点/短缺口、长缺口、持续偏差、过期数据和新鲜坏估计。',
            '恢复时间指最终合格区间的起点，确认时间还需累计100ms合格时长；两者分别保存在feedback_recovery_s和feedback_confirmed_s，不能混为“100ms内恢复”。', '',
            '## 输入及复现', '',
            '每轮实际数据仅192点×1ms；五窗共960点，来自240rpm空载稳态，不含有真值标注的外载。仿真把配对短窗按固定种子重排重复至6.5s，属于压力条件和平稳外推，不代表真实长时尖峰发生率。',
            'measurement假设把高频Iq残差当测量异常；torque假设把同一残差当真实电流/转矩扰动，且不再叠加相同速度高频项，避免重复计入。两种解释并未由独立传感器区分。曲线中的published estimate在无效发布帧为0，不代表真实扰动消失；必须联合dob_valid标记阅读。',
            '真实外载由仿真器独立生成20～60mA等效阶跃或200ms斜坡，4.6s卸载，绝不把DOB输出当ground truth。每个OFF/ON种子实际消费的输入逐点配对。',
            '前60种子只用实测窗1～3作调优，后40种子只用窗4～5作留出；奇数阶跃、偶数斜坡。均值/标准差反映这些假设下的种子变化，不是对真实电机的置信保证。', '',
            '机械模型使用rad/s：J/Kt=0.000386049 A·s²/rad、B/Kt=0.00155158 A·s/rad，库仑项0.1194516824A、偏置0.0005496600A。观测器名义参数与plant略有差别，原值均未调。',
            '速度PI、S曲线、Ka=0.000046875 A/(rpm/s)、摩擦前馈0.105A保持原值。正扰动表示阻转，补偿为+gain×估计，经独立cap、原slew及总Iq±0.50A限幅；cap不超过25mA。', '',
            '## 每组结果（100次，速度为仿真物理速度MAE）', '',
            '|假设|增益|限幅 mA|OFF MAE rpm|ON MAE rpm（均值±标准差）|配对变化 rpm|改善/恶化/持平|准入失败|',
            '|---|---:|---:|---:|---:|---:|---:|---:|']
    for s in summary:
        if s['split'] != 'all' or s['event'] != 'both' or s['metric'] != 'true_load_speed_mae_rpm':
            continue
        group = [r for r in rows if r['case_name'] == s['hypothesis'] and r['gain'] == s['gain'] and r['cap_a'] == s['cap_a']]
        fails = sum(not r['feedback_gate_pass'] for r in group)
        text.append(f"|{s['hypothesis']}|{s['gain']:g}|{s['cap_a']*1000:g}|{s['off_mean']:.4g}|{fmt(s)}|{s['delta_mean']:+.4g}|{s['improved']}/{s['worsened']}/{s['tied']}|{fails}/{len(group)}|")
    text += ['', '## 调优选择与独立留出', '', choice['criterion'], '']
    if selected:
        gain, cap = selected['gain'], selected['cap_a']
        text += [f'按上述单一主指标选出的软件候选：gain={gain:g}，cap={cap*1000:g}mA。未应用到固件，也不等于所有指标都最优。', '',
                 '|假设/分组|物理速度MAE OFF→ON rpm|跌速变化 rpm|卸载超调变化 rpm|峰值Iq变化 mA|空载误补偿 RMS mA|',
                 '|---|---:|---:|---:|---:|---:|']
        for hyp in ['measurement', 'torque']:
            for split in ['tune', 'heldout']:
                def get(metric):
                    return next(s for s in summary if s['hypothesis'] == hyp and s['split'] == split and
                                s['event'] == 'both' and s['gain'] == gain and s['cap_a'] == cap and s['metric'] == metric)
                v=get('true_load_speed_mae_rpm')
                text.append(f"|{hyp}/{split}|{v['off_mean']:.4g}→{v['on_mean']:.4g}|{get('speed_dip_rpm')['delta_mean']:+.4g}|{get('unload_overshoot_rpm')['delta_mean']:+.4g}|{get('iq_peak_a')['delta_mean']*1000:+.4g}|{get('false_comp_unloaded_rms_a')['on_mean']*1000:.4g}|")
        text += ['', '跌速/超调/峰值Iq/空载误补偿的正向变化都需视为代价，而非隐去；有效率按原DOB发布标志统计，没有因恢复标准放宽而虚增。',
                 '完整summary_paired_by_split.csv还包含阶跃/斜坡分别统计、速度恢复时间、积分峰值、饱和时间、估计RMSE和原始连续恢复指标。无法恢复等未定义指标单列missing_pairs，绝不填0或删除整轮；该行均值仅针对finite_pairs，需结合缺失数量阅读。primary_candidates.json记录所有候选的调优得分，未用留出数据反复选优。']
        if selected['primary_worst_ratio'] >= 1:
            text += ['', '**连最佳主指标候选也至少在一种调优假设下恶化；这只是网格中较小的最坏代价，不是可以替代OFF的统一改善方案。建议保持OFF，先核实尖峰的物理来源。**']
    else:
        text += ['没有满足全部调优质量/限幅条件的候选；保留所有失败轮，不给出生产参数建议。']
    text += ['', '## 自动检查', '',
             f"独立审计{audit['on_traces_checked']}份ON MAT，共{int(audit['on_rows_checked'])}行；与200份原OFF输入逐点配对，最大差{audit['maximum_input_abs_delta']:.3g}（容差1e-10，仅用于CSV序列化精度）。",
             f"隔离样本LPF前后相同检查{audit['quarantined_lpf_unchanged_checks']}次；有限值、总Iq和补偿cap检查通过；guard故障{audit['guard_fault_trials']}轮；新恢复准入失败{audit['feedback_gate_failed_trials']}轮。源码和原生控制二进制哈希未变。", '',
             '## 不能据此得出的结论 / 下一步', '',
             '本轮机械plant固定为一个名义模型，仅扫描补偿增益/限幅和条件化事件/噪声；没有扫描J/Kt、B/Kt等辨识不确定性，不能称为机械参数全范围鲁棒性验证。',
             '未验证真实拧紧接触/工件刚度、真实负载转矩、Kt绝对标定、实际电气FOC电流环、电压裕量/SVPWM、ADC/IRQ时序或硬件过流。电流lag为假设，不能用这些结果宣称真实电机DOB性能已验证。',
             '先审查两种尖峰假设下是否存在相反结论、卸载超调及空载误补偿代价；入选值仍需少量受控实机配对验证和独立负载记录，不能自动接入正式B。若只有测量假设改善，优先补齐尖峰物理来源证据。', '',
             '## 数据文件', '',
             '- metrics_per_trial.csv：200份复用OFF+1800份新ON的每轮指标。',
             '- summary_paired_by_split.csv：全体/调优/留出及阶跃/斜坡配对均值、标准差和改善轮数。',
             '- *.mat：所有1800次ON的完整逐点表T；固定seed1/61阶跃和seed2/62斜坡同时提供CSV（后者由独立审计补充）。原OFF完整CSV.gz仍在../results。',
             '- primary_candidates.json、independent_audit.json、report.json：选择规则、独立审计、源码/原生二进制固定哈希。',
             '- off_on_selected.svg/png：固定seed1/61的示例曲线（不是挑出的最好轮）；selection_tradeoffs.svg/png：全网格留出对照。', '']
    if run.get('storage_interruption'):
        text += ['## 存储中断及续跑证据', '',
                 f"原full进程在额外SDI缓存约4.24GB导致D盘空间不足后退出，留下{run['verified_saved_traces_reused']}份逐轮MAT（检查点仅1550轮）。原日志、检查点和每份已保存MAT的SHA-256均保留。",
                 'MATLAB退出后，只将明确属于本轮的单份SDI缓存复制到C盘工作区，SHA-256一致后移除D盘同一缓存；没有删除原始实机记录、逐轮MAT或严格结果。详见storage_interruption.json。',
                 f"续跑对已有{run['verified_saved_traces_reused']}份轨迹重新计算并核验，未重跑或覆盖；只新增缺失{run['new_simulations_after_resume']}次。已有轨迹若损坏/不合格会停止，不通过隐藏重试替换。最终1800份完整审计通过后才生成正式report.json。", '']
    return '\n'.join(text)


def main():
    rows=read_metrics(OUT/'metrics_per_trial.csv')
    assert len(rows)==2000
    audit=json.loads((OUT/'independent_audit.json').read_text())
    assert audit['passed'] and audit['on_traces_checked']==1800
    summary=summarize(rows);choice=select_tuning_candidate(rows)
    write_csv(OUT/'summary_paired_by_split.csv',summary)
    (OUT/'primary_candidates.json').write_text(json.dumps(choice,indent=2),encoding='utf-8')
    (OUT/'RESULTS_ZH.md').write_text(make_report(rows,summary,choice,audit),encoding='utf-8')
    pins={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
          [Path(__file__),OUT/'summary_paired_by_split.csv',OUT/'primary_candidates.json',OUT/'RESULTS_ZH.md']}
    (OUT/'reduction_manifest.json').write_text(json.dumps(pins,indent=2),encoding='utf-8')
    print(json.dumps(choice,indent=2))


if __name__=='__main__':
    main()
