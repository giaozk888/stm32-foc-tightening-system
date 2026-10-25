"""Independent files-only audit of actual-C Simulink classification replay."""
import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct
from report_dob_trend_scan import episode_onsets,match_events
from prepare_dob_window_scan import ROOT

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stats(values):
    v=[x for x in values if x is not None and math.isfinite(x)]
    return dict(n=len(v),mean=statistics.mean(v) if v else None,sd=statistics.stdev(v) if len(v)>1 else None)
def metrics(rows,m,r,w):
    t=[x['time_s'] for x in rows];p='w'+str(w)+'_'
    trend=[int(x[p+'trend']) for x in rows];valid=[bool(x[p+'trend_valid']) for x in rows]
    level=[int(x[p+'level']) for x in rows];lv=[bool(x[p+'level_valid']) for x in rows]
    start,end=m['eval_s'];event=m['event_s'];unload=m['unload_s'];limit=m['event_match_max_s']
    has_load=any(abs(x['load_ground_truth_a'])>.005 for x in rows)
    has_unload=has_load and any(x['time_s']>=unload and abs(x['load_ground_truth_a'])<.001 for x in rows)
    rise=match_events(episode_onsets(t,trend,valid,2,start,end),[event] if has_load else [],limit)
    fall=match_events(episode_onsets(t,trend,valid,3,start,end),[unload] if has_unload else [],limit)
    mask=[i for i,x in enumerate(t) if start<=x<end]
    high=[i for i in mask if abs(rows[i]['load_ground_truth_a'])>=.025]
    light=[i for i in mask if abs(rows[i]['load_ground_truth_a'])<=.010]
    fraction=lambda x:statistics.mean(x) if x else None
    delays=rise['delays']+fall['delays']
    level_reset=rows[-1][p+'resets']
    # No load truth from the board is inferred. Real* data remains software
    # measurement/current hypotheses with independent simulated external load.
    return dict(scenario=r['scenario'],seed=r['seed'],split='train' if r['seed']<=5 else 'heldout',window_ms=w,
        min_good=w*6//10,min_span_ms=w*.6,
        trend_valid_rate=fraction([valid[i] for i in mask]),level_valid_rate=fraction([lv[i] for i in mask]),
        level_changes=rows[-1][p+'level_changes'],trend_changes=rows[-1][p+'trend_changes'],quality_resets=level_reset,
        rise_hits=rise['hits'],rise_fp=rise['false'],rise_miss=rise['misses'],
        fall_hits=fall['hits'],fall_fp=fall['false'],fall_miss=fall['misses'],
        false_events=rise['false']+fall['false'],missed_events=rise['misses']+fall['misses'],
        rise_delay_ms=statistics.mean(rise['delays'])*1000 if rise['delays'] else None,
        fall_delay_ms=statistics.mean(fall['delays'])*1000 if fall['delays'] else None,
        matched_delay_ms=statistics.mean(delays)*1000 if delays else None,
        high_recall=fraction([lv[i] and level[i]==4 for i in high]),
        false_high_rate=fraction([lv[i] and level[i]==4 for i in light]))

def audit(file,run,m):
    assert sha(run['original'])==run['original_sha256'] and sha(run['input'])==run['input_sha256']
    binary=Path(run['input']).read_bytes();expected=list(struct.iter_unpack('<8d',binary))
    with gzip.open(file,'rt',newline='') as f:rows=[{k:float(v) for k,v in row.items()} for row in csv.DictReader(f)]
    assert len(rows)==run['rows']==7001
    active_calls=0
    for index,row in enumerate(rows):
        active_calls+=int(row['target_rpm']!=0 and row['simulation_guard_fault']==0)
        assert all(math.isfinite(x) for x in row.values())
        # MATLAB CSV rendering may round the original binary double's last
        # digits. The hashed binary is the model input; tolerate print-only loss.
        assert all(math.isclose(row[k],v,rel_tol=5e-14,abs_tol=1e-12)
            for k,v in zip(m['input_columns'],expected[index])),'Replay inputs changed'
        assert abs(row['time_s']-index*.001)<1e-9
        for w in m['windows_ms']:
            p='w'+str(w)+'_'
            assert row[p+'level'] in (0,1,2,4) and row[p+'trend'] in (0,1,2,3)
            assert row[p+'level_valid'] in (0,1) and row[p+'trend_valid'] in (0,1)
            assert not row[p+'trend_valid'] or row[p+'level_valid']
            assert 0<=row[p+'coverage']<=1.000001
            assert row[p+'accepted']+row[p+'rejected']==active_calls
            if index and not row['dob_valid']:
                assert not row[p+'level_valid'] and not row[p+'trend_valid']
                previous=rows[index-1]
                if row[p+'resets']==previous[p+'resets']:
                    for name in ('mean_a','filtered_slope_a_s','trend_dwell_ms'):
                        assert row[p+name]==previous[p+name],name+' changed on invalid epoch'
    return rows

