# PWM 更新余量：同帧归因候选

先完成代码、离线测试和编译；随后在电机 U/V/W 动力线断开、驱动板 12 V 限流 0.5 A 的条件下，仅试运行一次诊断 A 槽。没有发送电机 START。该次试运行未通过健康确认，已停止并恢复先前已确认的 B 槽。下文的离线结果和上板结果分开陈述。

## 做了什么

新增独立预设 `RcBoundaryAttribution`，继承已实测的 `RcSamplingOptimizedCandidate`，保留原有滤波、零点、RC 采样预算、保护及原拧紧状态机。没有调低编码器 IRQ 优先级，没有提前采样，没有增加一个控制周期，也没有取消 PWM 余量告警。

新增的是定位工具，不是已证明更快的控制版本：

- 对同一次外层 ADC IRQ 记录入口/出口计数值与方向、到底部的估计剩余 ticks、工作区间墙钟周期、已计入的抢占周期。
- 分开记录 TIM7 保护、TIM2 编码器定时、编码器 RX DMA、TX DMA 的次数和独占 IRQ 主体周期。嵌套时不重复计费。
- 冻结首次余量非正的有效帧，并保留最小余量帧。所有输出携带帧号，不把不同帧的最大值相加。
- 时钟证明、计数方向不稳定、源统计错误、统计不一致或算术异常均标记为无效证据，不用它们覆盖首次/最差有效帧。
- 定时器几何检查增加 `TIM1->RCR == 0`，与当前初始化配置一致。原有 ARR、PSC、中心对齐、死区、CCR 预装载和 TRGO2 检查保留。
- 四类源入口/出口及帧开闭函数主体放入 RAM；没有声称完整调用图都位于 RAM。

诊断模式 `FOC_PWM_BOUNDARY_TRACE` 与旧的内层 `FOC_IRQ_SOURCE_TRACE` 互斥，避免一个 IRQ 中重复开启/关闭统计帧。它要求完整 RC 原状态机候选配置。

## 诊断版本不能用于电机验收

诊断会增加中断开销，快照冻结也会增加短临界区。因此本预设的 `FocAdcTiming_RcActuationReady()` 固定返回 0，`FocAdcTiming_CommitBeforeBottom()` 也拒绝发布占空比。没有新增使能功率桥入口，原保护未放宽。

`MOTOR TEST PROFILE` 返回 `NAME=RC_BOUNDARY_TRACE HARD_OFF=0 ADMISSION=0 ... QUALIFIED=0`。这里 HARD_OFF=0 表示沿用原控制结构，而不是编译级硬关闭镜像；ADMISSION=0 才是本诊断候选拒绝控制准入的标记。不要混称为物理硬关闭保证。

已实测的优化版 A/B BIN 和旧上板脚本保持不变。上板使用独立的 `tools/rc_boundary_board_test.py`，只允许精确镜像的暂存、一次试运行及失败后的已确认 B 槽恢复。

## 读数怎么理解

串口新增只读命令：

```text
ADC BOUNDARY
ADC BOUNDARY FIRST
ADC BOUNDARY FIRST IRQ
ADC BOUNDARY WORST
ADC BOUNDARY WORST IRQ
```

`FIRST` 是首次有效余量非正帧；`WORST` 是最小余量帧。两条 WORST 查询之间记录可能更新，必须比较 `SEQ`，不同帧不能配对；FIRST 一旦有效便不再更新。`VALID=0` 不代表正常，而是尚无对应有效记录。`INVALID` 是无效观测累计次数。

在认证的 170 MHz CPU/TIM1 配置下：

```text
余量 = IRQ 入口快照估计的到底部 ticks - 同帧墙钟 cycles
未归因于已测 IRQ 主体的周期 = WALL - IRQ
```

`CPU` 只是第二式，包括 FOC、未埋点工作、异常切换及探针开销，不能称为纯 FOC 算法耗时。`ORDER=G,T,R,X` 分别是保护定时器、编码器定时器、RX DMA、TX DMA；`BODY=EXCL` 不包括完整物理异常进入/退出延迟。

