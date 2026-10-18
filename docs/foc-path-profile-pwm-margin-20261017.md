# FOC 分段计时与 PWM 更新余量定位

日期：2026-10-17。本轮只做静态审计、诊断插桩、编译和离线回归。没有连接调试器、刷写、复位、开启功率桥或启动电机。

## 结论先说

1. **尚不能把 42.06 us 归因到某一个计算阶段。** 旧记录提示优先排查高优先级中断抢占：被测抢占体峰值由 3.66 us 增至 22.71 us，而原统计的扣除抢占后工作峰值由 14.25 us 增至 17.47 us。两版观测长度也完全不同。新增同帧分段账本用于下一轮板测定因，本轮没有虚构“优化后阶段耗时”。
2. **现有 PWM 告警不是实际 CCR 写入过晚的证据。** 它比较 ISR 结束时间与入口时估算的 bottom 预算。上一轮是 HARD_OFF 计算版，`CHECK=0 FAIL=0`，运行期 duty 分支不写 CCR，仍累计 `BOTTOM_LATE=20313`。不能因此认定带输出版本安全，也不能直接关闭告警。
3. 已分开记录实际 CCR 事务与假设 duty 提交位置，加入有符号、本轮目标 bottom 的余量，以及下一自然 UEV 的余量。**最终 A（真实 late-write）/B（旧判据保守）分类、阶段最大值及 <30 us 目标，均待人工上板证据。**

## 1. 19.64 us 和 42.06 us 不是等长对照

历史数据均来自本地保存的实测收据，不是本轮 PC 运行时间：

| 项目 | 旧快速拒绝版 | 已通过 CUR_CONFIRM 版 |
| --- | ---: | ---: |
| 外层正常路径最大 | 3338 cycles / 19.6353 us | 7150 cycles / 42.0588 us |
| 现有内部 CPU 工作峰值 | 2422 cycles / 14.2471 us | 2970 cycles / 17.4706 us |
| 现有内部被测抢占体峰值 | 622 cycles / 3.6588 us | 3861 cycles / 22.7118 us |
| 观测情况 | 校准后约 0.1494 s 即故障 | 健康确认后观察 31.5236 s |
| 50 us deadline miss | 0 | 0 |

来源：`docs/foc-fast-current-reject-board-20261016.md`、`docs/foc-cur-confirm-cycles-board-20261017.md`，以及私有本地收据 `fast-reject-trial-1792149041071958600.json`、`cur-confirm-trial-1792202130676075100.json`。

内部 CPU、抢占、外层总最大值的边界不同，且峰值可能发生在不同帧。**禁止把表中独立最大值相加、用 42.06 减 22.71 当作同帧 CPU 时间，或计算某模块的耗时占比。** 现有记录只能说明抢占是重要嫌疑，不能证明主因已经唯一定位。

当前优先级为 TIM7 guardian=0、编码器 TIM2/RX DMA/TX DMA=1、ADC=2，前两组可抢占 ADC。没有修改这些优先级或频率。

## 2. normal fast path 审计

| 位置 | 审计结果 / 计时归属 |
| --- | --- |
| ADC 入口、pair 就绪、JDR1 读取、JEOS 提前应答 | `adc_read`；包括入口适配和 timer 观察开销，不冒充纯两次 JDR load 的耗时 |
| 原码缓冲 | `raw_diagnostics`；ISR 仍只存原码/发布缓冲；块统计和格式化已在任务中 |
| `ProtectedLoop_Pair` | `current_validation`；包含现有整数判别、保护状态、健康寄存器检查，不调整逻辑 |
| 浮点原码转换、边界检查、READY 时 PI reset、旧统计等 | 分配到相应边界的 `other_diagnostics`，不改转换结果 |
| Clarke/Park、sin/cos | `clarke_park` |
| 电流 PI、矢量限幅、anti-windup | `current_pi_and_limit`；原表达式和参数不动 |
| inverse Park | `inverse_park` |
| SVPWM | `svpwm`；原表达式不动 |
| `PWM_SetDuty` 分发、现有硬关闭动作 | `duty_dispatch`；**不是纯 CCR 写入耗时** |
| 尾部角度推进、旧 profiling、入口/出口诊断 | 其余部分归 `other_diagnostics` |
| `CommitPrepared` 实际 CCR1/2/3/4 事务 | 独立 `cycles_ccr_write_max`，与 duty 分发分开 |

故障快照和 timeout 快照只在故障冷路径复制，不是每个健康 normal frame 都复制。新增正常账本也排除已故障的帧。hold/确认计数属于可疑或未决分支，不能直接当作 normal 数学开销。

