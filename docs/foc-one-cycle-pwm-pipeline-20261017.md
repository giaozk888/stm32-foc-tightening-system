# 一拍 PWM pipeline、TIM7 优先级与非侵入提交探针

日期：2026-10-17。范围：离线实现、编译、host 回归及功率硬关闭板测准备。

**没有刷板，没有访问调试器/串口，没有启动电机，没有改变 B 槽启动选择。实机 late-write 是否归零尚未测量。**

## 1. 配置边界

新增默认关闭的 `OneCyclePwmPipeline` preset，A/B 均可构建；继承
`FastCurrentRejectComputeOnly` 的硬关闭约束。编译时必须同时具备
`FOC_ONE_CYCLE_PWM_PIPELINE`、`FOC_PREEMPT_COMMIT_PROBE` 和
`FOC_FAST_REJECT_COMPUTE_ONLY`。

新提交函数还在运行时要求 SD=0、MOE=0、AOE=0、CCER=0。任一不符即拒绝，
不修改使能位。该配置不能用于带电驱动；原带电配置没有被偷偷切换到新调度方式。

原因：当前 main 中 TIM1 BREAK、BREAK2 均为 DISABLE，未找到已经启用并验收的
TIM1 BREAK/driver-fault 中断链。外部驱动板自主过流不能由代码检查替代验收。
因此本次不把降低软件守护优先级解释为“已证明硬件安全响应不变”。

## 2. 一拍交接

```text
ADC IRQ k：
  只读 wall/IRQ 时间戳
  → PwmEntry：提交上一有效 pending(k-1)
  → 读取 ADC(k) / 原判别器 / 原 FOC
  → PwmStage：仅保存 pending(k)，不写 TIM1

ADC IRQ k+1：
  → 提交 pending(k)
```

`ProtectedLoop_PwmEntry()` 是向量内第一个控制动作，在 ADC 读数、校验、HAL、
FOC 数学之前；并不是 Cortex-M 异常入口的第一条机器指令。被动归因时间戳在它之前。

正常样本新增固定 **1 个 ADC 周期，20 kHz 下约 50 µs** 的发布延迟。
这不是整个闭环的端到端延迟，也不包括等待 preload latch 的相位时间。
坏样本期间重复保持旧命令，命令年龄可以超过一拍；原确认/保护仍限制异常持续。

原判别器拒绝 suspect/unresolved 样本时，不调用正常 FOC，不更新电流 PI/积分器，
不生成修补电流，不覆盖上一有效 pending。后续入口可以再次提交同一有效命令。

启动先复用原工程 0.5/0.5/0.5 neutral 初始化；pending 保存 neutral 但 `valid=0`。
校准完成前不提交，首个正常样本只生成 pending，下一入口才有第一次真实提交。
STOP、EmergencyOff、controller reset 和模式切换均使 pending 无效；模式 epoch 或
ADC 序号不连续也使其无效。故障路径先关输出，再清槽；没有新增故障自动清除/重试。

## 3. TIM7 与 FreeRTOS 审查

NVIC 数值越小优先级越高，当前使用 4 位抢占优先级，无子优先级：

| 路径 | 原诊断配置 | 新硬关闭 pipeline |
|---|---:|---:|
| TIM7 软件健康守护 | 0 | 3 |
| TIM2 编码器时基 | 1 | 1 |
| DMA1 CH4/CH5 编码器 | 1 | 1 |
| ADC1_2 / FOC | 2 | 2 |
| SysTick / PendSV | 15 | 15 |
| TIM1 BREAK / driver fault | 未证实启用 | 未擅自新增或更改 |

FreeRTOS：`configPRIO_BITS=4`，
`configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY=5`，
`configMAX_SYSCALL_INTERRUPT_PRIORITY=0x50`。ADC=2、TIM7=3 都在禁止调用
FreeRTOS API 的高优先级区；检查的 TIM7 健康/保护/关断调用链没有 FromISR API。
新增静态断言防止修改 syscall ceiling 后仍静默复用本审查。

