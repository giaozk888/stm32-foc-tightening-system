# FOC 同周期抢占归因与功率硬关闭 CCR probe

## 当前结论与边界

本轮只实现、编译和离线验证诊断代码，没有连接调试器/串口，没有刷板、复位、修改启动元数据或启动电机。历史 `outer=59.43 us` 是否主要来自抢占，**仍不能从各自独立的 max 值倒推**；需要新镜像产生一次同周期有效快照。真实板端 CCR probe、最小 margin 和 late-write 结论也仍待人工上板验证。

新配置为 A/B 两侧的 `PreemptCommitProbe`，默认 OFF，继承功率硬关闭的 `FastCurrentRejectComputeOnly`。与旧的九阶段 `FastPathTiming` 配置互斥，避免叠加两套重型 profiling。

## 1. 哪些 IRQ 可以抢占 ADC/FOC

按现有配置，NVIC priority grouping 为 3（4 个抢占优先级位），数值越小越优先：

| IRQ | 优先级 | 用途 | 本轮处理 |
| --- | ---: | --- | --- |
| TIM7_DAC | 0 | 独立保护/超时 guardian | 入口/出口 DWT 统计 |
| TIM2 | 1 | 编码器 DMA 定时状态机 | 入口/出口 DWT 统计 |
| DMA1_Channel4 | 1 | 编码器 SPI RX | 入口/出口 DWT 统计 |
| DMA1_Channel5 | 1 | 编码器 SPI TX | 入口/出口 DWT 统计 |
| ADC1_2 | 2 | 被测电流环 | 同周期前后快照 |
| UART/日志 DMA | 6 | 通信 | 不能抢占 ADC，不计入高优先级集合 |
| SysTick / PendSV | 15 | RTOS tick / 调度 | 不能抢占 ADC，不凭空算作来源 |

FDCAN 当前是任务轮询，没有据此添加不存在的 FDCAN IRQ 统计。SVC 是调度启动路径，不是这一运行期的周期抢占源；NMI/HardFault 属异常终止，不属于正常 FOC 工作负载归因。

`FocPreempt_CheckPriorities()` 在任务中只读核对上述优先级、grouping，并扫描实际启用的外部 IRQ。发现未插桩的更高优先级源时，`PRIORITY ok=0`，归因标为无效，拒绝真实 CCR probe。没有修改任何 NVIC priority、SysTick、IRQ enable 或系统负载开关。

## 2. 如何累计与计算

新增 `FocPreempt_IrqBegin/End()` 包住现有四个 ISR 的工作体。每源记录 `count / cycles / max_single / invalid`：

- `cycles` 是可相加的 **exclusive** 累计值。TIM7 能嵌套编码器 IRQ，因此 TIM2/RX/TX 的 inclusive 时间要扣除期间 TIM7 增量；三个同级编码器 IRQ 不互相嵌套。
- `max_single` 是单次 **inclusive** 时间，便于看一次服务有多长，不能拿它们的 max 相加。
- 每个源只有本 IRQ 一个写者；ADC 在入口/出口读取累积快照。若 IRQ 恰好打断多字快照，计数校验会将该帧标为 invalid，不关中断、不循环重试。

同一个 ADC 帧内计算：

```text
wall_cycles       = exit_dwt - entry_dwt
irq_delta[i]      = exclusive_total_after[i] - exclusive_total_before[i]
preempt_cycles    = irq_delta[0] + irq_delta[1] + irq_delta[2] + irq_delta[3]
active_est_cycles = wall_cycles - preempt_cycles   （仅有效帧）
us                = cycles / 170                 （当前已校验 170 MHz）
```

`FocPreempt_End()` 返回同一 wall 值给现有外层耗时保护记录器，原有 8500-cycle / 50 us 阈值不变。不是在不同周期中挑两个 max 相减。

### 测量开销说明

`active_est` 不是纯控制数学 WCET：它仍包含未被 IRQ hooks 包住的异常入栈/出栈、hook 自身边缘开销以及 ADC 路径内的诊断/真实提交开销。完整物理异常入口/返回的时间不能仅靠 C 函数入口/出口计数精确拆尽。

ADC 出口时间戳之后的统计归约/首次快照保存另计 `observer_tail_max_us`；最后几条发布/返回指令及原有保护记录尾部不在该尾部数字内。不要将 `wall_max` 单独当作包含所有插桩尾部和 exception return 的完整 ISR WCET。入口时间戳前少量快照准备同样未计入 wall。

本轮保留现有框架已有的短临界区；**新增抢占 hooks、快照和 CCR probe 本身不新增 PRIMASK/BASEPRI mask**。没有为获得好看的数据屏蔽高优先级工作。

