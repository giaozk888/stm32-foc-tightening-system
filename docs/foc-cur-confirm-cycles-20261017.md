# CUR_CONFIRM 按 ADC 周期确认（2026-10-17）

本轮仅修改当前 `FOC_FAST_CURRENT_REJECT` 配置的 CUR_CONFIRM 确认时序及其统计。
未连接调试器、未刷写、未复位、未发送 START、未启动电机。

## 修改位置

- `firmware_common/foc_filtered_protection_candidate.h`
  - `FocFp_Begin()`：初始化确认计数和统计；当前配置不再使用或校验旧 `confirm_deadline_us`。独立 ADC 采样截止时间的校验不变。
  - `FocFp_Poll()`：当前配置取消 CUR_CONFIRM 的 100 us wall-time 故障条件。硬件故障优先级、健康检查、首样本/采样断流截止时间保持不变。
  - `FocFp_PushRawSafety()`：原有原码范围、序号连续性、时间戳以及 U/V/W 电流阈值检查不变；只有验证为新的 ADC pair 后才推进确认状态。
  - 新增 `FocFp_ConfirmPair()`：执行 2 个连续正常样本清除、4 周期未确认故障、统计更新；无循环、动态分配或 IO。
- `firmware_common/protected_closed_loop.inc`
  - `ProtectedLoop_Command()` 仅将原状态描述 `OC=RAW_2_OF_3` 改为 `OC=RAW_CONFIRM_4`，避免错误描述当前策略。
- 对应离线测试和离线构建收据脚本。

历史非 FAST 实验配置、`foc_overcurrent_confirm.h` 的历史策略不改。本轮生成的 A/B 正常版和 ComputeOnly 版均使用新的周期确认逻辑。

## 进入、退出及故障

固定参数：

```c
#define CUR_CONFIRM_CLEAR_GOOD_SAMPLES 2U
#define CUR_CONFIRM_MAX_CYCLES         4U
```

首次原码越过原有电流阈值时进入 CUR_CONFIRM，`confirm_cycles=0`、`good_samples=0`。
触发进入的样本不消耗后续确认预算。

每个后续新 ADC pair 只推进一次：

1. `confirm_cycles++`。
2. 正常则 `good_samples++`；可疑则 `good_samples=0`，不重启周期预算。
3. 连续正常达到 2 个，清除 pending、正常计数、周期计数及待确认相位掩码。
4. 否则周期数达到 4，进入现有锁存故障路径：`FOC_FP_TIMEOUT / FOC_TO_CURRENT_CONFIRM`。

先判断成功，再判断预算耗尽，因此第 4 周期恰好得到第 2 个连续正常样本时允许清除。
第 4 周期只有 1 个连续正常样本时仍故障退出。

预算为进入之后最多 **4 个 ADC 周期**，20 kHz 下名义约 **200 us**。
这不是新的 200 us wall-time 门槛；时间差只作统计。ADC 不再产生新样本时，原有独立的 100 us 采样断流保护仍有效，不能靠没有样本来无限停留。

按照本次指定逻辑，窗口中再次可疑不再沿用旧的“第二次越界即故障”分支，而是清零正常计数，在 4 周期预算内继续确认。这是 CUR_CONFIRM 的时序策略变化，不是硬件过流关断的宽限期。

原板端失败的因果边界回放：首次进入、+50 us 第一个正常样本、+103 us 第二个正常样本，现在正常清除；不会在处理第二个正常样本之前被 100 us 确认定时器抢先停止。

## 独立保护与控制算法

硬件过流/驱动器故障标志在 `FocFp_Poll()` 中优先立即进入故障，不检查或等待确认周期；ADC 断流、ADC 无效、序号错误、健康故障和计算 deadline 保护不变。
外部硬件自行关断电源桥的路径及接线未修改；本轮仅离线验证代码的故障优先级，未重新验证实物硬件关断时序。

未修改 FOC、PI、SVPWM、PWM/ADC 频率、原码电流阈值或 current discriminator。
判别器文件 SHA-256 保持：

```text
a77bf47b2fb3082bf331b0c54782488e253b644cb0f289f4c94b47150288275d
```