仅改 NVIC 不够：旧 TIM7 把整个健康检查包在 PRIMASK 内，仍能阻挡 ADC。
新配置将只读健康检查移出长临界区，ADC 可抢占；进入短保护状态更新临界区时，
若 ADC 序号已变化，丢弃旧快照，避免拿旧 now 与新 last_sample 做无符号减法误判。
保护状态 poll/关断仍有有界临界区，不能声称 ADC 完全没有入口阻塞。

TIM7 降级后，其软件超时响应也受更高优先级 ISR 调度影响；硬关闭板测需要确认
ADC WCET、短临界区及守护响应。真实硬件安全路径若存在，应独立于该软件守护。
本次不新增、绕过或修改任何过流判别/阈值。

## 4. UDIS 与真实 margin

已删除诊断 `FocAdcTiming_HardOffCommitProbe()` 及其 UDIS 操作，替换了依赖旧
侵入探针的 host fixture。旧 `PreemptCommitProbe` 配置现在只保留 hypothetical
观察；要真实提交，必须明确选择新的 `OneCyclePwmPipeline`。

新高频路径只写 CCR1/2/3，不写 CR1.UDIS、EGR.UG、SR、CCR4、MOE、SD 或 CCER。
原正常初始化/原带电路径的功能性 `FocAdcTiming_CommitPrepared()` 事务未修改，
其中仍保留原有 UDIS。这与“调试探针不允许改变 update 行为”是两回事。

真实配置检查：TIM1 center-aligned mode 1、ARR=4249、PSC=0、RCR=0，CCR preload
开启，TRGO2=OC4REF、原 ADC injected 触发不变。RCR=0 时两端存在 update/latch；
本提交只接受下数段，目标是该入口之后的 **同一个 bottom**，不是错过后再取模找
下一个 bottom。

在提交函数内、准入检查之前，读取 DWT/CNT/DIR 作为 begin；三次真实 CCR store
及 DMB 后读取 end。在 170 MHz CPU/TIM1 同时钟、PSC=0 的已认证配置下：

```text
actual_margin_ticks = begin.CNT - (end.DWT - begin.DWT)
actual_margin_us    = actual_margin_ticks / 170
```

使用早 begin / 晚 end 的保守边界；包括准入检查与三次写入的成本，不是 ISR exit
位置的推测。异常时钟/方向/观测跨度使证据 invalid，不把零计数当作已通过。
保留原 170 ticks guard，不足时在写入前拒绝。实际写入但证据无效、目标越界、
跨 latch 风险分别计数。未直接观测硬件内部 shadow latch，仍不是完整 WCET 证明。

真实字段：`foc_pwm_write_profile`、`foc_ccr_probe_hard_late` 等；
假设尾部字段：`foc_pwm_duty_profile`。两套统计不混用。
新离线解码器把旧 RAM 布局字段 `possible_suppressed_uev_count` 显示为
`possible_mixed_latch_count`：新路径没有抑制 UEV，只可能跨越更新边界。

## 5. 耗时与归因

保留同周期 wall/preempt/active_est、首次 miss IRQ breakdown、deadline miss。
TIM7=3 不再计作 ADC=2 的抢占来源；TIM7 自身累计值标为
`SERVICE_WALL_INCLUDING_CHILDREN`，可以包含 ADC 抢占，不能与 ADC 抢占量相加。
TIM2/DMA=1 仍作抢占累计。

新增 `foc_pending_commit_max_cycles`、`foc_pending_generation_max_cycles`、
`foc_tim7_preempt_max_cycles`，MonitorTask 低频输出。提交 max 覆盖到诊断归并完成，
仅计入走到归并的提交尝试，不含提前拒绝返回；生成 max 包括原 planner、只读假设
观察与 pending 发布，不只三个内存赋值。它们均可能包括 probe 本身开销。

wall 边界保留既有 profiler 定义；observer tail 单独统计，不能冒充完整异常
进入/退出 WCET，也不能把来自不同周期的各项最大值直接相加。
ISR 中没有新增 printf/UART、动态内存或复杂循环。

## 6. 离线验收与产物

运行：`python tools/pwm_pipeline_offline.py`。

