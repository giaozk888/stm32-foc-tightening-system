"""Independent files-only reduction of twenty actual unloaded motor trials."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct
import dob_gain_ab_twenty_board as b


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def analyze(path):
    parent=json.loads(path.read_text())
    assert parent['pass_'] and parent['acquisition_complete'] and parent['schedule']==list(b.SCHEDULE)
    assert len(parent['runs'])==20 and len(parent['attempts'])==20
    if parent.get('manual_resume_authorized'):
        assert digest(parent['resume_original_batch'])==parent['original_batch_sha256']
        original=json.loads(Path(parent['resume_original_batch']).read_text())
        interrupted=json.loads(Path(parent['interrupted_no_start_receipt']).read_text())
        assert len(original['runs'])==9 and parent['runs'][:9]==original['runs']
        assert original['last_run']==parent['interrupted_no_start_receipt'] and interrupted['start_attempts']==0
        assert interrupted['final_outputs_off'] and interrupted['final_cpu_halted']
        assert [p['receipt'] for p in parent['reused_run_hashes']]==original['runs']
        for pin in parent['reused_run_hashes']:assert digest(pin['receipt'])==pin['sha256']
    baseline=json.loads(Path(parent['baseline_restore_receipt']).read_text())
    base=Path(baseline['final_capture']).read_bytes()
    assert digest(baseline['final_capture'])==baseline['final_sha256']
    image=b.image();symbols=b.base.symbols(b.ELF);address,size=symbols['dob_gain_ab'];assert size==4
    rows=[];per_run=[];pins=[]
    for i,receipt in enumerate(parent['runs']):
        r=json.loads(Path(receipt).read_text());gain=b.SCHEDULE[i]
        assert r['pass_'] and r['start_attempts']==1 and r['dob_gain_requested']==gain
        assert r['image_sha256']==b.SHA and r['elf_sha256']==b.ELF_SHA
        assert r['actual_gain_ram']==gain and r['gain_selection']['GAIN_PPM']==str(round(gain*1e6))
        b.normal.classify(r) # Original protection, timing and shutdown gates.
        flash=Path(r['final_capture']).read_bytes();ram=Path(r['ram_capture']).read_bytes()
        assert digest(r['final_capture'])==r['final_sha256']
        assert flash[0x8000:0x8000+len(image)]==image
        assert flash[:0x8000]==base[:0x8000] and flash[0x40000:0x7e800]==base[0x40000:0x7e800] and flash[0x7f800:]==base[0x7f800:]
        assert struct.unpack_from('<f',ram,address-0x20000000)[0]==gain
        assert digest(r['ram_capture'])==r['raw_capture']['ram_sha256']
        if r['raw_capture']['csv']:
            assert digest(r['raw_capture']['csv'])==r['raw_capture']['csv_sha256']
        m=b.metrics(r)
        assert m['iq_command_peak_a']<=.5+1e-7 and m['comp_peak_a']<=.025+1e-7
        per_run.append(dict(trial=i+1,gain=gain,receipt=receipt,raw_window_quality=r['raw_capture']['quality_pass'],**m))
        rows.append(r);pins.append(dict(receipt=receipt,sha256=digest(receipt),flash_sha256=r['final_sha256'],ram_sha256=digest(r['ram_capture'])))
    summary=b.summarize(rows);pairs=summary['pairs'];pair_stats={}
    for key in b.metrics({}):
        values=[p['gain050_minus_gain025'][key] for p in pairs if p['gain050_minus_gain025'][key] is not None]
        pair_stats[key]=dict(n=len(values),mean=statistics.mean(values) if values else None,
            sd=statistics.stdev(values) if len(values)>1 else None,
            lower=sum(v<0 for v in values),higher=sum(v>0 for v in values),equal=sum(v==0 for v in values))
    sensitivity={}
    if parent.get('manual_resume_authorized'):
        assert parent.get('reused_runs')==9 and parent.get('new_runs_planned')==11 and parent.get('pairing_pause_after_trial')==9
        for label,selected in [('exclude_pause_pair5',[p for p in pairs if p['pair']!=5]),
                               ('before_pause_pairs1to4',[p for p in pairs if p['pair']<5]),
                               ('after_pause_pairs6to10',[p for p in pairs if p['pair']>5])]:
            sensitivity[label]={}
            for key in b.metrics({}):
                values=[p['gain050_minus_gain025'][key] for p in selected if p['gain050_minus_gain025'][key] is not None]
                sensitivity[label][key]=dict(n=len(values),mean=statistics.mean(values) if values else None,
                    sd=statistics.stdev(values) if len(values)>1 else None,
                    lower=sum(v<0 for v in values),higher=sum(v>0 for v in values))
    out=path.with_suffix('.comparison.json');summary.update(pair_stats=pair_stats,independent_audit_pass=True,
        hardware_commands=0,source_receipt_hashes=pins,usable_fixed_windows=sum(r['raw_capture']['quality_pass'] for r in rows))
    if sensitivity:
        summary.update(manually_resumed_after_trial9=True,pause_pair5_sensitivity=sensitivity,
            source_interrupted_batch=parent['resume_original_batch'],
            interrupted_no_start_receipt=parent['interrupted_no_start_receipt'],total_actual_start_runs=20,
            extra_boot_attempt_without_start=1)
    out.write_text(json.dumps(summary,indent=2),encoding='utf-8')
    csvpath=path.with_suffix('.metrics.csv')
    with csvpath.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(per_run[0]));w.writeheader();w.writerows(per_run)
    keys=[('accel_mae_rpm','加速MAE rpm',1),('cruise_mae_rpm','匀速MAE rpm',1),
          ('low_mae_rpm','低速MAE rpm',1),('overshoot_rpm','超调 rpm',1),
          ('iq_command_peak_a','Iq命令峰值 mA',1000),('integrator_peak_a','积分器峰值 mA',1000),
          ('comp_peak_a','DOB补偿峰值 mA',1000),('iq_saturation_s','Iq饱和时间 s',1),
          ('dob_valid_fraction','整轮DOB有效率 %',100),('fixed_window_speed_mae_rpm','固定短窗速度MAE rpm',1)]
    lines=['# 实机DOB增益0.25 / 0.5各10次空载对照','',
        '同一诊断A、240rpm、两组交替各10轮；补偿cap±25mA、总Iq±0.50A，原PI/轨迹/前馈/保护不变。每轮原预检通过，一次START，原8秒空载RUNDOWN_TIMEOUT，不是拧紧成功。无制动器施加载荷、无独立负载真值。','',
        '## 每组均值±样本标准差；配对差为0.5−0.25','',
        '|指标|0.25（10轮）|0.5（10轮）|配对差均值±SD|下降/上升/相同|',
        '|---|---:|---:|---:|---:|']
    for key,label,scale in keys:
        a=summary['groups']['0.25']['metrics'][key];z=summary['groups']['0.5']['metrics'][key];p=pair_stats[key]
        def fmt(v):return '不可用' if v['mean'] is None else f"{v['mean']*scale:.5g} ± {(v['sd'] or 0)*scale:.4g}"
        lines.append(f"|{label}|{fmt(a)}|{fmt(z)}|{fmt(p)}|{p['lower']}/{p['higher']}/{p['equal']}|")
    lines += ['', '## 每一轮', '', '|轮次|增益|加速MAE rpm|匀速MAE rpm|超调 rpm|补偿峰值 mA|', '|---|---:|---:|---:|---:|---:|']
    for r in per_run:
        lines.append(f"|{r['trial']}|{r['gain']}|{r['accel_mae_rpm']:.5f}|{r['cruise_mae_rpm']:.5f}|{r['overshoot_rpm']:.5f}|{r['comp_peak_a']*1000:.4f}|")
    if sensitivity:
        lines += ['', '## 人工停机与配对敏感性', '',
            '前9轮后主机被中断，原第10次boot预检未发START，安全关断后人工要求补齐；前9轮保留，只新增11轮。原中断批次/零START尝试保留，不算成完成的运动试验。',
            '第5对（第9轮0.25／第10轮0.5）跨越人工关电/重上电间隔，不能当作同一热状态的紧邻试验。下表为0.5−0.25的配对差：', '',
            '|配对集合|对数|加速MAE差 rpm|匀速MAE差 rpm|超调差 rpm|',
            '|---|---:|---:|---:|---:|']
        for label,stats in sensitivity.items():
            def number(k):return '不可用' if stats[k]['mean'] is None else f"{stats[k]['mean']:+.5f} ± {(stats[k]['sd'] or 0):.4g}"
            lines.append(f"|{label}|{stats['accel_mae_rpm']['n']}|{number('accel_mae_rpm')}|{number('cruise_mae_rpm')}|{number('overshoot_rpm')}|")
        lines += ['', '所有10对全体统计与9对排除跨停机统计均报告；若停机前后方向不同，不能把总均值包装成稳定改善。']
    lines += ['', '## 通过与限制', '',
        '- 独立文件审计：20轮实际gain RAM/命令回读匹配、Flash/RAM/CSV哈希、B/boot/config保留、原故障/时序/关断检查及Iq/补偿限幅全部通过。',
        f"- 固定192ms窗口质量通过{summary['usable_fixed_windows']}/20。短窗不是整轮完整原始波形，也不是负载真值；完整加速/匀速指标来自原固件积分统计。", 
        '- 下降/上升只是数值方向，非所有指标都以下降为好（例如DOB有效率）。原始电流尖峰不是独立真实电流测量，不能用来断言命令限幅失效。',
        '- 主指标看加速/匀速跟踪误差，不把stable确认时间当起转物理延迟。10对虽交替但顺序未随机化，温度/机械漂移未独立测量；不能把均值差自动当作因果或统计显著差。',
        '- 空载结果不能证明负载抑制或实际拧紧性能，不能用本轮自动替换正式0.25或推广到其他速度/负载。',
        '- 本报告只读已保存文件，不运行电机、不恢复启动选择。是否已关12V/恢复B，必须另看人工确认及restore receipt，不能由本报告推断。','',
        f"原批次：{path}",f"逐轮CSV：{csvpath}",f"配对/审计JSON：{out}",'']
    md=path.with_suffix('.report.md');md.write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(dict(report=str(md),groups=summary['groups'],pair_stats=pair_stats),indent=2))
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('batch',type=Path)
    analyze(parser.parse_args().batch)