## 五项低成本统计

存放在 `cl_safety.protection` 对应的 `FocFilteredProtection` RAM 状态中：

| 字段 | 含义 |
| --- | --- |
| `cur_confirm_enter_count` | 进入确认次数 |
| `cur_confirm_clear_count` | 两个连续正常样本成功清除的次数 |
| `cur_confirm_fault_count` | 确认周期预算耗尽次数，不混入其他故障 |
| `cur_confirm_max_cycles` | 新样本推进时观察到的最大确认周期数，清除后保留 |
| `cur_confirm_max_elapsed_us` | 新样本推进时观察到的最大确认历时，仅统计，不参与故障判定 |

三项事件计数使用 UINT32_MAX 饱和递增，避免溢出绕回；历时计算支持 uint32 时间戳回绕。
统计在显式 `FocFp_Begin()` 初始化时清零，不在每次清除确认时清零。
未新增 ISR printf/UART；本轮也未新增统计串口导出命令。可用匹配构建的符号/布局读取 RAM，不能沿用旧固件的结构体偏移。

故障快照仍为原来的 204 字节。周期耗尽保留 `CUR_CONFIRM` 子原因，其中 `limit_us=0` 表示没有对应 wall-time 限值，不能解释为 0 us 截止时间；实际预算见 `confirm_cycles` 和 `CUR_CONFIRM_MAX_CYCLES`。旧诊断字段 `misses` 与 `good_samples` 共用同一字节。

## 编译与离线测试

复现命令（仅离线，不导入上板脚本）：

```powershell
python tools/verify_foc_timeout_diagnostics.py --incremental --output tests/foc_adaptive_build/cur_confirm_cycles_evidence
```

主工程 Debug、A/B 的 FastCurrentReject、A/B 的 FastCurrentRejectComputeOnly 共 5 个构建全部通过。

| 配置 | BIN 字节 | RAM 字节 | Flash 剩余字节 |
| --- | ---: | ---: | ---: |
| 主工程 Debug | 110912 | 37744 | 不适用 |
| A 正常版 | 229364 | 126192 | 12 |
| B 正常版 | 228228 | 126176 | 1148 |
| A 功率关闭版 | 227492 | 126024 | 1884 |
| B 功率关闭版 | 226444 | 126008 | 2932 |

A 正常版 Flash 余量极小。通过合并确认事件计数更新、缩小该确认辅助函数的代码生成解决首次链接超限；未扩大分区、移除保护或修改 FOC 优化选项。已有 unused-variable/function 和链接 RWX 告警仍存在；现有警告比较测试通过，无新增 main 编译告警。

7 个相关测试模块共 **40 项测试全部通过**：

- 新增周期状态机与有界无 IO 检查 2 项，状态机分别以 -Os / -O2 编译运行。
- 超时快照与真实绑定 5 项。
- 快速电流判别器、真实 ADC IRQ、正常/功率关闭入口、ARM 镜像及编译选项 8 项。
- 电流保护分层 8 项、历史滤波保护 10 项、保护自检 3 项、闭环绑定 4 项。

覆盖 103 us 回放、正常/可疑交替、最后周期成功和失败、连续可疑、独立硬件故障优先、ADC 丢失/重复/跳号/无效、时间戳回绕、计数饱和及故障只记录一次。

完整收据与日志：`tests/foc_adaptive_build/cur_confirm_cycles_evidence/receipt.json`。其中 delta 仍与原超时诊断脚本的历史基线比较，并非本轮净增量。

本轮没有实测新版本 WCET，因此不把旧版 41.64 us 当成新版测量值；50 us deadline 和采样频率均未放宽。历史上板工具固定的是旧镜像哈希，不能直接用来激活这次新镜像。

## 交付状态

离线修改、编译和回归完成。**停在此处等待人工上板验证，不自动刷写、复位或启动电机。**

后续用户已另行请求并完成上板验证，结果见 [功率关闭上板验证记录](foc-cur-confirm-cycles-board-20261017.md)。上述离线收据保持原样，不将其改写为实物证据。
