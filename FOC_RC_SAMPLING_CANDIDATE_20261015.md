# RC 感知的延后采样对照版

2026-10-16 后续：已另建 [保留保护的闭环候选配置](FOC_RC_PROTECTED_CANDIDATE_20261016.md)，接入原 START／拧紧状态机；随后写入非活动 B 并单次试运行，零点通过，但触发 50 µs 计算截止，未确认 B、未启动电机，已锁定暂停。A564 不变。本页以下结果仍属于原硬关闭对照版，不能当成新闭环候选通过的证据。

状态：代码、主机回归、A/B 编译通过；**2026-10-16 已正常激活 A564，并完成功率硬关闭的 30.9 秒计算测试：50 µs 计算目标通过，但到下一计数底部的粗粒度余量告警不为零，未验收实际 PWM 更新、模拟建立或电机闭环。没有启动电机，超速根因仍未验收。**

## 2026-10-16 实测结果

| 项目 | 结果 |
| --- | --- |
| 正常健康确认 | A564；现有 bootloader/APP 流程确认，未强制确认 |
| 观察跨度 | 30.9104 秒，两个查询点之间新增 620046 对 ADC 样本 |
| FOC 墙钟最大值 | 44 µs，FOC 50 µs 超时计数为 0 |
| ADC ISR 最大值 | 7476 cycles / 170 MHz = 43.9765 µs |
| 配对与窗口 | ADC `MISS=0`、`PF=0`；CH4=4184，RC_MIN=1700，LATE=1 |
| 运算分项最大值 | 纯 CPU 3434 cycles≈20.2 µs；抢占累计 3873 cycles≈22.8 µs；PAIR_MAX=29 µs；MATH_MAX=23 µs |
| 编码器 DMA | READS=32247；FAIL/TIMEOUT/IO/SCHED/STALE 均为 0；MAX_US=37 |
| 后台原码双缓冲 | DONE 196→2618，栈余量 1860 字节；DROP_B=3、DROP_S=768 始终未新增，不能说启动全程零丢块 |
| 粗粒度底部余量告警 | ADC `LATE` 929→26961，观察期间增加 26032；**不是 50 µs 超时数，也不是 ADC 丢样数** |
| 结束状态 | ANALOG SAFE 已确认，SD/MOE/AOE/CCER/CEN 关闭，MCU 暂停；APP/bootloader/KVS/参数字节未变，只有正常试运行元数据更新 |

上述最大值来自不同样本/区段，存在包含关系，不能直接把纯 CPU、抢占、PAIR、MATH 的各自最大值相加重建某一帧。DWT 区间不包括触发至转换、异常入栈/返回的全部时间，也不是形式化 WCET 证明。

筛选零点完成 4000 对：U0=1562、V0=1560，筛选后范围分别 1554..1568、1554..1566；`RAW_STATE=4 RAW_REASON=2` 仍显示未筛选原码对照不通过，不能把本次写成“原码零点也通过”。本测试沿用已有筛选与保护，未修改阈值。

结论：后移采样没有让计算超过 50 µs，但缩短了采样后到下一底部的时间（名义约 25.38 µs）。ISR 最大约 43.98 µs 且粗粒度余量告警累积，**不能据此宣称同周期 CCR 提交满足或允许直接闭环验收**。硬关闭分支本来就不提交变化的电机占空比；该告警不是一次次物理 PWM 更新失败的直接测量。后续应单独设计/测量 CCR 生效边界与端到端延迟，而不是删除告警或放宽 50 µs 目标。本轮不追加桥开关或电机试验。

公共原始证据：`safety_backups/protected-closed-loop-20261014/rc-sampling-trial-1792121761791953100.json`。验收脚本 `tools/rc_sampling_trial.py` 默认仅离线检查；UART 只允许诊断查询/ANALOG SAFE，START 次数为 0。A 镜像 SHA-256 仍为下表值，B561 原镜像与私有数据完整保留。

## 2026-10-16 暂存记录

- 用户确认驱动板 12 V 关闭、电机 U/V/W 动力线断开。首次检查发现 MCU 已不再暂停，刷写被拦截；只读核验仍在 B 槽且 SD/MOE/AOE/CCER/CEN 均关闭。随后仅暂停核验：整片 Flash 与 B561 最终备份完全一致。
- 只将本页固定哈希的 `RcSamplingComputeOnly` A 镜像写入非活动 A。完整回读通过；新镜像最后擦除页之外的所有字节均未变，包括 B561、bootloader、元数据、KVS 和参数。原 A558 完整镜像仍保存在前次私有备份中。
- 暂存阶段保持 bootloader 暂停、输出关闭，未提交 START_TRIAL、未发 START，未强制确认。之后在用户开启驱动板正常供电后，经现有 A/B 健康流程激活功率硬关闭版本；结果见上方实测记录。暂存通过不代表时序或闭环通过。
- 公共证据：`safety_backups/protected-closed-loop-20261014/rc-sampling-stage-1792121561313495400.json`；对照脚本：`tools/rc_sampling_board_test.py`。脚本离线默认不访问设备或私有备份，六项主机回归通过。

## 实际改动

新增独立构建 `RcSamplingComputeOnly`，继承原 `ProtectedIrqCompact` 的功率硬关闭计算配置。原电流反馈符号、PI、筛选与保护阈值、编码器方向/零位、旧拧紧状态机均未修改；原 `LatestOriginalStartupEvidence` 配置没有自动启用新策略。