正常注入路径不调用 `HAL_ADC_IRQHandler`；ADC 错误处理在输出关闭后才进入 HAL。RCC/HAL 频率认证不在每帧执行。没有发现可以在无板端分段证据的情况下，直接删掉而不影响现有保护语义的“大块 normal 诊断代码”。因此本轮不盲目降频健康检查、不移走保护、不调整控制数学，也不声称已完成耗时优化。

## 3. 新增计时的含义

新增 `FOC_FAST_PATH_PROFILE`，默认 OFF。独立 A/B `FastPathTiming` preset 继承功率硬关闭的 `FastCurrentRejectComputeOnly`；不覆盖原验收输出目录，不准许这个插桩镜像启动电机。

`FocProfile_Begin / Mark / End` 使用 DWT CYCCNT。每段同时读取同一测量区间的嵌套 IRQ union，分别维护 wall max 和扣除被测 IRQ 后的 CPU max。只保存最大值及一帧完整的 worst-total 分段数据，固定 9 段；无 printf、UART、动态分配或浮点单位换算。us 换算只在离线解析器中进行。

另外保存四个高优先级 IRQ 的 inclusive body max 和调用次数，用于区分 guardian、编码器定时器、RX DMA、TX DMA。它们可能嵌套，**不可相加**；精确扣除使用分段同区间 IRQ union。

短 PRIMASK 只用于一致地读取 DWT 和 IRQ union，不在整段数学计算期间禁止抢占。异常压栈/退栈、hook 外开销仍计入所谓 CPU，不是精确纯指令 WCET。

分段 total 在 reducer 前截止；原外层 `cl_current_cycles` 的 8500-cycle 判据仍在 reducer 后测量，因此插桩汇总成本没有被藏到原 deadline 外。外层原有 recorder 尾部及硬件异常入口/返回仍不在该计时区间内。不能把插桩版比生产版多出来的成本随意扣除后宣称通过。

### 新版结果状态

| 所需结果 | 本轮状态 |
| --- | --- |
| ADC、validation、transform、PI、inverse、SVPWM、duty、other 各阶段 max cycles/us | 已具备采集字段；未上板，未测 |
| normal total max / normal CPU max | 未测；保留旧结果 42.0588 us / 内部 CPU 17.4706 us 作背景，不冒充新版值 |
| `deadline_miss` | 新版未测；旧版 0 不等于新版已通过 |
| 实际 CCR write 最小 margin | 未测；没有写入时必须显示 null，不能显示 0 us 或安全通过 |
| 实际 late update / UDIS 跨 UEV | 未测 |
| <30 us 及明确 PWM 安全余量 | 尚未验收 |

## 4. TIM1 和 shadow latch 的实际关系

检查了初始化、HAL/LL 定义和生产提交路径：

- center-aligned mode 1；PSC=0、ARR=4249、CKD=DIV1、RCR=0。
- TIM1 时钟经现有认证为 170 MHz，与 DWT CPU 时钟同速，1 tick = 1/170 us。
- CH1/2/3 PWM1，CH4 PWM2；TRGO=RESET、TRGO2=OC4REF。
- ADC1/2 各一 injected rank，同一个 TIM1 TRGO2 rising；仅 ADC1 拥有完成 IRQ。
- 四路 CCR preload 开启；`CommitPrepared` 在短 UDIS 事务中写 CCR1/2/3/4，之后恢复 UDIS。运行中不强制 UG，只有 CEN=0 初始化时才 UG。
- **RCR=0 的中心对齐自然更新在 top 和 bottom 都可能发生。** CMS=1 限制 CC 中断的方向，不等于只在 bottom 更新。

现有 checked commit 明确选择 down-counting 段、当前 ADC 帧之后的 bottom，并保留 170 ticks（约 1 us）guard。没有更改其准入或失败判据。

以当前计划器半占空比时 CCR4≈4184 为示意，计数轴为：

```text
上数 CCR4 上升沿 → ADC sample/conversion → ISR entry
                  → top UEV → 下数 → 本帧目标 bottom UEV
                         FOC compute → CCR preload write
```

从触发接近 top 到 bottom 只有约半周期，即约 25 us，而不是完整 50 us。精确剩余时间要扣除 ADC 转换、IRQ 入口延迟和已用计算时间。首次 top UEV 通常发生在新计算结果提交之前，因此“下一自然 UEV”和“本次计算意图赶上的 bottom”必须分开。

## 5. 写入余量如何记录

