# FOC 采样窗口与关键路径优化

## 结论

已完成代码优化、A/B 编译和离线回归。代码优化阶段没有访问板卡；后续用户明确授权的实测结果如下。

### 最新实测：功率关闭的 50 µs 计算观察通过

2026-10-16，用户明确允许恢复已确认 A、仅写非活动 B 及必要复位。驱动板先关闭 12 V，保持 MCU 供电和 U/V/W 动力线断开；完成新版 B 写入和完整回读后，用户开启 12 V，再提交一次正常 B 试运行。全程 **START=0**，不启用功率输出。

| 项目 | 实测结果 |
| --- | --- |
| 正常启动／确认 | 零点和 5 秒健康窗口通过，由现有 bootloader 正常确认 B |
| 连续计算观察 | 31.3769 秒，期间 ADC 对数增加 629248 |
| FOC 工作路径最大耗时 | **44 µs**；50 µs 超时计数为 0 |
| ADC 中断最大耗时 | **7587 cycles / 170 MHz = 44.6294 µs** |
| 双 ADC | 最后一次快照 PAIRS=677606，MISS=0、PF=0 |
| 筛选零点 | 4000 对，U0=1561、V0=1560；筛选范围 1555..1568 / 1554..1566；稳健零点 FLAGS=0 |
| 筛选／保护 | TREND4、4 A 2-of-3；故障 FLAGS=0，无首故障记录；策略未放宽 |
| 编码器 DMA | FAIL/TIMEOUT/IO/SCHED/STALE 均为 0，MAX_US=36 |
| 后台双缓冲 | DONE=2649，任务栈余量 1864 字节；DROP_B=4 / DROP_S=1024，不是全程零丢块；这两个丢弃计数在 31 秒观察内没有继续增加 |
| PWM 更新余量 | BOTTOM_LATE=28376、READY=0；CHECK=0、FAIL=0，未进入真实变化占空比提交 |
| 结束状态 | 已确认 B、generation=570；SD/MOE/AOE/CCER/CEN 关闭，MCU 暂停；A 回退固件和私有区域保留 |

**本轮功率关闭的计算目标通过，不等于电机闭环通过。** 44 µs 是该任务负载和观察时长下的测得最大值，不是形式化最坏执行时间保证；本轮未运行 RUNNING 态的实际占空比规划／提交，因此也不能据此验证专用规划器的板端运行态耗时。

上轮候选在健康确认前触发 50 µs 截止；本轮正常确认并完成 31 秒观察，说明优化对当前 READY／影子计算路径有效。新记录的 CPU_MAX_CYC=3528（20.7529 µs）、PREEMPT_MAX_CYC=3875（22.7941 µs）、PAIR_MAX_US=29、MATH_MAX_US=23，各自来自不同帧的历史最大值，**不能相加当作一帧总耗时**。

还没有解决的是采样完成后到指定 PWM 更新底部的余量：计算在 50 µs 内完成，但粗粒度余量告警仍增加，准入正确保持 READY=0。未删除该告警、未发 START，也未验收模拟建立、反馈极性、真实 PWM 更新或电机闭环。

完整 Flash 只保存在既有受限目录；最终全片对照确认，相比暂存版本，仅正常试运行／确认元数据变化，应用、bootloader 和私有区域字节均未变。镜像 SHA-256 仍为下表值。

证据：[新版 B 暂存与回读](safety_backups/protected-closed-loop-20261014/rc-optimized-stage-1792126807116795200.json)、[31 秒计算实测及最终关断](safety_backups/protected-closed-loop-20261014/rc-optimized-trial-1792126877053386600.json)。

上板准备中修正了两处主机验收问题：bootloader 跳转 A 复位入口前已安装 A 的 VTOR，应核验该向量及精确 PC；OpenOCD 重连后需先 poll 同步状态，才能读取 PC。两次中止均在 B 写入前，完整备份未变；随后只从同一恢复状态继续暂存，没有重复 A 恢复或电机／B 试运行。包括真实成功／失败记录判定在内，最终相关 **26 项离线回归全部通过**。

### 历史准备记录：曾在权限审核处暂停

用户随后要求实测，并回复驱动板 12 V 已关闭。只读检查确认 ST-Link 可用、MCU 电压约 3.288 V、VTOR 指向 B；CPU 已暂停，SD/MOE/AOE/CCER/CEN 均关闭。已有受限完整备份通过哈希核验，仍为上轮失败 B566 与保留 A564。

已新增独立脚本 `tools/rc_optimized_board_test.py`，固定新版 B 哈希，分开执行断电恢复／暂存及上电计算观察；相关 **23 项离线回归全部通过**。旧验收脚本和旧证据未改。

首次恢复／暂存命令在创建进程前被权限审核拒绝，理由为需要补充明确的刷写、复位授权。该次命令没有执行；之后用户已明确授权，并完成上节记录的恢复、写入及实测，不再停留在这条历史状态。

这次减少的是计算开销，不是用软件消除模拟电流尖峰。上节仅证明新版在功率关闭条件下的观察结果。此前旧候选版的实机失败记录保留，见 [上轮实测记录](FOC_RC_PROTECTED_CANDIDATE_20261016.md)。

## 改了什么

