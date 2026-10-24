"""Summarize saved Simulink repeated trials; no control/hardware operations."""
import csv
import hashlib
import json
from pathlib import Path
import statistics as st

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'simulation/dob_simulink/empirical/results'


def main():
    with (FOLDER/'metrics_per_trial.csv').open(newline='',encoding='utf-8-sig') as f:
        rows=list(csv.DictReader(f))
    def subset(case,gain,profile='nominal'):
        return [r for r in rows if r['case_name']==case and r['profile']==profile and float(r['gain'])==gain]
    def mean(rr,key,scale=1):return st.mean(float(r[key])*scale for r in rr)
    def fmt(rr,key,scale=1):
        vals=[float(r[key])*scale for r in rr]
        return f'{st.mean(vals):.5g} ± {st.stdev(vals):.3g}'
    report=json.loads((FOLDER/'report.json').read_text())
    audit=json.loads((FOLDER/'independent_audit.json').read_text())
    repeats=[]
    for file in sorted((FOLDER.parent/'smoke_results').glob('*_seed*.csv')):
        final=FOLDER/file.name
        if final.exists():
            same=hashlib.sha256(file.read_bytes()).digest()==hashlib.sha256(final.read_bytes()).digest()
            repeats.append({'file':file.name,'exact_csv_match':same})
    assert len(repeats)==20 and all(r['exact_csv_match'] for r in repeats)
    (FOLDER/'repeatability_check.json').write_text(json.dumps({'passed':True,'traces':repeats,
        'note':'Same seed/config CSV byte-identical across independent MATLAB batches; smoke not used for final statistics.'},indent=2),encoding='utf-8')
    text=['# 实测事件注入：DOB 效果与参数审查（仅离线仿真）','',
      f"MATLAB/Simulink 共 {report['trials']} 次正式运行，主要对照每组 5 个固定种子；模型敏感性每组 3 个种子。独立文件审计匹配 {audit['matched_pairs']} 对实际外生输入，检查 {audit['quarantined_frames_checked']} 个隔离帧未更新 LPF。",'',
      '另有20份相同种子/配置的CSV在两个独立MATLAB批次之间字节完全一致；调试批次只用于此重复性检查，最终统计仅采用正式124次运行。','',
      '未烧录、未连接硬件、未改变固件默认行为。以下是模型结果，不能作为真实电机或拧紧性能验证。','',
      '## 真实数据如何使用','',
      '两个历史触发窗口各40个连续配对 Id/Iq 点，约39ms；最大原始 |Id|≈699mA、|Iq|≈772mA。ELF/Flash/RAM/receipt来源核验通过。剔除稀疏尾部，不假设它们构成完整实测轨迹或自然尖峰发生率。',
      '实测 Iq 减局部五点中位数后，分别作为①仅测量扰动，②产生真实转矩的电流脉冲。后者是敏感性假设，并未证明尖峰实际产生转矩。真实外载由仿真器独立生成；不是 DOB 输出。','',
      '## 主对照：DOB gain=0.25，独立补偿限幅25mA','',
      '正向240rpm；均值 ± 样本标准差；每档5次。负载为40mA等效电流阶跃，并在4.6s卸载。不是600rpm/高速或实际拧紧工件验证。','',
      '|场景|负载段速度 MAE OFF→ON (rpm)|速度跌落 OFF→ON (rpm)|卸载超调 OFF→ON (rpm)|',
      '|---|---|---|---|']
    for case in ['nominal','measured_once','measurement_train','torque_train']:
        off,on=subset(case,0),subset(case,.25)
        text.append(f"|{case}|{fmt(off,'load_speed_mae_rpm')} → {fmt(on,'load_speed_mae_rpm')}|{fmt(off,'speed_dip_rpm')} → {fmt(on,'speed_dip_rpm')}|{fmt(off,'unload_overshoot_rpm')} → {fmt(on,'unload_overshoot_rpm')}|")
    physical_off,physical_on=subset('torque_train',0),subset('torque_train',.25)
    delta=(mean(physical_on,'load_speed_mae_rpm')/mean(physical_off,'load_speed_mae_rpm')-1)*100
    text+=['',f'**未通过的性能项：真实转矩脉冲假设下，gain=0.25负载段误差平均恶化{delta:.2f}%，速度跌落也增大。估计准入通过≠闭环性能通过，不能宣布DOB普遍有效。**','',
      '估计器独立验证（OFF，评估窗口2.3–6.9s，不含启动预热）：','',
      '|场景|估计 RMSE (mA)|有效率 (%)|最长连续无效 (ms)|重置次数|', '|---|---|---|---|---|']
    for case in ['nominal','measured_once','measurement_train','torque_train','unloaded_stress']:
        rr=subset(case,0)
        text.append(f"|{case}|{fmt(rr,'estimate_rmse_a',1000)}|{fmt(rr,'valid_rate',100)}|{fmt(rr,'longest_invalid_ms')}|{fmt(rr,'reset_calls')}|")
    text+=['','## 增益不是越大越好','',
      '|gain|成串测量尖峰+外载：速度 MAE (rpm)|空载压力：速度 MAE (rpm)|空载误补偿 RMS (mA)|成串外载：补偿触顶时间 (s)|', '|---|---|---|---|---|']
    for g in [0,.25,.5,1]:
        rr=subset('measurement_train',g);un=subset('unloaded_stress',g)
        text.append(f"|{g}|{fmt(rr,'load_speed_mae_rpm')}|{fmt(un,'speed_mae_rpm')}|{fmt(un,'false_comp_unloaded_rms_a',1000)}|{fmt(rr,'compensation_cap_s')}|")
    text+=['','## 模型假设敏感性','',
      '轻/快模型：J/Kt×0.7、B/Kt×0.9、电流执行器tau=0.5ms；重/慢模型：×1.3、×1.1、tau=2ms。原 C 控制器与 DOB 模型参数不变。这是有限假设扫描，不是参数置信区间或鲁棒稳定性证明。','',
      '|模型|场景|OFF估计准入|负载段 MAE OFF→ON (rpm)|', '|---|---|---|---|']
    for profile in ['lighter_faster','heavier_slower']:
        for case in ['measurement_train','torque_train']:
            off,on=subset(case,0,profile),subset(case,.25,profile)
            gate=next(g['passed'] for g in report['estimator_gates'] if g['scenario']==case and g['profile']==profile)
            text.append(f"|{profile}|{case}|{gate}|{fmt(off,'load_speed_mae_rpm')} → {fmt(on,'load_speed_mae_rpm') if on else '未运行（准入失败）'}|")
    text+=['','## 参数判断','',
      '- 增益0.25、独立25mA限幅、总Iq±0.50A可继续保留为保守候选。较高增益在理想负载阶跃模型中误差更小，但空载误补偿更大；不能据此自动升增益。',
      '- DOB带宽2Hz（12.566rad/s）：单极点50%响应约55ms，5/g预热约398ms；另有20ms匹配滤波。适于较慢负载估计，不能消除1ms级真实转矩脉冲。',
      '- 200mA是相对可信配对样本的跳变门限，不是物理电流上限；60mA滤波Id+20ms持续异常是质量门控，不是硬件过流保护。本次数据支持“大单点先隔离、短缺口不硬重置”，不支持断言这些门限已最优。',
      '- J/Kt、B/Kt只支持等效电流模型；不能直接当作已标定的绝对J、B、Kt。电流执行器时间常数、真实负载和尖峰成因尚未独立标定。','',
      '## 与已有实机结果的边界','',
      '既有600rpm空载OFF/ON各5次：加速MAE 7.70189±0.91774→7.52873±0.88978rpm，匀速2.25717→2.25699rpm，超调5.51954→5.72614rpm，实际补偿峰值约4.86mA。加速差异远小于轮间波动，且配对方向混合：尚未证明可重复的真实跟踪改善。见 docs/dob-feedback-repeat5-20261023.md。不要用本次仿真替代这个结论。','',
      '## 限制与下一步','',
      '所有正式运行检查有限值、总命令限幅、独立补偿限幅、隔离时LPF不变，以及同种子OFF/ON实际外生输入完全一致。物理电流脉冲假设可能超过命令限幅；没有建模硬件过流、电气FOC、电压裕量、采样/IRQ实时行为，不能认定硬件可执行或安全。',
      '持续Id异常、源数据缺口和电压饱和等合成场景的回归见上层 simulation/dob_simulink/results/RESULTS.md；本轮真实触发窗口不足以确认这些事件的实际发生率。',
      '当前扩展未加入完整 tightening FSM/真实螺钉接触模型。下一阶段应独立建立接触位置随机、软/硬连接、卡滞/卸载的负载模型，再验证 CONTACT/TIGHTEN/HOLD 转换，不改变原固件默认参数。',
      '在没有可运行平台时，结论停在离线一致性和假设敏感性；未来需要长时连续同帧原始数据及独立外载信息，才能判断真实负载补偿和门限是否合理。','',
      '## 可复现结果','',
      '- 每次输入/控制/真值：本目录 CSV。',
      '- metrics_mean_std.csv、paired_on_minus_off.csv：重复统计和配对差异。',
      '- estimator_gates.json、independent_audit.json、report.json：准入、独立审计与源码冻结。',
      '- off_on_curves.svg/png、spike_isolation.svg/png：由保存的 Simulink CSV 后处理生成。','']
    (FOLDER/'RESULTS_ZH.md').write_text('\n'.join(text),encoding='utf-8')
    provenance={str(Path(__file__).relative_to(ROOT)):hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'tools/plot_dob_empirical.py':hashlib.sha256((ROOT/'tools/plot_dob_empirical.py').read_bytes()).hexdigest(),
                'metrics_per_trial.csv':hashlib.sha256((FOLDER/'metrics_per_trial.csv').read_bytes()).hexdigest()}
    (FOLDER/'reduction_manifest.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    print(f'{len(rows)} trials summarized')


if __name__=='__main__':main()
