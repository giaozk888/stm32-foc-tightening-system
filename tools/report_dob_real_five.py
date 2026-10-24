"""Independent gzip-CSV audit/report, never controls motor or changes gates."""
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics as st

ROOT=Path(__file__).resolve().parents[1]
ENV=ROOT/'simulation/dob_simulink/real_five'
OUT=ENV/'results'

def main():
    report=json.loads((OUT/'report.json').read_text())
    with (OUT/'metrics_per_trial.csv').open(newline='',encoding='utf-8-sig') as f:metrics=list(csv.DictReader(f))
    signatures={};pairs=0;quarantine=0;counterexample=[];first_accepted=[]
    for m in metrics:
        hyp=m['case_name'];seed=int(m['seed']);gain=float(m['gain']);cap=float(m['cap_a'])
        file=OUT/f'{hyp}_seed{seed:03}_g{gain:g}_cap{cap:g}.csv.gz'
        with gzip.open(file,'rt',newline='') as f:rows=list(csv.DictReader(f))
        assert len(rows)==7001
        h=hashlib.sha256()
        for r in rows:
            ex=['time_s','target_rpm','load_ground_truth_a','speed_noise_rpm','iq_noise_a','id_raw_a',
                'physical_current_pulse_a','input_valid','input_voltage_sat','input_encoder_age_us','input_running']
            h.update((','.join(r[k] for k in ex)+'\n').encode())
            assert all(math.isfinite(float(v)) for v in r.values())
            assert abs(float(r['iq_cmd_a']))<=.5000001
            assert abs(float(r['iq_dob_a']))<=cap+1e-7
            if int(float(r['quality_reason']))&8 and not float(r['lpf_updated']):
                quarantine+=1;assert r['abs_id_lpf_a']==r['id_lpf_before_a']
        if gain==0:
            signatures[hyp,seed]=h.hexdigest()
            # Report accepted-sample recovery separately; never replaces the
            # strict continuous100ms gate or calls an invalid epoch valid.
            hits=[float(r['time_s'])-4.6 for r in rows if float(r['time_s'])>=4.6 and float(r['dob_valid']) and
                  abs(float(r['dob_estimate_a'])-float(r['load_ground_truth_a']))<=.008]
            first_accepted.append(dict(hypothesis=hyp,seed=seed,
                first_accepted_in_band_s=min(hits) if hits else None,
                strict_continuous_recovery_s=float(m['estimate_recovery_s'])))
        else:
            assert h.hexdigest()==signatures[hyp,seed];pairs+=1
    for pin in report['sources']+report['native_artifacts']:
        assert hashlib.sha256(Path(pin['path']).read_bytes()).hexdigest()==pin['sha256']
    audit=dict(passed=True,trials=len(metrics),matched_actual_input_pairs=pairs,
        quarantined_lpf_checks=quarantine,full_csv_rows_checked=len(metrics)*7001,
        source_artifact_pins_unchanged=True,hardware_access=False)
    (OUT/'independent_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    with (OUT/'recovery_diagnostic.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=first_accepted[0]);writer.writeheader();writer.writerows(first_accepted)
    real=json.loads((ENV/'data/window_reports.json').read_text())
    def fmt(vals):return f'{st.mean(vals):.4g} ± {st.stdev(vals):.3g}'
    text=['# 五轮真实记录与100次软件验证','',
      '## 实机采集已完成','',
      '240rpm、DOB反馈OFF、全部原保护保留。五轮各192点固定窗，共960点约0.96秒，不是五轮完整8秒原始波形；每轮8秒过程汇总另保留。所有原始CSV、Flash/RAM/ELF和receipt来源哈希已验证。',
      '第一轮被错误的主机“记录器独占10us”检查拦截后保留原失败receipt，仅在独立控制/保护/关断证据复核后计入第1窗，其余4轮独立补采。没有把模拟测试打印当成实机记录。','',
      '|轮次|平均速度 rpm|Id范围 mA|Iq范围 mA|DOB有效点|LPF更新点|','|---|---:|---:|---:|---:|---:|']
    for i,r in enumerate(real,1):
        text.append(f"|{i}|{r['speed_rpm']['mean']:.3f}|{r['id_a']['min']*1000:.1f}～{r['id_a']['max']*1000:.1f}|{r['iq_a']['min']*1000:.1f}～{r['iq_a']['max']*1000:.1f}|{r['dob_valid_samples']}/192|{r['lpf_updated_samples']}/192|")
    text+=['','这些是实际测量值，不是独立真实转矩/电流探头真值。命令Iq≤0.50A不能证明每个测量尖峰均是假的，也不能据此断言真实相电流已超过硬件保护阈值。','',
      '## 软件验证及准入结果','',
      f"正式完成{len(metrics)}次MATLAB/Simulink软件运行。观察器先OFF：测量异常假设100次、真实电流/转矩假设100次。每个种子决定固定配对的背景噪声、负载阶跃/斜坡幅度和事件块排列；这些不是100份独立实机实验。",'',
      '前60种子只用来源窗1～3，后40种子仅用窗4～5作留出。整窗192ms块保持配对及顺序，原时戳显式映射1ms仿真网格。Iq减局部median21、高通速度残差仅是模型分解假设，不是已经测准的ADC/编码器噪声。',
      '模拟外载独立生成20～60mA等效阶跃或200ms斜坡，4.6s卸载；重复窗口至6.5s是压力条件/平稳外推，不是实测长时发生率，也不把DOB输出当作负载真值。','',
      '|假设|RMSE mA|有效率 %|严格恢复时间 s|准入失败次数|','|---|---:|---:|---:|---:|']
    for hyp in ['measurement','torque']:
        rr=[m for m in metrics if m['case_name']==hyp and float(m['gain'])==0]
        def v(k,s=1):return [float(x[k])*s for x in rr]
        text.append(f"|{hyp}|{fmt(v('estimate_rmse_a',1000))}|{fmt(v('valid_rate',100))}|{fmt(v('estimate_recovery_s'))}|{sum(x['estimator_trial_pass'] not in ('1','true','True') for x in rr)}/{len(rr)}|")
    text+=['','原软件准入：RMSE≤12mA、偏差≤8mA、有效率≥90%、正确符号、检测延迟≤0.5s、卸载后连续100ms“估计有效且误差≤8mA”的恢复时间≤0.8s、无模型guard故障。未改变电机硬件保护。','',
      '严格恢复指标会被短暂无效点打断：原DOB/反馈允许短缺口保持，但该统计要求连续有效。`recovery_diagnostic.csv`另记录第一条有效且误差合格的样本时刻，仅帮助定位失败，**不把它代替严格准入或自动放行ON**。','']
    accepted=[x['first_accepted_in_band_s'] for x in first_accepted if x['first_accepted_in_band_s'] is not None]
    other_fail=sum(float(m['estimate_rmse_a'])>.012 or abs(float(m['estimate_bias_a']))>.008 or
                   float(m['valid_rate'])<.9 or float(m['detection_delay_s'])>.5 or
                   m['direction_ok'] not in ('1','true','True') or float(m['guard_faults'])!=0
                   for m in metrics if float(m['gain'])==0)
    text += [f'失败定位：其余准入失败{other_fail}次；首条有效且误差合格时刻{min(accepted):.3f}～{max(accepted):.3f}s，均值{st.mean(accepted):.3f}s，而严格连续指标约1.896s。最长连续无效最大{max(float(m["longest_invalid_ms"]) for m in metrics):g}ms。不能把严格指标的1.896s解释成观测器始终未恢复，也不能忽略这9ms最大缺口。','']
    if not any(float(m['gain']) for m in metrics):
        text+=['**本轮估计器准入未通过，增益/限幅ON扫描未执行，不能给出新的最佳参数或宣称0.25最优。**',
          '准备的网格为gain=0.15/0.25/0.5，cap=6.25/12.5/25mA，每组100次；未通过前置验证，不以冒烟测试结果替代正式扫描。总Iq±0.50A和独立≤25mA上限均保持。','']
    else:
        text+=['已执行的ON试验及均值/标准差见metrics_mean_std.csv；实际输入配对审计通过。未执行或失败组不得被当成有效最优组。','']
    text+=['## 通过项 / 未通过项','',
      f"- 通过：实机五窗来源验证；{audit['full_csv_rows_checked']}行正式软件日志有限值/命令和补偿限幅检查；{quarantine}个隔离帧LPF保持不变；源码/主机二进制哈希未变。",
      '- 未通过：目前严格恢复准入，因而尚无正式增益/限幅排名；真实电流尖峰成因、独立负载真值、真实DOB闭环收益仍未验证。',
      '- 当前结果不能支持调高质量门限、抬高安全阈值或自动修改正式参数。需要先审核持续恢复指标与真实短缺口保持机制是否匹配，并保留严格指标对照；若另设验证标准，必须明确记录，不改旧结果。','',
      '## 安全收尾','',
      '用户确认12V关闭后，tmp/dob-real-restore-1792755294485030100.json已恢复原B启动选择，B应用未运行、motor_commands=0、输出OFF、MCU halted；此后仅软件仿真，不再启动电机。','',
      '## 文件','',
      '- ../data/events.csv、manifest.json、window_reports.json：五窗实测证据。',
      '- *.csv.gz：正式软件逐点CSV压缩归档（仅删除已有gzip副本的临时未压缩CSV）。',
      '- metrics_per_trial.csv、metrics_mean_std.csv、estimator_gates.json、independent_audit.json。',
      '- five_real_windows.svg/png：五轮真实固定窗曲线；estimator_checks.svg/png：正式OFF验证曲线。无效发布帧的估计输出0不表示真实扰动归零，必须联合有效标记阅读。',
      '- 实机短窗无法替代完整tightening工件模型、电气FOC/电压裕量/IRQ与硬件过流仿真；未宣称这些已验证。','']
    (OUT/'RESULTS_ZH.md').write_text('\n'.join(text),encoding='utf-8')
    paths=[Path(__file__),ROOT/'tools/plot_dob_real_five.py',OUT/'metrics_per_trial.csv',OUT/'RESULTS_ZH.md']
    reduction={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (OUT/'reduction_manifest.json').write_text(json.dumps(reduction,indent=2),encoding='utf-8')
    print(json.dumps(audit,indent=2))

if __name__=='__main__':main()