def eligibility(rows,w,split):
    tests={};scenarios=sorted({r['scenario'] for r in rows})
    for s in scenarios:
        select=lambda v:[r for r in rows if r['scenario']==s and r['window_ms']==v and (split=='all' or r['split']==split)]
        a,b=select(100),select(w)
        tests[s+'_no_extra_fp']=sum(r['false_events'] for r in b)<=sum(r['false_events'] for r in a)
        tests[s+'_no_extra_miss']=sum(r['missed_events'] for r in b)<=sum(r['missed_events'] for r in a)
        tests[s+'_valid_not_worse']=statistics.mean(r['trend_valid_rate'] for r in b)>=statistics.mean(r['trend_valid_rate'] for r in a)-1e-9
        if s.startswith('real_'):
            for key in ('trend_changes','level_changes'):
                tests[s+'_'+key+'_bound']=statistics.mean(r[key] for r in b)<=1.25*statistics.mean(r[key] for r in a)
    lat=[r['matched_delay_ms'] for r in rows if r['window_ms']==w and (split=='all' or r['split']==split)]
    return dict(eligible=all(tests.values()),failed=[k for k,v in tests.items() if not v],checks=tests,latency=stats(lat))

def report(root,require_input_tap=True,repeat_reference=None):
    m=json.loads((root/'manifest.json').read_text());done=json.loads((root/'report.json').read_text())
    assert done['completed'] and done['model_runs']==130 and done['classification_evaluations']==520
    if require_input_tap:assert done.get('consumed_input_verified') is True
    for key in ('original_c','original_h'):
        original=Path(m[key]);saved=root/'firmware_sources'/original.name
        if sha(original)!=m[key+'_sha256'] and saved.is_file():original=saved
        assert sha(original)==m[key+'_sha256'],'Frozen classifier source missing'
    assert m['trend_tau_ms']==100 and m['trend_dwell_ms']==80 and m['level_dwell_ms']==30
    rows=[];audits=[]
    for run in m['runs']:
        file=root/f"{run['scenario']}_seed{run['seed']:03d}.csv.gz"
        trace=audit(file,run,m)
        rows.extend(metrics(trace,m,run,w) for w in m['windows_ms'])
        audits.append(dict(file=str(file),sha256=sha(file),rows=len(trace)))
    with (root/'metrics_per_trial.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
    keys=['trend_valid_rate','level_valid_rate','level_changes','trend_changes','quality_resets',
          'rise_delay_ms','fall_delay_ms','high_recall','false_high_rate']
    summaries=[]
    for s in sorted({r['scenario'] for r in rows}):
        for w in m['windows_ms']:
            group=[r for r in rows if r['scenario']==s and r['window_ms']==w];assert len(group)==10
            summary=dict(scenario=s,window_ms=w,**{k:stats([r[k] for r in group]) for k in keys})
            summary.update({k:sum(r[k] for r in group) for k in ('rise_hits','rise_fp','rise_miss','fall_hits','fall_fp','fall_miss')})
            summaries.append(summary)
    selection={str(w):{s:eligibility(rows,w,s) for s in ('train','heldout','all')} for w in m['windows_ms']}
    trained=[w for w in m['windows_ms'] if selection[str(w)]['train']['eligible']]
    ranked=sorted(trained,key=lambda w:selection[str(w)]['train']['latency']['mean'] or float('inf'))
    proposed=ranked[0] if ranked else 100
    selected=proposed if selection[str(proposed)]['heldout']['eligible'] else 100
    result=dict(audit='PASS',repeats=10,model_runs=130,classifier_evaluations=520,
        summaries=summaries,selection=selection,train_selection=proposed,heldout_confirmed=selection[str(proposed)]['heldout']['eligible'],
        selected_window_ms=selected,hardware_access=False,firmware_changed=False,
        physical_performance_validated=False,upstream_warmup='Frozen historical software traces; not the new 3tau board candidate',
        event_truth='Independent simulated load, not DOB output and not measured brake torque',traces=audits)
    if repeat_reference:
        equal=[]
        for r in m['runs']:
            name=f"{r['scenario']}_seed{r['seed']:03d}.csv.gz"
            with gzip.open(root/name,'rb') as f:a=f.read()
            with gzip.open(repeat_reference/name,'rb') as f:b=f.read()
            assert a==b,'Fixed-input repeated replay differs: '+name
            equal.append(dict(file=name,uncompressed_sha256=hashlib.sha256(a).hexdigest()))
        result['repeatability']=dict(result='PASS',same_inputs_repeated_130=130,
            classifier_evaluations_repeated=520,independent_seed_count_per_scenario=10,
            reference=str(repeat_reference),byte_identical_uncompressed_logs=equal)
    (root/'independent_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    flat=[]
    for r in summaries:
        x={}
        for k,v in r.items():
            if isinstance(v,dict):x.update({k+'_'+s:n for s,n in v.items()})
            else:x[k]=v
        flat.append(x)
    with (root/'metrics_mean_std.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=flat[0]);writer.writeheader();writer.writerows(flat)
    lines=['# 分类窗口缩短离线验证','',
        '使用实际 MCU float C 分类器的离线副本，在 Simulink 中对固定 1 ms 日志回放。',
        '13 类场景，各 10 个配对种子，四窗口共 520 次分类评估；训练种子 1～5，保留种子 61～65。',
        '若重复整组用于确定性检查，仍只有每场景 10 个独立输入，不能当作 20 个独立试验。','',
        '| 窗口 | 最少有效点 | 最少跨度 | 普通阶跃上升延迟（均值±SD） | 普通卸载下降延迟（均值±SD） |',
        '|---|---:|---:|---:|---:|']
    def summ(s,w):return next(r for r in summaries if r['scenario']==s and r['window_ms']==w)
    def fmt(d):return '—' if d['mean'] is None else '%.1f ± %.1f ms'%(d['mean'],d['sd'] or 0)
    for w in m['windows_ms']:
        lines.append('| %d ms | %d | %.0f ms | %s | %s |'%(w,w*6//10,w*.6,
            fmt(summ('step',w)['rise_delay_ms']),fmt(summ('unload',w)['fall_delay_ms'])))
    lines+=['','100 ms 趋势低通、80 ms 趋势确认、30 ms 负载等级确认、原门控和所有输入保持不变。',
        '窗口及最少点数/跨度同时按 60% 比例缩短；不是把窗口缩小却保留不可能达到的 60 点门槛。','',
        '| 窗口 | 实测噪声注入假设：误报/漏检 | 电流真实扰动假设：误报/漏检 | 训练/保留组相对基线门槛 |',
        '|---|---:|---:|---|']
    for w in m['windows_ms']:
        counts=[]
        for s in ('real_measurement','real_torque'):
            r=summ(s,w);counts.append('%d / %d'%(r['rise_fp']+r['fall_fp'],r['rise_miss']+r['fall_miss']))
        flags=selection[str(w)]
        lines.append('| %d ms | %s | %s | %s / %s |'%(w,*counts,
            '通过' if flags['train']['eligible'] else '未通过','通过' if flags['heldout']['eligible'] else '未通过'))
    lines+=['',f'预先固定规则按训练组选择、保留组确认：{selected} ms。',
        '规则要求各场景误报/漏检不高于 100 ms 基线、趋势有效率不降低，实测假设场景的标签切换不超过基线 1.25 倍。',
        '“通过”仅为相对基线筛选，不是零误报验收。75 ms 的电流真实扰动假设仍有误报和漏检，不能据此让标签直接驱动 FSM。','',
        '50 ms 的训练组电流真实扰动假设增加误报；30 ms 同时增加误报/漏检。不得用全组合并结果覆盖训练组失败。',
        '单独比较“命中的平均延迟”会忽略漏检，需同时看上表事件数。','',
        '## 证据边界','',
        '- 仅软件回放，无硬件连接、无固件参数修改、无烧录或电机启动。',
        '- 最近四轮板测记录为约 60 ms 间隔，未插值伪造为 1 ms。这里使用早期 1 ms 软件轨迹，包括五轮实测噪声/电流的注入假设。',
        '- 外部负载真值来自原仿真器独立生成，不是 DOB 输出，也不是真实制动力矩。',
        '- 上游 DOB、有效门控和预热沿用冻结的软件轨迹。本实验隔离分类窗口，不验证新 3τ 与短窗口的联合板测效果。',
        '- baseline 100 ms 生成副本在 native 回归中与原代码每步全部状态逐字节一致；所有 130 个 Simulink 回放均旁路核对实际消耗的输入。',
        '- 生产分类器源文件哈希不变；MEX 用离线兼容宏保留静态断言；原 C 阈值、滤波、确认逻辑不改。',
        '- 5 项回归通过，覆盖基线一致、短窗口识别、坏点不更新滤波、短缺口保持、长缺口重置、故障无效以及指标不奖励提前/重复事件。','',
        '详细数据：`metrics_per_trial.csv`、`metrics_mean_std.csv`、`independent_audit.json`；每场景/种子完整日志为 `.csv.gz`。',
        '模型：`dob_window_replay.slx`；曲线：`window_comparison.png`。']
    if repeat_reference:lines+=['','130 个固定输入整组复跑通过：解压后的 130 个完整 CSV 逐字节相同。']
    (root/'RESULTS_ZH.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(audit='PASS',selected_window_ms=selected,selection={w:{s:dict(eligible=v['eligible'],failed=v['failed']) for s,v in ss.items()} for w,ss in selection.items()}),indent=2))
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path)
    p.add_argument('--repeat-reference',type=Path);a=p.parse_args();report(a.root,repeat_reference=a.repeat_reference)