## 3. deadline miss 快照

`foc_preempt_timing.first_miss` 冻结首次 wall deadline miss 的同周期：

- wall / preempt / active_est；
- 四个 IRQ 各自的 exclusive cycles 与 count；
- dominant IRQ、valid 标志、原判别器 path 标签；
- path：0 NONE（初始化值），1 NORMAL，2 SUSPECT，3 UNRESOLVED；沿用已有路径标签，不替代独立 fault snapshot。

`worst_preempt` 另保存最大有效抢占周期。两个快照不混用。FOC TIMING 的总 max 覆盖外层 ADC 路径，不自动等价于“健康 NORMAL 路径 max”；判断超时类型时要读 path 和已有故障记录。

## 4. 真实 CCR 写入与硬关闭

`ProtectedLoop_SetDuty()` 的新诊断分支仍锁定 SD、清 MOE/AOE、关闭 CCER；不允许进入电机 RUNNING。然后在正式 duty 提交位置：

1. 记录独立的 hypothetical duty 到达点。
2. 用现有、不改数学结果的 planner 生成 FOC duty plan。
3. `FocAdcTiming_HardOffCommitProbe()` 检查 SD=0、MOE=0、AOE=0、CCER=0、活动 ADC 帧、时钟已校验、TIM1 几何与 preload 正确。
4. 记录 `begin`，短暂置 UDIS，**实际写 CCR1/CCR2/CCR3**，DMB，释放 UDIS，立即记录 `end`。
5. 复查硬关闭状态及 CEN；不满足条件的证据标无效/blocked。

probe 不写 CCR4，不发 UG，不主动启动 TIM1，不写使能 SD/MOE/CCER，不改变采样相位/频率。诊断版允许在功率硬关闭时记录一次“过晚提交”，不把此路径用作可带电的生产提交函数。正常 `CommitBeforeBottom()` 及其拒绝 late-write 的保护不变。

离线寄存器 mock 确认写的是 CCR1/2/3，拒绝 SD/MOE/AOE/CCER 未关闭的情况。**这不是声称本轮已经在物理 MCU 上执行过写入或验证过栅极电平。** U/V/W 物理断开仍是后续人工验收条件，软件不能识别动力线是否真的拔下。

## 5. TIM1 的 latch 语义与 margin

依据当前 `MX_TIM1_Init`、寄存器条件及仓库所带 STM32 HAL/LL：

- center-aligned mode 1、PSC=0、ARR=4249、RCR=0；计时器与 DWT 期望同为 170 MHz。
- CCR1/2/3 preload 已启用；CH4 PWM2、TRGO2 OC4REF，ADC injected 使用配置的上升沿触发。
- RCR=0 时自然 UEV 在顶点和底点发生；CMS=1 的方向选择不能误当成“只有一种端点会 UEV”。
- preload 在符合条件的 UEV 转入 active shadow。UDIS 期间 UEV 被抑制；本 probe 不强制 UG。跨过一个端点后，不能把更后面的端点当成原计划已经按时生效。

记录点含 `CNT / DIR / DWT / span / valid`，首次 IRQ 还保存 CR1、CR2、ARR、PSC、RCR、CCMR1/2、ADC1 JSQR。读 CNT 前后以 DWT 夹住，DIR 改变或观测跨度过长时拒绝该点。入口/事务开始用早时间戳，结束用晚时间戳，结果偏保守。

```text
distance_to_intended_bottom(entry) = down ? CNT : 2*ARR-CNT
actual_margin = distance_to_intended_bottom(entry) - (write_end_dwt-entry_dwt)

distance_to_next_natural_UEV(begin) = down ? CNT : ARR-CNT
latch_margin = distance_to_next_natural_UEV(begin) - (write_end_dwt-write_begin_dwt)
```

- `actual_margin_min_us`：真实事务结束相对本帧原目标底点的最小有符号余量。
- `actual_late_count`：该余量 <= 0 的有效真实提交数。
- `guard_warning`：仍用现有 170 ticks guard；0 < margin <= guard 仍会 warning，不直接关闭告警。
- `latch_margin_us / latch_crossings`：事务是否可能跨过开始时的下一个自然 UEV。UDIS 包络跨端点属于可能抑制 UEV 的证据，不是内部 shadow latch 的直接可见观测。
- `actual_commit_count` 统计真实写次数，即使结束点无效也不隐藏该写入；`measured` 只数有效点，`invalid / post_unsafe` 单独输出。`measured=0` 时 margin 的初始 0 **不代表测得零余量**。