1. **不运行，就不规划占空比。** 原来 READY／影子计算也会生成一次最终被丢弃的采样窗口。现在在 `ProtectedLoop_SetDuty` 入口提前检查运行、使能和故障状态；不满足就返回。规划后仍在原临界区重新检查，防止规划期间发生 STOP／TIM7 关断后又提交输出。
2. **低边延后采样走专用算法。** 当前配置只需考虑 U/V 都已导通之后的窗口，W 最多再把它分成两段。现在先检查靠近顶点的一段，不合格再检查 W 之前的一段，不再走三项排序和四段搜索。其他拓扑和采样位置保留通用算法。
3. **减少 Flash 路径和重复清零。** 窗口规划、占空比转换、Prepare 和 CommitPrepared 的函数体放入已有 RAM 热路径；有效 Duty 调用不再重复清零输出。参数错误仍清零计划，不能复用上次计划。RAM 标记不表示整个调用图都在 RAM，例如反汇编中仍可见 memset 跳板。

没有更换四点趋势筛选、PI、原 START／拧紧状态机，也没有改中断优先级。4 A 的 2-of-3 保护、50 µs 截止、TIM7 独立超时、原超速和短测范围保持不变。RC 低边导通预算仍为 1700 ticks（10 µs），死区、建立时间和 ADC 孔径预算不变。

## 离线证据

- **53 项合并回归全部通过**：覆盖采样时钟、原控制绑定、保护链、旧状态机、快速数学和既有失败证据判定。
- 新规划器与冻结的旧规划器在 `-Os`、`-O2` 下分别比较 **1,319,107** 组输入；返回状态和完整计划逐字节一致。包括实际 PWM 网格、小定时器穷举、随机边界、相位顺序／重合和无效参数。
- 真实控制绑定的主机测试确认 READY、DONE、FAULT、未使能和已有故障时不规划；RUNNING 正常提交、规划失败以及规划期间 STOP／独立关断的竞争仍按原策略处理。
- 既有窗口／双缓冲脚本通过：独立检查 **1,752,355** 个成功计划；双线程压力测试覆盖 **5,120,000** 对样本。主机压力运行允许丢块，不能写成全程零丢块。
- A/B 新镜像链接成功；符号和 A 槽反汇编确认 RAM 地址、入口提前返回、规划后重新检查及底部提交检查。它们是编译证据，不是板端时序证据。

旧回归有一处仍匹配 `static uint32_t ProtectedLoop_Health`，而实际声明早已使用紧凑帮助函数宏／Captured 变体；本轮修正了这个测试定位方式，原检查内容未删除，复跑通过。

## 候选镜像与代价

新预设 `RcSamplingOptimizedCandidate` 继承原候选配置，不覆写参数，并使用独立构建目录。上轮实测镜像固定哈希复核通过，未被覆盖。

| 槽 | BIN 字节 | 静态 RAM（含链接保留） | SHA-256 |
| --- | --- | --- | --- |
| A | 211788 | 126072 / 131008 | `0990cdf2ec7fde9c169afdc3d67cb2d3ea772ae29fd90b0c9b4f565565f05e20` |
| B | 210916 | 126056 / 131008 | `9fd54166df782cce3e737ecfebe67bc4aff8f15a005fca1f1136c91bb8786f44` |

位置：`foc2_app_a/build/RcSamplingOptimizedCandidate/foc2.bin` 和 B 槽对应目录。

相比原候选，RAM 各增加 976 字节；A/B 静态余量分别为 4936／4952 字节，不代表任务栈运行余量。原有未使用函数、Pigweed ABI 提示和 RWX LOAD 段链接警告仍存在。本轮没有处理这些独立问题。

既有旧版上板脚本固定的是旧候选哈希，未被改成新版。新版通过独立脚本和独立收据上板，未改旧版失败记录。

## 后续实测要看什么

优先比较相同供电／任务负载下的 READY 和 RUNNING 路径，分别记录同一帧的 wall cycles、抢占 cycles、计算截止和到底部的余量。入口提前返回主要收益在 READY，不能据此推断运行态同样节省。

旧候选同一失败帧 wall=8287 cycles、已计入的抢占=3868 cycles（170 MHz 下约 48.75／22.75 µs）。本轮没有改变抢占安排，READY 路径已通过上节限时观察；运行态新增规划／提交后的余量仍需验证。不能把软件计算缩短当作模拟采样建立、PWM 提交边界或电机反馈已经合格。

## 复现

```powershell
$env:PATH='D:\software\arm\bin;D:\software\ninja;'+$env:PATH
cmake --preset RcSamplingOptimizedCandidate -S 'D:\new project\foc2_app_a'
cmake --build 'D:\new project\foc2_app_a\build\RcSamplingOptimizedCandidate' -j 6
cmake --preset RcSamplingOptimizedCandidate -S 'D:\new project\foc2_app_b'
cmake --build 'D:\new project\foc2_app_b\build\RcSamplingOptimizedCandidate' -j 6
Set-Location 'D:\new project'
$env:PYTHONPATH='D:\new project\tools;D:\new project\tests'
python -m unittest test_foc_rc_protected_candidate test_foc_adc_rc_policy test_foc_adc_clock test_foc_startup_evidence test_latest_original_fsm test_foc_fast_math test_control_chain_reconnect.ReconnectAdapterTests.test_actual_ab_current_pi_uses_filtered_frame_and_original_limits test_rc_sampling_board_test test_rc_sampling_trial test_protected_irq_optimized test_foc_rc_optimized -q
powershell -NoProfile -ExecutionPolicy Bypass -File tests/foc_adc_window_host.ps1
```