- `FocWindowConfig` 新增 `min_low_on_ticks` 与采样位置策略，旧默认仍为 0 和窗口中点。
- RC 对照将 U/V 名义低边导通后的最短观察时间设为 1700 timer ticks（10 µs），与三相边沿的旧 85 ticks 恢复裕量分开。W 仍要避开边沿，但不把 U/V 的 RC 预算错误施加为 W 的完整恢复时间。
- 在全部合法区间中选择最晚可用点，而不是最大区间的中点；包括触发延迟上界及采样孔径在内，采样孔径结束必须早于计数顶点/预装载更新边界。
- 窗口不足返回 `FOC_WINDOW_TOO_SHORT`，失败输出计划清零。STM32 提交失败使计划失效，不继续使用旧窗口开启输出，不隐式降低观察时间。
- `ADC WINDOW` 增加 `RC_MIN` 和 `LATE` 字段；保留 `HW_VERIFIED=0`。`REF_MAX=95` 仅表示请求占空比的原有钳位上限，不表示 RC 模式可接受 95%。
- CMake 和头文件均拒绝将本诊断开关与电机使能配置混用；现有硬关闭路径使 `ProtectedLoop_Ready()` 返回 0、SD/MOE/CCER 保持关闭。

## 50% 参考的几何差别

170 MHz、ARR=4249、三相 CCR=2125，名义死区为 85 ticks：

| 项目 | 原窗口中点 | RC 延后对照 |
| --- | --- | --- |
| CH4 比较值 | 3271 | 4184 |
| 名义低边开通到触发 | 6.241 µs | 11.612 µs |
| RC 最短观察预算 | 无独立约束 | 10 µs |
| 采样孔径跨过顶点 | 原算法允许 | 不允许 |
| 95% 同占空比 | 旧几何可行 | 拒绝，观察时间不足 |

上述为定时器模型，不是实测光耦/MOS 导通时间或模拟建立时间。10 µs 只对应手册名义 100 Ω × 100 nF 的一个时间常数，**不是充分稳定的保证**。对孤立理想阶跃，新触发点的残余初始误差仍约 31.3%；实际低边分流信号为周期波形，不能把这个百分比当成实板电流误差、增益补偿或方向结论。若要求 3 个时间常数，当前 50%/上数触发几何不能容纳，测试明确拒绝，不能为通过而偷偷缩短预算。

采样后移不等于 FOC 运算变快。到下一周期底部的名义剩余时间从约 30.75 µs 减至 25.38 µs；实际 CCR 更新、完整 ISR 及 50 µs 新样本截止必须重新检查。不能拿旧 50 µs 耗时测试当新相位配置已经通过的证据。

功率硬关闭版本只能先验证 ADC 配对、触发相位和计算时序；它不能验证带开关的模拟建立或电压矢量到 IU/IV 的实际方向。后者仍须单独定因，本次没有盲改相序/符号来尝试转动。

## 离线验证

- 规划器主机测试：1,752,355 个成功计划逐个经过独立边沿距离/低边导通/孔径检查。新增 RC 的 91³ 个组合中 245,209 个接受、508,362 个拒绝；其中 1000 组另外穷举每个 timer tick，核对确实选择全局最晚安全点。
- 覆盖 95% 拒绝、3τ 不可行、W 边沿分割、非法策略/拓扑、失败计划清零。
- STM32 适配器分别测试未知拓扑、旧策略和新 RC 策略；校验提交失败不写 CCR、计划失效、掩码/UDIS 保留、配对、诊断输出和统计缓冲。
- 原码双缓冲两真实主机线程处理 5,120,000 对样本，所有权、顺序和丢弃计数检查通过；这不是 MCU 双缓冲实测。
- Python 回归：原 ADC 时钟/估速证据/旧状态机/快速数学/实际 A/B PI 数值 27 项；新增 RC 策略、10 组头文件编译组合、A/B 配置与链接结果检查 4 项，共 31 项。
- 实际 CMake 负例 `FOC_ADC_RC_MIN_LOW_ON_TICKS=1000` 被拒绝，符合预期。
- A/B 新镜像编译成功。链接器仍有原有 RWX LOAD 段警告；本改动没有修复/消除该警告。无 MCU 耗时实测。

复现：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tests/foc_adc_window_host.ps1
cd foc2_app_a
cmake --preset RcSamplingComputeOnly
cmake --build --preset RcSamplingComputeOnly -j 6
cd ../foc2_app_b
cmake --preset RcSamplingComputeOnly
cmake --build --preset RcSamplingComputeOnly -j 6
cd ..
$env:PYTHONPATH='D:\new project\tools;D:\new project\tests'
python -m unittest test_foc_adc_rc_policy test_foc_adc_clock test_startup_overspeed_analysis test_foc_startup_evidence test_latest_original_fsm test_foc_fast_math test_control_chain_reconnect.ReconnectAdapterTests.test_actual_ab_current_pi_uses_filtered_frame_and_original_limits -q
```

## 镜像与保留项

| 槽 | 新诊断 BIN 字节 | SHA-256 |
| --- | --- | --- |
| A | 208236 | `951a9381cd18e5614b685d8ca978e466d0746252a03c3554892595c549a0ccf3` |
| B | 207316 | `deadaa1290a530676ddbdc27799a57e48ee72fde381682dbdf63d90e4d410119` |

A RAM 使用 122472/131008 字节，B 为 122448/131008 字节；包含静态布局，不证明运行栈余量。

原 B561 本地 BIN `foc2_app_b/build/LatestOriginalStartupEvidence/foc2.bin` 仍为 210116 字节、SHA-256 `2450f5a6da36c0698690aa2353fd1f76758e4b7401453fb7f361cfab1e72c61b`。板上 B561、bootloader、元数据和私有配置未变；原 A558 已由上述诊断 A 替换，完整备份保留。离线阶段未操作板卡；2026-10-16 的暂存操作以上方记录为准。