`foc_pwm_write_profile` 是 actual，`foc_pwm_duty_profile` 是 hypothetical，分别保存计数与最差点，不共用 margin 字段。没有用 ISR exit 代替 CCR transaction end。

## 6. 低频输出与改动范围

已有 MonitorTask 低频调用 `FocPreempt_Monitor()`，输出 `FOC TIMING / IRQ PREEMPT / PWM COMMIT / HYPOTHETICAL PWM / FOC MISS`。所有 us 格式换算在任务里用整数完成。ISR 只进行固定长度 DWT/寄存器读取、整数统计和标量快照；没有 UART、printf、动态内存或新的等待循环。

关键 diff：

| 文件 / 函数 | 本轮新增 |
| --- | --- |
| `foc_preempt_probe_stm32.c`：Begin/End、IrqBegin/IrqEnd、CheckPriorities、Monitor | 同周期 exclusive IRQ ledger、快照、只读优先级核验、任务打印 |
| A/B `ADC1_2_IRQHandler`、`ProtectedLoop_AdcProfileEnd` | 新配置下前后快照，回传同边界 wall |
| 编码器 TIM2/RX/TX wrapper、TIM7 wrapper | 四源入口/出口计数，不改 ISR 工作体逻辑 |
| `ProtectedLoop_SetDuty` | 仅新硬关闭诊断分支真实提交 preload |
| `foc_adc_timing_stm32.c`：PwmPoint、HardOffCommitProbe | 无新增 mask 的实际事务采样、独立 actual/latch 统计 |
| A/B CMake / presets | 默认 OFF 的独立配置；不改变正式配置 |
| A/B `Protocol_HandleLine` 声明附近 | 仅新配置将任务命令分发按 `-Os` 编译以适应固定分区；命令/协议行为不改 |

原 ADC 时序适配器保持 `-O2`，FOC 控制数学、编码器/guardian 优化设置保持原样。新诊断归约模块按 `-Os` 编译。新增真实 plan/commit 和插桩会改变诊断镜像自身耗时，后续数据要注明镜像版本，不能当成历史镜像的追溯性证明。

**未改** current discriminator、CUR_CONFIRM、reference rebase、PI、SVPWM、PWM/ADC 频率、硬过流及其他阈值、速度/位置/拧紧状态机、CAN/Pigweed/IAP 协议逻辑或 boot 选择。

## 7. 编译与离线测试

可复现入口：`python tools/preempt_commit_offline.py`。它只有构建和 host tests，不包含任何串口、烧录、调试器或启动选择操作。

矩阵：主工程 Debug，以及 A/B 两侧 FastCurrentReject、FastCurrentRejectComputeOnly、FastPathTiming、PreemptCommitProbe，共 9 项。

回归：18 个测试模块，共 102 个测试；新增测试以 `-Os` / `-O2` 实际编译生产 hooks/提交适配器，覆盖嵌套不重复记账、同周期首 miss、计数回绕、快照被打断、优先级不匹配、真实三 CCR 写入、硬关闭拒绝条件、UDIS 期间跨 UEV、actual/hyp 分离。旧 CCR 原子性测试只修正了函数定位范围，保留原断言。

最终构建收据及各项日志：`tests/foc_adaptive_build/preempt_commit_evidence/receipt.json`。编译 warning 对比检查针对本轮改动单元运行 `-fsyntax-only` 与原 compute-only 基线比较；旧版既有 unused-function / RWX LOAD 告警不能说成已消失。

诊断镜像固定分区检查：

| 配置 | BIN / Flash 占用 | Flash 余量 | RAM 占用 / 上限 | BIN SHA-256 |
| --- | ---: | ---: | --- | --- |
| A PreemptCommitProbe | 228524 B | 852 B | 128448 / 131008 B | `6673490d00bab3958583b73474efd065daa60f8332ea1938861bb59b027dba9c` |
| B PreemptCommitProbe | 227412 B | 1964 B | 128432 / 131008 B | `bfc2e0e1cb28e1c44753481a7c0d2f9b1a9852c26d5985b0c374861f2eb1e231` |

原 A FastCurrentRejectComputeOnly BIN/ELF 及 A FastPathTiming BIN/ELF 与此前固定哈希一致。以上余量只是链接边界检查，不替代完整运行期任务栈余量验证。

本轮没有物理 max/margin 数值，也没有新的电机验收结论。后续须检查 `PRIORITY ok=1`、snapshot valid、actual measured>0，再根据真实事务的 margin 与 latch crossings 判定是否存在 late-write。

preemption attribution + safe real CCR commit probe 已实现，等待人工上板验证
