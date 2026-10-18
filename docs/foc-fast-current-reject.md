# 20 kHz 电流反馈：两拍判别、冻结电流环、重新定基准

日期：2026-10-16。状态：已用两态判别器修正旧版 reference lockout，代码、PC 回归与 A/B 四镜像编译通过，**新版未上板**。旧版上板正常路径最大 19.64 µs，但连续拒绝触发故障，见 [旧版上板记录](foc-fast-current-reject-board-20261016.md)；此耗时不能当作新版实测值。完整本轮结果见 [两拍判别修订](foc-current-impulse-discriminator-20261016.md)。

## 改了什么

继续使用现有 ADC1/ADC2 同触发、单 IRQ 所有者、提前清 JEOS 的路径。没有重写控制器。

原保护候选的 `ProtectedLoop_Pair()` 调用四点修补，然后调用 `FOC_CurrentLoopStep()`。更早的 HAL 回调甚至会在拒绝样本后，用上一次发布的电流再次计算 PI。新候选不进入这两种路径：

同目录 `foc-fast-current-reject-core.patch` 是**上轮旧版**修改摘录，不是本轮两拍判别器的安装补丁；本轮关键 diff 见修订记录。

```diff
- Trend4 / adaptive repair -> delayed frame -> current PI -> PWM
+ every physical raw pair -> independent raw-current safety
+                        -> integer TRACKING / SUSPECT discriminator
+                           accepted: this pair -> current PI -> PWM
+                           suspect/unresolved: no current PI, no voltage generation,
+                                    no compare/preload write
+                           third consecutive unresolved: existing emergency OFF
```

函数分工：

- `FocCurrentValidation_Push()`：O(1) 整数判定与计数，无排序、预测、分配或 I/O。
- `FocFp_PushRawSafety()`：每个物理采样先参加原码 U/V/W 过流确认，与反馈拒绝独立。
- `FocFeedbackSafety_Push()`：有效才创建当拍 frame；无效返回“不就绪”，不产生修补电流。
- `ProtectedLoop_AdcIrq()`：只有就绪分支调用电流环；连 READY 状态下原有 PI reset 也不会在无效分支执行。
- `ProtectedLoop_AdvanceAngle()`：有效或保持周期均推进既有转子时间基准；不是推进 PI。用有界折返代替新候选的角度 while 循环。
- `FOC_CurrentLoopStep()`：Clarke/Park、PI 增益/积分步长、SVPWM 方向不变。当拍测量角度与执行角度相同，复用一次已检查的 sin/cos。
- `ProtectedLoop_AdcProfileEnd()`：外层 ADC IRQ 的 DWT 计时，覆盖有效、无效、校准/故障路径；达到 8500 cycles 走现有 `CL_COMPUTE_LATE`。
- `ProtectedLoop_CurrentMonitor()`：MonitorTask 每 5 秒快照并输出统计。除短暂一致性拷贝外，除法和格式化均在开中断的任务上下文。

## 判定和保持的确切含义

`FOC_CURRENT_JUMP_THRESHOLD_COUNTS=60`。TRACKING 下整对距离 `max(abs(ΔU),abs(ΔV)) <=60` 接受；否则保存 candidate，进入 SUSPECT、保持一拍，不累计 unresolved。初始 reference 使用合格零点 U0/V0。

SUSPECT 下按顺序判断下一拍 N：

- 回旧 reference 距离 <=25：若中间仅一个 candidate，计 confirmed spike；若已出现 unresolved，计 recovery，不能叫 isolated spike。
- 更接近 candidate 且距离 <=25，或更接近 candidate、距离 <=60 且距旧 reference 不缩短：计 confirmed transition，接受 N、reference=N。
- 其余：只更新 candidate、保留旧 reference，累计 unresolved 并保持输出。

返回/确认容差均为可配置初始值 25，不是带电标定。只有 Case C 连续达到 `FOC_CURRENT_UNRESOLVED_LIMIT=3` 才测量故障；确认 spike/transition/recovery 都清连续计数。三次 unresolved 占 150 µs，**另有最初 suspect 的 50 µs**；从最后有效点到关断最多四个采样间隔约 200 µs，不是全部只 hold 150 µs。原码保护/看门狗可更早关断。
- 恢复有效：用当前真实采样计算一次，积分仍按原 Ts=50 µs，不补算被跳过的积分，也不复用旧电流重跑 PI。
- 保持是不写新的 PWM compare/preload。此前已提交的有效 preload 仍可能在硬件更新事件锁存；独立 STOP/过流/超时可以随时覆盖保持并关断输出。

这里只冻结电流环，不重写速度环、位置环或拧紧状态机。角度时间推进保留；编码器方向、电角度零点和电流极性不变。

## 为什么先保留 60 counts

工程原有阈值就是每通道 60。按 3.3 V、4095 满量程、120 mV/A：1 count 约 6.72 mA，60 counts 约 0.403 A。20 counts 可能是连续小变化；历史零电流记录中相对全局中位数偏离 >40 的事件都是单点，但这个离线基线不是在线基准。