在实际 `CommitPrepared` 的 UDIS 前、恢复 UDIS 后记录 DWT、CNT、DIR；入口另外记录对应 timer 点。DIR 前后不一致、时钟未认证、CEN/几何不符、观测跨度过大等情况记 invalid，不能当安全证据。

在 DWT 与 TIM1 同速、入口对应本帧采样且几何有效的条件下：

```text
entry_to_bottom = entry.DIR_down ? entry.CNT : 2*ARR - entry.CNT
elapsed         = write_end.DWT - entry.DWT       // unsigned，支持 DWT 回绕
signed_margin   = entry_to_bottom - elapsed
```

`pwm_update_margin_ticks_min` 保持有符号；负值表示已经错过**入口锁定的本轮 bottom**，不能用写完时“距离再下一个 bottom”重新算成正值。entry 采用 CNT 之前的 DWT，end 采用 CNT 之后的 DWT，形成保守边界；最坏余量的 entry/end 点成对保留。

同时计算 `next_uev_ticks_min = DIR_down ? CNT : ARR-CNT`，扣除观测跨度。记录 `late_update_count`（margin≤原 170-tick guard）、`cycles_ccr_write_max`、`possible_suppressed_uev_count`。最后一项表示包围 UDIS 的事务跨度可能跨 UEV，不是直接看到了内部 shadow latch。

**证据边界：** CNT/DIR/DWT 不能直接读出内部 active CCR，也不能单独证明 ADC 触发到 ISR 入口没有跨过目标更新点。若出现 ADC 延迟/积压、观测 invalid、时钟不符或 UDIS 跨界可能性，应保持未证实状态；需要结合触发时序/更新事件证据，不能仅凭一个正 margin 宣告 PWM 安全。

`foc_pwm_write_profile` 只统计 ADC 帧内实际 CCR 事务，初始化时写 CCR 不冒充正常提交。`foc_pwm_duty_profile` 只统计硬关闭计算版的**假设提交位置**，`writes` 永远为 0。实际写入计数即使观测 invalid 也保留，不把“证据无效”误解成“没有发生写入”。

当前硬关闭分支不会执行运行期实际 CCR 提交，因此这次准备的镜像可定位数学/抢占及假设余量，但不能独自完成真实写入 A/B 分类。生产实际事务观察代码和 host 测试已经准备；不能为获得数字而在本轮擅自开启运行期输出或改变提交流程。

## 6. warning 判定结论

旧逻辑 `FocAdcTiming_IrqExit` 仍原样保留：`ISR_elapsed >= entry_remaining_ticks` 累计 BOTTOM_LATE。它可能包括 CCR 写完后的统计/尾部，也可能像上轮一样根本没有运行期 CCR 写入。

- A 类证据：有效实际写入观测表明本轮 bottom 已过，或余量耗尽；UDIS 可能跨 latch 点时也不能宣称安全。
- B 类证据：同一观测窗口实际提交完整、有效，满足目标 bottom 和下一相关 latch 的时序要求，余量充足，但旧 ISR-end 粗告警仍增长。还须排除漏采/invalid/触发积压；不能只选一帧证明整段运行。
- **目前：旧告警的测量对象与实际写入不同已确认，但 A/B 最终归类仍未证实。没有关闭告警，也没有把 42.06<50 当作 PWM 安全。**

## 7. 关键 diff 和函数

本轮在原有未提交改动之上，只增加以下诊断；git HEAD 的完整 diff 还包含以前的工作，不应全部归为本轮：

```c
// ADC 读数、原码缓冲、验证三个边界
FocProfile_Mark(FOC_PROF_ADC);
FocAdcTiming_RecordRaw(u,v);
FocProfile_Mark(FOC_PROF_RAW_DIAG);
int prof_pair_ready=ProtectedLoop_Pair(u,v);
FocProfile_Mark(FOC_PROF_VALIDATE);
```

`FOC_CurrentLoopStep` 仅在原数学段之间增加 Mark；没有改表达式、计算顺序或常量。`ADC1_2_IRQHandler` 增加 Begin，`ProtectedLoop_AdcProfileEnd` 增加 End；`TIM7_DAC_IRQHandler` 及 AS5047P 三个 IRQ wrapper 只增加诊断成本记录。

`FocAdcTiming_IrqEnter` 增加入口和几何观察；`FocAdcTiming_CommitPrepared` 增加实际事务观察；`ProtectedLoop_SetDuty` 的硬关闭分支增加假设位置观察。新文件：`foc_fast_path_profile.h`、`foc_fast_path_profile_stm32.c`、`foc_pwm_write_probe.h`、离线解析器 `tools/foc_path_profile_report.py`。

