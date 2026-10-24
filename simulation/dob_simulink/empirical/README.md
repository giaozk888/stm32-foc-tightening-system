# 实测事件驱动的 DOB 离线验证

本扩展仅运行 MATLAB/Simulink 和文件分析，不连接硬件，不修改 A/B 固件、默认参数或保护。复用上层环境已编译的原 C 速度 PI、S 曲线、前馈、摩擦补偿、DOB、质量门控及统一 Iq 限幅。

## 数据边界

`export_events.py` 通过现有只读解码器核验两份历史 receipt/ELF/BIN/Flash/RAM，再导出两个各 40 点、约 39 ms 的连续触发窗口。保留原 Id/Iq 配对与时间戳；舍弃每段后续 32 个稀疏尾部点，不插值成长波形。触发式采集不能识别自然尖峰发生率，也不能区分测量错误与真实电流动态。

五点局部中位数从 Iq 中去除局部运行基线，得到 `Iq_residual`；它不是经过独立电流探头校准的 ADC 噪声。原始 Id 按记录值注入。原 `speed_ref-speed_meas` 不作为编码器噪声注入，因为它含有真实跟踪误差。原观察器完整 source-age 未保存，因此本扩展不是历史全流程精确回放。

## 两种不同假设

- `measured_once` / `measurement_train`：残差仅进入 Iq 测量，原 Id 进入质量门控；不改变仿真真实转矩。
- `torque_train`：同一 Iq 残差作为真实电流脉冲，同时影响机械模型和 Iq 测量；保留真实负载扰动的独立来源。真实总 Iq = 电流执行器模型输出 + 脉冲。
- `unloaded_stress`：无外部负载，连续嵌入事件块，专门检查空载误补偿。40 ms 重复间隔是人为压力条件，不是实测发生频率。
- `nominal`：无实测事件注入，作为基准。

模型使用机械 rad/s：

`(J/Kt)*dω/dt = Iq - (B/Kt)*ω - Ic*sign(ω) - bias - load_A`。

真实脉冲通过 `load_effective = load_A - pulse_A` 加入机械方程，观察器输入 `Iq_total = Iq_regulator + pulse_A`；`load_ground_truth_a` 始终记录独立外载，不把 DOB 输出或电流脉冲伪装成外载真值。

真实电流脉冲可能超过命令 Iq 限幅。这属于假设敏感性试验：没有仿真电气 FOC/电压裕量、硬件过流关断、IRQ、ADC/PWM 时序，也没有让真实硬件执行这些脉冲，不能据此断言物理可实现或安全。电流执行器一阶时间常数仍为假设，不是实测电流环。

## 采样和配对

控制器/DOB 1 ms，机械与命令 pipeline 50 µs。原约 1 ms 时间戳显式重采样到新仿真网格，保留 `scheduled_*` 标签；标签仅表示计划注入，实际控制器端电流/噪声和脉冲独立记录。From Workspace 的浮点 ZOH 边界可能选择上一行，因此审计比较实际输入日志，不把计划标签当成精确历史时序。

OFF/ON 使用相同种子、事件选择、负载和背景噪声，逐列哈希核对实际输入。每场景先完成全部 OFF 重复，满足预先存在的估计误差/偏差/有效率/延迟/恢复门槛后才允许仿真 ON；失败保留数据并跳过 ON，不放宽门槛。

## 运行

在 MATLAB 中 `addpath` 本目录，然后 `run_empirical_validation('full')`。需先存在上层已编译的 `build/dob_host.dll`、MEX 和 `dob_offline.slx`。本扩展不自动重建或覆盖原基准模型。

`java.opts` 仅在以本目录作为 MATLAB 启动目录时将该进程 Java 堆上限设为 256 MB，适应本机内存限制；不修改全局 MATLAB 偏好。SDI 位置沿用上层 session helper 并在退出恢复，不删除用户历史运行。

正式批次为 100 次主要对照（5场景×5种子×4增益）及24次模型敏感性（2场景×2模型×3种子×OFF/ON0.25）。敏感性仅改变仿真机械参数及执行器假设，保持 C 控制器/DOB 参数不变。

结果位于 `results/`，包括每次 CSV、均值/样本标准差、逐种子配对差异、准入结果及源文件哈希。再运行 `python audit_saved_runs.py` 独立审计；仓库根目录运行 `python tools/report_dob_empirical.py` 和 `python tools/plot_dob_empirical.py` 生成报告与SVG。曲线仅后处理保存的 Simulink CSV，不另写仿真算法。

`smoke_results/` 是早期单种子调试产物，不是最终证据：其第一次运行期间脚本曾改动，结束时冻结检查正确报错，且个别MATLAB栅格图为空。正式 `results/` 是随后冻结源码重新完成的124次运行及独立SVG/PNG曲线，未复用调试统计或图。

本扩展仍不是螺钉/工件接触模型，也未仿真完整 tightening FSM。所有性能结论仅限声明的机械模型和注入条件，不代表真实拧紧或真实电机已验证。