**60 也不是全运行范围已标定的物理上限。** 它约等于每 50 µs 0.403 A 的变化。按现有 L≈42.3 µH，仅用 V/L 粗估，0.8 V 在 50 µs 就可能引起约 0.95 A 变化；实际还受相电压、R、反电动势和工作点影响。因此不把低速/零电流统计推广为高速、大电流的通用噪声判据。上板必须检查合法电流阶跃是否误拒绝；这次不改原有电压、速度或电流指令限幅。

## 保护不被拒绝器绕过

新路径在判定反馈是否可用**之前**，使用所有原码计算：

```
IU_counts = U0 - raw_U
IV_counts = V0 - raw_V
IW_counts = -(IU_counts + IV_counts)
```

现有 4 A / 2-of-3 确认策略改为独立看原码：阈值初始化时换算为 595 counts，绝对值从 596 counts 起命中。W 使用有符号整数重构，不钳到 12-bit 伪原码。单个命中保持 pending；后续两点内再次命中就关断，两个正常点清 pending。连续无效、输入范围错误、时序/序列错误、ADC 丢采、驱动 fault 标志仍走原故障机制。原 25 µs TIM7、100 µs 采样/确认看门狗保留。

核对硬件相关配置的结果：`MX_TIM1_Init()` 当前 `BreakState=TIM_BREAK_DISABLE`，`Break2State=TIM_BREAK2_DISABLE`。通用保护核接收硬件/driver fault 标志，但这不证明存在已接通、已验收的独立 fault 引脚链。**本次未开启 Break、未修改接线，也没有把驱动板自身 OCP 当作 MCU 已验证的自动关断。**

## 如何选择版本

在 A 或 B 的工程目录运行：

```powershell
$env:Path='D:\software\arm\bin;'+$env:Path
cmake --preset FastCurrentRejectComputeOnly
cmake --build --preset FastCurrentRejectComputeOnly -j 8
```

首轮测试使用 `FastCurrentRejectComputeOnly`：真实反馈/FOC 计算，但 START 准入、任务和 PWM 发布三处均排除桥使能。正常候选 `FastCurrentReject` 复用原 START/FSM、既有一次性资格测试范围和 RC 采样窗口准入，不自动启动，也不解除已有资格门禁。

两者继承当前 RC 采样时序候选，**并未解决或绕过此前的 PWM 更新窗口资格问题**。计算版通过不能代替 RUNNING 状态下计划生成/提交的耗时和模拟反馈验收；RC 准入不满足时不能直接做带电 TEST 2。

`FOC_ENABLE_LEGACY_CURRENT_REPAIR` 默认 OFF；新候选明确 OFF。旧 `ProtectedClosedLoop` 及其历史派生预设明确 ON，保留原研究实现与命名。不要用 `RcDeferredShadow` 或通用 `Release` 的历史路径代替这次的新候选。新候选与 deferred shadow / repair trace 混用会编译报错。

启动零点资格校准仍保留原独立稳健零点算法，只在输出关闭时运行；从**校准后的实时反馈路径**移除的是 Trend4、adaptive learning、median repair 和 deferred plan。并未声称整个固件中不再有任何 median 代码。

新候选 Release 全局 `-O2`，无 `-Ofast` / `-ffast-math`；实时主链为 O2/RAM 热路径。原按体积优化的中间件和 HAL 保持 `-Os`，冷 Monitor/诊断命令按 `-Os`，否则 A 槽会溢出。没有调整 224 KiB 槽、IAP、KVS、通信或参数格式；原 Debug / 历史预设优化等级保留。

## 统计口径与时间边界

每 5 秒的 `CURRENT VALIDATION` 行包含 samples、suspect、spike、transition、unresolved、run、max_unresolved_run、fault、recovered，以及 normal/suspect/unresolved 的 max_cycles、总体 last/max_cycles、deadline_miss。cycles 除以 170 得该区间 µs。

- samples：完成校准且通过前置 safety 的物理对；前置硬件/过流故障先关断，不虚构后续 selector 事件。
- suspect：从 TRACKING 进入 SUSPECT 的次数，不叫 spike。
- spike：只在下一拍回旧 reference 且没有 unresolved 时确认；是算法分类，不是物理毛刺真值。
- transition：确认新工作点/有界 ramp 的次数；recovered 为 unresolved 后返回旧工作点次数。
- unresolved：只有 Case C 累计；run/max 为其连续长度；fault 为其触发测量故障的次数（锁存后不重复计）。
- U/V 同时异常仍计一对。计数饱和不回绕，不因 START 清零；只随初始化/复位重建。
- 这些不是历史 78/4311 修补点计数，也不是旧版 invalid=29 的同一指标。
- 正常、suspect、unresolved DWT 指标是外层 ISR 墙钟区间，包含高优先级抢占和原有计时开销。总体还覆盖校准/故障入口。
- **不包含**异常入口堆栈开销、最后统计/关断尾部和异常返回；因此不能把 49.5 µs 当作通过。`cycles/170` 是该区间 µs。
- 8500 cycles = 50 µs；测得超限会关断，但事后计时不能阻止已经发生的 deadline miss，更不能证明 WCET。
- 原 `MOTOR TEST TIMING` 的微秒 WorkEnd 指标和 ADC 相对 PWM bottom 的余量告警仍保留；它们与新增完整区间、固定 50 µs 计数不是同一个口径。