关闭 `FOC_FAST_PATH_PROFILE` 后，Mark/Begin/End 编译为空，观察分支被剔除。重新编译的原 A 计算版 BIN、ELF 与上轮固定 SHA 完全相同：

```text
BIN 1cbe43061f7879e5550d0db9301c739c2e00ca213e1ec1a3acb12e3fff5a0bdf
ELF 386a5dea822b590e50d2b75ab1f2c72148883b219223dc11360650470c706fc7
```

判别器、CUR_CONFIRM 2/4、reference rebase、硬过流保护、fault threshold、PI/SVPWM、PWM/ADC 频率、外环、tightening、CAN/Pigweed/IAP 均未修改。测试还固定核验五个控制/保护核心文件 SHA。

## 8. 编译和测试

主工程 Debug、A/B FastCurrentReject、A/B FastCurrentRejectComputeOnly，以及新增 A/B FastPathTiming，合计 7 个配置编译通过。没有新增编译告警或错误；原有 unused 告警和 RWX LOAD 段链接告警仍保留，未在本轮顺手修复链接脚本。

最终诊断镜像：

| 镜像 | Flash | RAM | Flash 剩余 |
| --- | ---: | ---: | ---: |
| A FastPathTiming | 229220 B | 128296 B | 156 B |
| B FastPathTiming | 228180 B | 128280 B | 1196 B |

仍使用原 224 KiB 槽和 131008 B RAM 区，未扩槽。A 插桩镜像空间很紧，本轮不据此改变分区或生产链接布局。

```text
A BIN 69f98bc70f9216ed33d9e16af9cc3b9e06b65ac363a0cbc84d57727e5ef610e7
A ELF 3e12f18329d567ea688e5d3577ced86a93fa1917bd8d168b69bec98fe147b774
B BIN c3e58ba474c5486782834ef5a51abaecef3e3f4699f0d4af61816b437057e466
B ELF 0f607995a17d869c22fc11c38c03f9e9292a611910d1b63e899364e0fc2a4bfd
```

离线测试共 90 项通过：

- 原 timeout/CUR_CONFIRM/current protection/closed loop 等 7 个模块：40 项。
- `test_foc_adc*.py`：27 项。
- `test_foc_rc_protected_candidate.py`：7 项。
- `test_foc_pwm_boundary*.py`：7 项。
- 新 `test_foc_path_profile.py`：9 项。

新测试使用生产 DWT adapter、生产 CCR adapter 和 ARM ABI 布局，覆盖同区间抢占、normal-only 统计、DWT 回绕、有符号错过本轮 bottom、top/bottom 区分、实际/假设提交分离、无效观察不冒充无写入、最坏点配对、禁止输出配置、旧镜像不变、无新增编译告警。PC 人工时钟值仅验证算术和控制流，不作为 MCU 性能数字。

现有 `tests/foc_adaptive_build/fast_path_profile_evidence/receipt.json` 只记录原 5 个配置及其 40 项回归，不冒充本轮全部 90 项的机器收据。

## 9. 人工上板后的解析

构建命令在各自 A/B app 目录运行：

```powershell
cmake --preset FastPathTiming
cmake --build --preset FastPathTiming -j 8
```

离线查询镜像身份（不接硬件）：

```powershell
python tools/foc_path_profile_report.py
python tools/foc_path_profile_report.py --elf foc2_app_b/build/FastPathTiming/foc2.elf
```

手动取得同一次停机状态的完整 SRAM、完整 512 KiB Flash 和实际 VTOR 后，使用匹配 ELF：

```powershell
python tools/foc_path_profile_report.py --elf <匹配的ELF> --ram <完整SRAM> --flash <完整Flash> --vtor <同次停住的VTOR>
```

解析器要求三项一起提供、按 Flash 中实际镜像逐字节匹配、核验 BIN/ELF reset entry 和 SRAM 符号布局；它不执行读取硬件/刷写/启动。Flash/VTOR 文件仍须人工保证来自同一停住会话，脚本不能从离线文件自动证明采集原子性。完整备份保持本地私有，不上传。

先取得同窗口分阶段 wall/CPU 和最坏帧抢占分配，才能决定是否把非必要诊断移到任务或降频。未得到真实 CCR 证据前，最小实际余量及 A/B 分类保持未测；不把计算版成功当作带电闭环验收。

profiling / PWM margin 离线插桩完成，等待人工上板验证。

后续实机记录见 [分段耗时与 PWM margin 上板记录](foc-fast-path-profile-board-20261017.md)：本次诊断版触发 1 次外层 50 µs 超时，已恢复原 B；不能把本报告的离线通过当作实机通过。