这些仍是软件粗估：计数与 DWT 不是同一时钟沿读取；IRQ 进入前的转换/排队延迟、退出后的快照复制和 ISR 尾声没有完整覆盖。保留 `HW_VERIFIED=0`。余量正数也不等于 CCR 物理更新已经合格，还须保留现有 170 ticks 提交保留预算及实际检查。

当前代码 RCR=0、中心对齐、CCR1..4 均预装载；提交路径只接受向下计数并用 UDIS 包住四路写入，运行时不强制 UG。新增 RCR 检查防止更新节奏假设被配置变化破坏；它不是示波器/逻辑分析仪验收。

本地 ST HAL 头文件 `foc2_app_b/Drivers/STM32G4xx_HAL_Driver/Inc/stm32g4xx_hal_tim.h` 中 `TIM_Base_InitTypeDef.RepetitionCounter` 的说明明确区分：中心对齐时 N+1 对应半个 PWM 周期的数量。因此不能简单地把“50 µs 整周期计算完成”当成“赶上本次更新边界”。

## 编译产物

| 槽 | BIN 字节 | 静态 RAM / 链接区 | 静态余量 |
| --- | ---: | ---: | ---: |
| A | 213580 | 127256 / 131008 | 3752 |
| B | 212716 | 127232 / 131008 | 3776 |

SHA-256：

- A：`059cea4b5aad85d774fd41af9ac86440d57f82b22afee7861c3f1355beea3643`
- B：`8ecba8e49f03fec61a72915f2a19222f0b0ef5ed3a437cc7942d87fa379015fc`

静态余量不是任务栈运行余量。原有 RWX LOAD 段警告、未使用函数及 Pigweed ABI 提示未在此轮处理。

```powershell
$env:PATH='D:\software\arm\bin;D:\software\ninja;'+$env:PATH
cmake --preset RcBoundaryAttribution -S 'D:\new project\foc2_app_a'
cmake --build 'D:\new project\foc2_app_a\build\RcBoundaryAttribution' -j 6
cmake --preset RcBoundaryAttribution -S 'D:\new project\foc2_app_b'
cmake --build 'D:\new project\foc2_app_b\build\RcBoundaryAttribution' -j 6
```

## 2026-10-16 上板诊断与恢复

先在 12 V 关闭时对照完整 Flash，写入非活动 A 槽并回读；确认 B570、bootloader 和私有配置不变，暂不激活。驱动板 12 V 开启、无报警后，提交一次普通 A/B 试运行。功率输出始终关闭，U/V/W 动力线断开，未发送 START。

候选 A 在零点完成后、约 4056 次 FOC 工作帧处触发 `CL_COMPUTE_LATE`（`FLAGS=256`）：`MAX_US=52`，因此未通过 5 秒健康确认。不是驱动板过流报告，也不是零点失败；当次零点 `STATE=3, REASON=0, N=4000`。当次 `ADC TIMING` 的 `PAIRS=28060, MISS=0`，编码器 DMA `FAIL=0, TIMEOUT=0`。现场通过 `ANALOG SAFE` 锁定输出并停机，没有自动重试。

冻结的首个有效余量非正帧 `SEQ=24000`：入口剩余 `4043` ticks、同帧墙钟 `4211` cycles，估算余量 `-168` cycles，即约 `-0.99 µs`。其中已记录保护 IRQ 主体 `678` cycles，余下 `3533` cycles 不能等同于纯 FOC 算法。

最差有效帧 `SEQ=28019`：入口剩余 `4041` ticks、墙钟 `10257` cycles，估算余量 `-6216` cycles，即约 `-36.56 µs`；同帧已归因 IRQ 主体 `5499` cycles（约 `32.35 µs`），其余 `4758` cycles（约 `27.99 µs`）。已归因部分按 G/T/R/X 顺序为 `2086/2813/600/0` cycles，分别约 `12.27/16.55/3.53/0 µs`，次数 `3/6/2/0`。`FIRST` 和 `WORST` 各自的帧号与对应 `IRQ` 帧号一致，源统计错误为 0。累计有效余量非正 `3305` 帧、无效观测 `6` 帧。该累计数包含诊断版的额外开销，不能移植为原 B570 的丢更新次数。