构建 11 个配置：基础 foc2 Debug；A/B 的 FastCurrentReject、
FastCurrentRejectComputeOnly、FastPathTiming、PreemptCommitProbe、OneCyclePwmPipeline。
原历史实测 build 目录不覆盖，旧配置复核放在 `build/PipelineReview/`。

回归共 111 项 unittest；新增 pipeline 模块 9 项，其中 adapter/binding/归因/
CUR_CONFIRM 均按 -Os/-O2 测试。真实提交 mock 还逐个覆盖 15 种准入/异常场景。
离线测试不是 MCU 耗时测量。

覆盖：neutral 未就绪不提交、本拍生成下一拍提交、invalid 冻结 PI 并保持 pending、
fault/STOP 无危险提交、mode epoch 清空、CUR_CONFIRM 原 2-good/4-cycles 不变、
优先级/抢占归因、无 UDIS/UG、无功率使能、旧快照丢弃，以及解码器镜像匹配拒绝。

新增代码没有相对基线增加编译 warning/error；原 unused-function、unused meta 和
链接 RWX warning 仍存在，没有通过屏蔽编译选项掩盖它们。

| 新镜像 | Flash 使用 / 229376 B | RAM 使用 / 131008 B |
|---|---:|---:|
| A OneCyclePwmPipeline | 229236 B | 128792 B |
| B OneCyclePwmPipeline | 228220 B | 128776 B |

A Flash 仅余 140 B、RAM 余 2216 B：这是链接预算，不代表运行栈高水位通过。
完整构建/test 日志、最终 SHA256 和内存占用：
`tests/foc_adaptive_build/pwm_pipeline_evidence/receipt.json`。

新产物：`foc2_app_a/build/OneCyclePwmPipeline/foc2.{elf,bin,hex}`，B 同路径。
离线解码：`tools/pwm_pipeline_report.py`，要求同批完整 Flash/RAM、A 槽 VTOR 及
精确匹配 ELF/BIN；不会访问设备。旧板测 runner 的固定镜像校验未放宽。

## 7. 关键修改位置

| 位置/函数 | 修改 |
|---|---|
| A/B `ADC1_2_IRQHandler` | ADC 读取前增加 PwmEntry |
| `foc_pwm_pipeline.h` | pending/序号/mode epoch 核心 |
| `ProtectedLoop_PwmEntry/PwmStage/PwmInvalidate` | 入口交接、尾部生成、撤销 |
| `ProtectedLoop_SetDuty` | 新配置仅 stage，不直接提交 |
| `ProtectedLoop_Init/Stop/EmergencyOff` | neutral/valid 生命周期 |
| A/B `FOC_ResetController`、`MotorControl_Set*` | 模式/控制器变化清 pending |
| `FocAdcTiming_PipelineCommit` | 硬关闭三 CCR 非侵入提交与实际 margin |
| `TIM7_DAC_IRQHandler`、`ProtectedLoop_TimerHealthy` | 软件守护优先级3、缩短遮蔽 ADC 的区域 |
| `FocPreempt_*` | 适配低优先级 TIM7，不误计抢占 |

未修改 PI Kp/Ki、速度/位置环、Clarke/Park、SVPWM 数学、电流判别器阈值、
CUR_CONFIRM、reference rebase、保护阈值、频率、电角零点、拧紧、CAN/Pigweed/IAP
或 A/B 槽算法。本次改变的是 PWM 发布调度，因此闭环相位特性仍需重新资格验证。

## 8. 留给人工上板的判据

只在动力线断开、SD/MOE/CCER 关闭条件下验证。至少同时取得：
actual_commit_count>0、有效点>0、actual_late_commit_count=0、blocked=0、invalid=0、
post_unsafe=0、margin 超过原 guard、priority audit 通过、deadline_miss=0，以及
同周期 IRQ breakdown。零 actual commit 不能算零 late 的通过。

本次不动态改 CCR4，因此只是原固定触发下的数字提交时序验收；不能由该结果推断
任意占空比下低侧电流采样窗口有效，更不能直接宣布电机/扭矩验收通过。

**one-cycle PWM pipeline + TIM7 priority review + non-invasive CCR probe 已完成，等待人工上板验证**
