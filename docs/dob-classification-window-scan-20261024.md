# DOB 分类窗口缩短验证

仅软件离线副本，未修改固件分类窗口，未刷板、未启动电机。
当前 3τ 候选和板上旧镜像均未在本轮更动。

Simulink 模型使用实际 MCU float 分类器生成副本，对固定 1 ms 软件日志回放。
对比 100 / 75 / 50 / 30 ms，最少有效点和跨度按原 60% 比例缩短，
100 ms 趋势 LPF、80 ms 趋势确认及 30 ms 等级确认保持不变。
13 类场景，各 10 个配对种子，共 520 次分类评估；额外同输入复跑核验确定性，
不能把复跑视作每组 20 个独立试验。

| 窗口 | 普通阶跃上升识别，均值±SD | 普通卸载下降识别，均值±SD | 相对基线筛选 |
|---|---:|---:|---|
| 100 ms | 133.9 ± 0.7 ms | 133.5 ± 0.5 ms | 基线 |
| 75 ms | 126.0 ± 0.7 ms | 125.7 ± 0.5 ms | 训练、保留组通过 |
| 50 ms | 117.1 ± 0.6 ms | 116.8 ± 0.4 ms | 训练组复杂电流扰动假设误报增加 |
| 30 ms | 109.1 ± 0.6 ms | 108.8 ± 0.4 ms | 训练组复杂假设误报/漏检增加 |

建议下一候选先选 75 ms，约少 8 ms 的普通阶跃识别延迟。这里“通过”表示
相对 100 ms 不恶化的预设筛选，不是零误报验证：75 ms 的电流真实扰动假设
10 轮仍有 19 次误报、1 次漏检，标签暂不适合直接决定安全相关 FSM 转换。

5 项 native/报告回归通过。100 ms 副本与原 C 在 native 中逐步全部状态相同；
最终 Simulink 130 轮核对实际消耗输入；130 份完整 CSV 与首轮相同固定输入
复跑结果解压后逐字节相同。原生产分类器源文件哈希不变。

边界：最近四轮板测只有约 60 ms 间隔，未插值伪造为 1 ms；本轮使用早期
软件轨迹和实测噪声/物理电流注入假设，负载真值独立来自仿真器。
上游 DOB 与预热冻结，不验证新 3τ + 75 ms 的联合真实电机性能。

最终结果目录：`simulation/dob_simulink/window_scan_results/20261024_154439`。
完整说明 `RESULTS_ZH.md`，逐轮 `metrics_per_trial.csv`，均值/SD
`metrics_mean_std.csv`，独立审计 `independent_audit.json`，曲线
`window_comparison.png`，模型 `dob_window_replay.slx`，完整每轮 `.csv.gz` 日志。
源脚本 `tools/prepare_dob_window_scan.py`、`tools/report_dob_window_scan.py`、
`simulation/dob_simulink/run_window_scan.m`。