诊断镜像本身增加了 IRQ 源埋点、冻结快照及读数开销；它在本次达到 `52 µs` 并触发原有 50 µs 停机保护。因此结论是“诊断版在这一开销条件下，保护定时器和编码器定时器/DMA 可与 ADC 帧叠加占用更新余量”，**不是**“原 B570 稳态一定超 50 µs”，也不能仅凭这些软件粗估认定物理 CCR 更新失败。此前 B570 的独立 31 秒功率关闭试运行 `compute_max=44 µs`、ADC IRQ 最大约 `44.63 µs`；两次镜像与埋点不同，不作同帧直接差值比较。

用户关闭驱动板 12 V 后，使用现有 bootloader 的正常 `SET_CONFIRMED_SLOT` 选择原已确认 B 槽，清除失败 A 的 pending；在 B 复位入口设断点并停住，没有执行 B 应用或启动电机。完整 Flash 回读显示除 bootloader 正常元数据外，应用、bootloader 和私有配置字节不变。最终元数据为 confirmed B、pending none、attempts 0、generation 573；SD/PWM 关闭且 CPU 停止。

公开收据：[暂存](safety_backups/protected-closed-loop-20261014/rc-boundary-stage-1792128534815748900.json)、[试运行失败及同帧数据](safety_backups/protected-closed-loop-20261014/rc-boundary-trial-1792128741578925600.json)、[恢复 B](safety_backups/protected-closed-loop-20261014/rc-boundary-restore-1792129050337883700.json)。完整 Flash 备份在 `private` 目录，不外传。

## 下一步

先用这版在功率关闭条件下抓取同帧归因，再判断究竟是 FOC 本体、保护 IRQ 还是编码器定时/DMA 占用了底部前的时间。之后才能有依据地调整编码器相位/短临界区，或设计固定周期流水线。现在不能宣布余量告警已经消除，也不能把诊断新增耗时算作控制版性能退化。

后续已实现开销更低、仍不允许电机准入的独立诊断候选，见 [PWM 更新余量低扰动诊断](FOC_PWM_BOUNDARY_LITE_20261016.md)。它尚未上板，不能替代本页记录的实物试验。

## 离线验证结果

56 项 Python 回归通过。新增测试使用真实 timing/source adapter 配合寄存器模拟，覆盖 DWT 回绕、上下行剩余时间、嵌套 IRQ 独占计费、首次异常冻结、最差帧更新、RCR 配置改变、DWT 关闭、统计溢出/不一致、192 字节命令缓冲及无控制准入/无占空比发布。纯数据结构与真实 adapter 均在 `-Os` 和 `-O2` 下验证。

链接检查通过：四类实际 IRQ 包装器调用源统计入口/出口，内层 FOC 不重复开启统计帧，两个准入/提交函数实际生成返回 0 的代码，指定源统计函数主体在 RAM。

```powershell
$env:PYTHONPATH='D:\new project\tools;D:\new project\tests'
python -m unittest test_foc_pwm_boundary test_foc_irq_source_trace test_foc_rc_protected_candidate test_foc_adc_rc_policy test_foc_adc_clock test_foc_startup_evidence test_latest_original_fsm test_protected_irq_optimized test_foc_rc_optimized test_rc_optimized_board_test -q
```

上述离线测试本身没有硬件时序、模拟采样或电机闭环结论；上面的单次上板诊断另行报告。下一轮若要实际减少余量告警，应先做低扰动源统计或相位对照，并保留 50 µs 计算保护、零点/反馈检查与输出锁定。不能把诊断版的 52 µs 失败当作放宽停机阈值的理由。