## 本次离线验收

本轮 8 项 unittest + 旧保护/整数 guardian/原 FSM/反馈核回归 24 项全部通过。宿主 C 测试使用 `-Wall -Wextra -Werror -pedantic`，核心与真实 IRQ 包装在 `-Os` / `-O2` 均测试。

覆盖用户指定十组状态机用例、实测端点复现、回落/阶跃/ramp、三次 unresolved、U/V 对一致性、原码独立过流和原有超时/硬件故障。ARM 单独判别核无 VFP/调用/循环；真实 IRQ 测试验证 PI/电压/PWM 的变动函数不被调用。硬关闭版另验 START 拒绝、异常请求不能使能桥。

链接后的 ADC 入口检查：没有 Trend4 / adaptive / median repair、deferred、malloc、UART、printf 调用。新旧同源 `main.c` 诊断对照未新增编译 warning；工程原有未使用函数/变量及链接 RWX warning 保留，未全局屏蔽。

| 镜像 | FLASH 链接占用 / 229376 B | RAM 链接占用 / 131008 B |
|---|---:|---:|
| A FastCurrentReject | 226884 | 125728 |
| B FastCurrentReject | 225852 | 125712 |
| A ComputeOnly | 225068 | 125560 |
| B ComputeOnly | 224020 | 125544 |

上述是链接占用，不是运行栈峰值。RAM 余量较小；Monitor 新统计有额外调用栈，需上板同时检查各任务 stack high-water mark。ISR 栈的静态报告不能替代嵌套中断最坏栈测量。

复查命令（仓库 tests 目录）：

```powershell
python -m unittest test_foc_fast_current_reject -v
python -m unittest test_protected_closed_loop test_latest_original_fsm test_foc_guard_fast test_foc_feedback_fast -v
```

## 上板分阶段计划（短测已执行，完整验收未通过）

1. **功率关闭**：用 ComputeOnly，检查零点、保持输出锁定，运行正常 FreeRTOS/编码器/通信负载。记录至少 30 秒 DWT 与计数。正常目标 <5100–5950 cycles（30–35 µs），整体目标 <6800 cycles（40 µs）、deadline_miss=0。自然毛刺不足时，先以离线注入验证故障逻辑，不把未出现 invalid 的 `invalid_max=0` 称为耗时验收。
2. **低电流空载**：只有上述及既有 RC 窗口/功率保护资格满足，才用保留全部保护的正常候选，沿用现有受控 START/STOP 范围。关注 RUNNING 的 PWM 计划提交路径，其时间不等于 ComputeOnly。任何 deadline miss、unresolved 测量故障等均停下分析。
3. **相近样本长度**：分别记录约 3600 / 4311 对及更长区间的统计，报告 invalid 比率、isolated 占比、两点段、最大段和 normal/invalid 最大 cycles。累计快照做差得到区间计数，运行中不清零；跨区间异常段以闭合时归属计数，需说明边界。长时间另做 ≥30 秒复测。
4. **旧新 A/B 比较**：在相同硬件、供电、采样时序、任务负载、指令下，对历史 repair 与新 hold 分别记录 deadline miss、Id/Iq 峰值、速度稳定性、fault 数及原因。旧 filtered 过流与新 raw 独立过流不同，必须记录，不把 fault 数变化全部归因于筛选优劣。没有数据前不宣称性能优于旧版或已完成电机闭环验收。

## 文件索引

- 核心新增：`firmware_common/foc_current_fast_reject.h`
- 保护/反馈：`firmware_common/foc_filtered_protection_candidate.h`、`foc_feedback_safety_candidate.h`
- 实际绑定：`firmware_common/protected_closed_loop.inc`、`.h`、`protected_adc_irq.inc`、`latest_original_fsm.inc`、`foc_hot_path.h`
- A/B 各自：`Core/Src/main.c`、`Core/Src/stm32g4xx_it.c`、`CMakeLists.txt`、`CMakePresets.json`、`cmake/gcc-arm-none-eabi.cmake`
- 新测试：`tests/foc_fast_current_reject_host.c`、`foc_fast_reject_irq_host.c`、`foc_fast_reject_binding_host.c`、`test_foc_fast_current_reject.py`
- 既有测试夹具扩展：`tests/protected_adc_irq_host.c`、`protected_closed_loop_host.c`

没有修改通信协议、CAN/Pigweed 实现、ESP32、bootloader、IAP 分区、编码器方向、电角度零点、速度/位置环或原拧紧状态机。
