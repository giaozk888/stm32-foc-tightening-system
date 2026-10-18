# TIMEOUT 子原因与首次故障快照（2026-10-16）

本轮只增加诊断，没有操作硬件、刷写、复位或启动电机。上一轮的 TIMEOUT 原因仍未知，不能把本轮离线测试当成板端定位结果，也不能宣称已通过 30 秒验收或新版仍满足最坏 50 µs。

## 1. 先看审计结论

当前运行的 APP A/B 没有一个全工程共用的 `FAULT_REASON_TIMEOUT`。
最容易混淆的是：`FOC_FP_TIMEOUT=6` 属于电流反馈保护枚举，而主控制 `foc_fault_reason=6` 是控制链失活。不能只看数字 6。

按电机/传感器/隔离测试的**触发语义去重**，本轮诊断分为 **21 类时间来源，另有 1 类被旧代码归入 TIMEOUT 的样本数量上限**。同一条件在 ADC 路径和独立守护中检查，不重复算两类；同一零点流程的不同入口通过实际限值区分。通信、升级回退、离线仿真超时另列，不能声称整个仓库只有 21 个 timeout 调用点。

以下表覆盖本轮的电机故障分类；文件均相对项目根目录。APP A/B 的对应逻辑同步接入。

| 文件 / 函数 | 原触发条件、原常量（保持不变） | 原 reason / 是否压成同一 TIMEOUT | 新 subreason / 日志名 |
| --- | --- | --- | --- |
| `firmware_common/foc_filtered_protection_candidate.h` / `FocFp_Poll` | 尚无首样本，距离 Begin **>100 µs** | `FOC_FP_TIMEOUT=6`，是 | 1 CURRENT_FIRST_SAMPLE / CUR_FIRST |
| 同上 | 已有样本，距离最后物理样本 **>100 µs** | 同一个 6，是 | 2 CURRENT_SAMPLE / CUR_SAMPLE |
| 同上 | pending 等待确认 **>100 µs** | 同一个 6，是 | 3 CURRENT_CONFIRM / CUR_CONFIRM |
| `protected_closed_loop.inc` / PhysicalSeen、TIM7 guard；旧 `foc_feedback_binding_stm32.inc` 对应入口 | ADC 相邻到达间隔 **>100 µs** | 新控制链原为 `CL_BAD_ADC`→HEALTH；旧绑定可为 6 | 4 ADC_GUARD |
| APP `main.c` / `MotorControlTask` | ADC 计数不前进 **>50 ms** | 主控制 reason 5，不是上述 6 | 5 ADC_CHAIN |
| 同上 | FOC 计数不前进 **>50 ms** | 主控制 reason 6，不是 `FOC_FP_TIMEOUT` | 6 CONTROL_CHAIN / FOC_CHAIN |
| `protected_closed_loop.inc` / Health、EmergencyOff | 已运行时外环没有续期 **>2000 µs** | `CL_OUTER_STALE`→HEALTH，不是 6 | 7 OUTER_CONTROL / OUTER |
| `as5047p_dma_engine.c`、`as5047p_dma_stm32.c`、APP encoder consumer | SPI DMA 绝对事务 deadline **200 µs** 到期，或消费到 `elapsed>=200` | `AS_DMA_TIMEOUT`→编码器故障，原丢失具体分类 | 8 ENCODER_TRANSACTION / ENC_XFER |
| APP / `FOC_EncoderSpeedUpdate`（DMA） | 成功样本年龄 **>1500 µs** | 编码器故障 reason 2 | 9 ENCODER_SAMPLE / ENC_AGE |
| `as5047p_dma_stm32.c` / TIM2 CC4 | 消费 ACK 没有在 **2500 µs** 内续期 | `AS_DMA_CONTROL_STALE`→编码器故障 | 10 ENCODER_CONTROL / ENC_CTRL |
| 同上 / TIM2 周期调度 | **1000 µs** 周期应启动点迟到 **>=200 µs**，或该点事务仍未空闲 | `AS_DMA_SCHEDULE`→编码器故障 | 11 ENCODER_SCHEDULE / ENC_SCHED；也可能是 busy，不虚称纯时间迟到 |
| APP / `TighteningTask` RUNDOWN | 阶段 elapsed 达到 recipe `rundown_timeout_ms`，默认 **8000 ms** | `TIGHTEN_OUTCOME_RUNDOWN_TIMEOUT`，非电流保护 6 | 12 RUNDOWN |
| 同上 / CONTACT_STOP | 未完成停稳确认，elapsed 达到 **2000 ms** | `TIGHTEN_OUTCOME_STOP_TIMEOUT` | 13 STOP_SETTLE |
| APP / `FOC_EncoderSpeedUpdate` 失速保护 | 位置模式低速且有指令/电流条件持续 **1.5 s** | 主控制 reason 4 | 14 STALL_POSITION / STALL_POS |
| 同上 | 速度模式对应失速条件持续 **2.0 s** | 仍是主控制 reason 4，是同一失速码 | 15 STALL_SPEED / STALL_SPD |
| APP / `ADC_RunZeroCalibrate`；`protected_closed_loop.inc` / Init；旧 `isolated_concurrency.inc` / IsolatedZero_Fail | 启动零点等待 **>1500 ms**；保护/隔离零点总窗口 **5000 ms** | reason 7 / `CL_BAD_ZERO` / `FOC_ZERO_TIMEOUT`，框架各异 | 16 STARTUP_ZERO / ZERO_CAL；快照记录实际 MAX_US |
| APP DMA consumer / `AsDma_Consume` | 两次消费样本时间差 **>2500 µs** | reason 2 | 17 ENCODER_INTERVAL / ENC_DT；零间隔不是 timeout |
| `protected_closed_loop.inc` / `ProtectedLoop_AdcProfileEnd` | DWT 执行周期达到 **8500 cycles**，170 MHz 下为 **50 µs** | `CL_COMPUTE_LATE` | 18 COMPUTE_DEADLINE / COMPUTE |
| `bridge_feedback_filter_core.h` / `BridgeFilter_Push`（旧断电机诊断） | elapsed 达到 **50000 µs** | 与采样故障同为 `FOC_FP_TIMEOUT=6` | 19 BRIDGE_WINDOW / BRIDGE_US |
| 同上 | 已收 **1000 对**，不是时间超限 | 也被映射成 6，是 | 20 BRIDGE_PAIR_BUDGET / BRIDGE_N；保留旧退出语义 |
| `protected_closed_loop.inc` / `ProtectedLoop_WorkEnd` | 微秒计时工作窗口 elapsed **>=50 µs** | 也为 `CL_COMPUTE_LATE` | 21 COMPUTE_WALL / WALL；与 DWT 来源区分 |
| `control_chain_reconnect.inc` / DeadlineReached；旧 feedback binding | 硬关闭算术控制诊断租期 **5000 ms** 到期 | `FOC_FB_CONTROL_LEASE_EXPIRED`→HEALTH | 22 CONTROL_LEASE / LEASE |

其中最初共享 `FOC_FP_TIMEOUT` 的语义有：首样本、已有采样流、待确认、旧 ADC 到达间隔，以及旧桥诊断的时间和数量边界，共 **6 类**。重复的 PhysicalSeen / guard 调用不算新来源。旧 `foc_overcurrent_confirm.h` 的待确认使用自己的 `FOC_OC_DEADLINE`，本轮也附加 CURRENT_CONFIRM；旧 layered wrapper 的首样本/断流附加对应分类，没有改变其优先级。

**针对上一次 fast-profile 的 protection.reason=6：首先看 CUR_FIRST / CUR_SAMPLE / CUR_CONFIRM。** 不应凭同名 TIMEOUT 认定为拧紧 8 秒或编码器 200 µs。

### 其他搜索命中：不能混作电机 TIMEOUT

| 文件 / 位置 | 条件、常量 | 原行为 / 本轮处理 |
| --- | --- | --- |
| APP TighteningTask / RUNDOWN travel 分支 | 超过 recipe 最大行程 | 虽叫 RUNDOWN_TIMEOUT，但非时间故障；subreason=NONE，保留 PROCESS outcome |
| APP 五个 torque-stage 分支 | 速度/接触后行程超限 | 状态写入 TIGHTEN_STATE_TIMEOUT，outcome 实为 ABORT；不是新增定时超时，未改变状态机 |
| APP 接触确认 | recipe `contact_ms`，默认 250 ms | 是连续成立的确认计数，不存在单独 CONTACT_WAIT timeout；未凭空创建 |
| APP 位置 settle | `POSITION_SETTLE_HOLD_MS=500`、位置/速度判据 | 正常停稳保持，不是独立超时 fault；未凭空创建 |
| APP 扭矩阶段时长 | seating、T1/T2/T3、hold 的 recipe 时长 | 正常阶段转换条件，不是失败 deadline |
| APP `BootHealthTask` | `BOOT_HEALTH_FAIL_RESET_MS=12000` | 原日志已明确启动健康超时及回退；按要求不改 IAP、复位或槽逻辑 |
| `can_control_v0.c` / Evaluate | ARM 窗口 >500 ms | `CAN_CONTROL_V0_REJECT_TIMEOUT`，拒绝命令，不映射电机保护 6 |
| `can_shadow_diag.c` / Tick | shadow 窗口 >500 ms | 只读 probe 超时计数/拒绝，不映射电机 fault |
| `can_rpc_transport.c` / Expire | idle >=500 ms / packet >=5000 ms | 回收 CAN RPC 重组状态，不改 CAN/Pigweed |
| `pw_can_rpc.c` / 服务 | response >=4000 ms | 响应状态回收，不改 Pigweed |
| `router_transfer_wire.c` | 段重组 >=2000 ms | 只回收 Router 重组槽，不改 Transfer |
| APP router | node/route 15000 ms | 发现/路由过期，不是电机失活 |
| APP ProtocolTask ESP PING | 2000 ms | 已有 ESP_PING_TIMEOUT 协议错误，不改 ESP32 |
| APP UART | 协议入队 250 ms；DMA 发送等待 1000 ms | 入队失败或 DMA 恢复，不改 UART 超时 |
| APP Modbus / Exchange | TX 30 ms；响应窗口 150 ms | `MODBUS_PROBE_TIMEOUT/UART_ERROR`，不是电机 TIMEOUT |
| `adc_dma_diag.c`、`adc_parallel_diag.c` | 原码采集窗口 1000 ms | `ADC_DMA_DIAG_TIMEOUT`，已有独立诊断结果，不是 FOC shutdown 6 |
| APP regular ADC live read | HAL poll 2 ms | 返回 HAL_TIMEOUT，更新模拟监控读数质量，不改 injected 采样 |
| `isolated_concurrency.inc` 运行结束；ClSession_Expired | 请求的诊断时长；原 400 ms 单次会话 | 正常结束/STOP，不应捕获成 TIMEOUT 故障 |
| `tighten_synthetic_bench.cpp` | 模拟 rundown、stop、torque、simulation deadline | 离线模拟结果枚举，未改、不会作为实物故障快照 |
| ST HAL / FreeRTOS / 第三方库 | 各驱动等待、内核超时和传输重试 | 不改 vendor/kernel，不把每个 API 参数当成一类电机 fault |

完整自有源码搜索记录由 `tools/verify_foc_timeout_diagnostics.py` 生成到 `tests/foc_adaptive_build/timeout_diagnostics_evidence/owned-source-audit.log`，涵盖上述关键字及 C/C++/头文件/绑定。没有搜索私钥目录或展开私有 Flash。

`FOC_TO_UNKNOWN` 是枚举/打印器的防御值；本轮接入的 TIMEOUT 分支没有主动传 UNKNOWN。`NONE` 表示该次故障不是已识别的时间条件，不能解释为“没有故障”。老 `foc2` 单镜像工程保留为编译兼容检查，不替换板上 APP A/B，也没有把它改成新的部署入口。

## 2. 快照如何保存，在哪里看

定义：`firmware_common/foc_timeout_diag.h` 中 `FocFaultSnapshot`，**204 字节**。

实例和捕获：`firmware_common/foc_fault_snapshot.inc` 中 `foc_fault_snapshot`、`FaultDiag_CapturePacked()`。调用侧保留五参数的 `FaultDiag_Capture(domain, reason, subreason, elapsed_ms, limit_ms)` 宏，仅把 domain/reason 打包到 ARM 参数寄存器，降低 Flash 开销；没有改变原 fault enum。

捕获过程是短 PRIMASK 临界区：检查 valid → 固定大小字段复制 → `__DMB()` → 最后置 valid。后续保护、清理或 Monitor 不覆盖；`FaultDiag_Clear()` 只接入原有启动清故障的位置，没有新增在线清故障命令。复位会丢失 RAM 快照，务必先保存日志。

原输出关断仍保留，保护 EmergencyOff 先关闭 SD/MOE/CCER，再保存快照，再执行原清理。传感器非 DMA 错误、失速及过程退出处补上关断后、清参考前的捕获，避免只保存清零后的 IqRef。新增故障路径无 printf、UART、堆分配、RTOS 锁、等待或按输入长度增长的循环。固定大小复制不是新增波形缓冲；**本轮未实测捕获耗时/栈峰值**。

快照保存实际状态：模式、拧紧阶段和阶段时间、位置/目标/误差、瞬时/滤波/指令速度、IqRef/Iq/Id、stall 累计秒数、contact 连续成立毫秒数、encoder 有效与错误计数、fast 判别状态及 6 个计数、4 类最大周期与 deadline miss、ADC/FOC 次数、hold、保护 flags、超时证据。

没有可读的独立驱动 fault 引脚就明确打印 **DRV_FAULT=NA**，不是假造 0 或“硬件保护已验证”。编码器 DMA 的原 first_fault 寄存器快照仍保留；本轮只增加只读状态导出，在原回调前发布其原因，不改事务/方向/调度策略。

### 日志字段与单位

`FaultDiag_Monitor()` 在 MonitorTask 每次唤醒时服务一次，仅把首次快照加入原可靠 UART 队列。启动失败且没有创建 MonitorTask 的通信循环也服务同一打印器。入队失败则停在当前行，下次继续；`END CPU_HZ=...` 入队成功后不再重刷。这里的“可靠”是本机入队成功，不是主机收到 ACK。

为适应 224 KiB 槽，字段用紧凑名字；下面是阅读字典：

| 日志 | 含义 / 单位 |
| --- | --- |
| TIMEOUT_SUBREASON、TO | 上表名字及枚举数字 |
| DOM、FAULT_REASON、FLAGS | 原 fault 域、原 reason、原保护位；DOM=1 MOTOR、2 PROTECTION、3 PROCESS、4 STARTUP |
| STATE、STATE_MS、MODE | 原拧紧阶段数字、阶段毫秒、原模式数字；故障前状态，不是清理后的 IDLE |
| POS、PTGT、PERR | 毫度，即显示值 /1000 得 deg |
| SPD_RAW、SPD_FILT、SPD_CMD | 毫 rpm，即 /1000 得 rpm |
| IqRef、Iq、Id | mA，即 /1000 得 A；RAM 仍是原 float |
| STALL、CONTACT | 失速累计毫秒、接触条件连续成立毫秒；CONTACT 不是绝对时间戳 |
| ENC、ENC_ERR | encoder_valid 与累计错误数；原 DMA first_fault 另行保留 |
| CUR_STATE | fast TRACKING/SUSPECT 的原枚举值；CUR_OK=1 表示本构建提供 fast 计数，不是“电流安全 PASS” |
| SUS、SPIKE、TRANS、UNRES、RUN、MAXRUN | suspect、确认尖峰、确认阶跃、unresolved 总数、连续数、连续最大数 |
| MAX_CYC、N_CYC、S_CYC、U_CYC、D_MISS | 总/正常/可疑/未决最大 CPU cycles；deadline miss 次数 |
| ADC_N、FOC_N | 原物理采样/FOC 执行计数 |
| hold_total、hold_n、hold_max、hold_ppt、hold_ms | 累计 hold、最近完成窗口数、最大窗口数、千分率、最近窗口实际毫秒 |
| TO_ID、NOW_US、REF_US、DT_US、MAX_US | 捕获的触发来源、now、参考时间、差值及限值，单位 µs |
| LAST_US、PEND_US、PEND、MISS | 最后物理样本时间、候选起点、是否 pending、候选确认 misses |

例如 `TIMEOUT_SUBREASON=CUR_CONFIRM / DT_US=101 / MAX_US=100 / PEND=1`，就能说明是候选确认等了 101 µs，而不是 8 秒拧紧超时。`SPD_FILT=4800 / IqRef=400` 表示 4.8 rpm / 0.40 A。此处是格式说明，不是本次板端采集结果。

CPU 时间换算：`cycles / (CPU_HZ / 1000000)`；170 MHz 下 cycles/170 = µs。不在 ISR 格式化浮点；非有限或无法安全转换的 float 打印 INVALID。

证据边界：电流 sample/confirm、ADC gap、outer、WALL 保存完整微秒触发时间；过程/启动保存 elapsed 与 limit（从 ms 换算）。DWT 使用周期计数和 8500-cycle 限值，不伪造微秒定时器起点；encoder 事务详细时序仍在原 DMA first_fault 中，global snapshot 提供分类和 encoder 状态。对应未采集字段为 0，不能把它读成实际等了 0 µs。BRIDGE_N 是数量边界，其 MAX_US 仍是旧桥测试的时间上限，1000 对的界限见上表，不把它误读成 1000 µs。

## 3. hold 统计没有改变控制

物理样本经过 fast 判别后，若未 TRIPPED 且路径为 SUSPECT 或 UNRESOLVED，ISR 只增加 `current_hold_total`。已触发终止的最后一帧不冒充“继续运行的一拍 hold”。

任务侧按名义 **1 秒**统计差分：`hold_rate_per_mille = holds_delta * 1000 / physical_samples_delta`，不是 FOC 执行次数作分母。计数回绕和没有样本的窗口已测试。保存 actual window_ms；任务迟到时不假称精确 1 秒，`hold_max` 也应结合 `current_hold_window.max_window_ms`（调试器可读）理解。千分率取整，小于 1‰ 会显示 0，原 hold_n/total 仍保留。

窗口临时计算在任务中完成，再在短临界区一次提交，避免故障 ISR 读到半写窗口。fault snapshot 中是最后完成的窗口，故障可能发生在新窗口尚未满 1 秒时，应一起看 hold_total。本轮为了 Flash 余量不新增正常运行周期刷屏；活窗口可调试器读取，故障时完整打印一次。

Two-sample 判别器文件未改，SHA256：
`a77bf47b2fb3082bf331b0c54782488e253b644cb0f289f4c94b47150288275d`。
没有修改 jump/return/confirm/unresolved、one-cycle hold、PI、SVPWM、ADC 触发、PWM 频率、电角零点、方向、recipe、CAN FD/Pigweed/ESP32/IAP/bootloader。低优先级诊断格式化使用尺寸优化；没有把实时 FOC 改为 fast-math 或删保护。

## 4. 编译、测试和资源

执行了主工程及以下四个 APP 目标的 clean build，随后在最终源码上增量重编译；均成功。可复现命令：

```powershell
python tools/verify_foc_timeout_diagnostics.py
```

最终构建收据和原始日志：`tests/foc_adaptive_build/timeout_diagnostics_evidence/receipt.json`。所有数据是离线构建，不是实机验收。

| 目标 | Flash B | RAM B | 相对本轮前 Flash / RAM 增量 B | 剩余 Flash B |
| --- | ---: | ---: | ---: | ---: |
| foc2 Debug（保留旧主工程） | 110912 | 37744 | 未修改源逻辑 | 非 A/B 槽 |
| APP A FastCurrentReject | 229356 | 126328 | +2472 / +600 | **20** |
| APP B FastCurrentReject | 228212 | 126312 | +2360 / +600 | 1164 |
| APP A FastCurrentRejectComputeOnly | 227476 | 126168 | +2408 / +608 | 1900 |
| APP B FastCurrentRejectComputeOnly | 226444 | 126152 | +2424 / +608 | 2932 |

基线来自 `docs/foc-current-impulse-discriminator-20261016.md` 的四目标表。总 RAM 增量不仅是 204-byte 快照，还包括 timeout latch、hold 窗口、冷路径/实时入口布局及 RAM 函数代码；不是运行时栈峰值。A/B RAM 上限 131008 B，Flash 上限 229376 B，未扩槽。

**A 正常版只有 20 B Flash 余量**：确实链接成功，但没有继续叠加功能的空间；下一轮定位使用已有的 ComputeOnly 计算版。本轮没有通过扩大分区、删除保护、删控制功能来塞镜像。

新增诊断无新增编译 warning。不是“整个项目无 warning”：APP 四构建保留 12 项既有 main.c unused 警告，clean link 仍有既有 RWX LOAD segment 警告；旧主工程有 10 项既有 unused/set-but-unused 警告。本轮没有统一关闭 warning 或为清警告删除旧接口。新 host 代码使用 `-Wall -Wextra -Werror -pedantic`。

通过 **38 项 unittest**：新诊断 5、fast 判别/实际绑定 8、旧分层保护 8、旧反馈保护 10、自检 3、实际保护控制绑定 4；后者包含 30/31 个 host 场景。新测试使用真实 `.inc`，在 -Os/-O2 下覆盖：

- 100 µs 边界及 uint32 回绕；sample 与 pending 同时过期的原优先级；首个原因粘住。
- 编码器 transaction/age/control/schedule/interval 分类，parity/IO/零间隔不假报时间超时。
- 原保护关输出、保留故障前 IqRef、后续故障不覆盖。
- ADC guard、outer、WALL、DWT 的实际绑定来源和 flags。
- UART 队列满的逐行恢复和打印一次；快照 schema 大小/字段数量一致。
- hold 真正由物理样本路径计数，任务窗口延迟/回绕/分母为零。
- 两槽旧硬关闭 feedback binding 的语法兼容（含/不含 control lease）。

不是全仓所有历史工具的全量回归，也没有运行任何刷板 runner。未推送 GitHub、未提交，保留工作区原有其他改动。

## 5. 下一次人工上板只做什么

1. 使用与当前槽匹配的 **FastCurrentRejectComputeOnly** BIN、ELF 和本收据；不要把正常候选当成这次计算诊断。保留原回退镜像与参数；本轮没有自动刷入任何版本。
2. 继续采用功率硬关闭、U/V/W 断开的原计算测试接线/流程。由人工按原 A/B 升级流程部署，不改 recipe/保护/超时；开启串口原始日志保存。不要直接运行旧的硬编码 RAM 偏移/旧 SHA 的自动脚本。
3. 启动原有功率关闭计算测试，等待 fault 或原 30 秒观察结束。本次不需要发送电机 START，不做扭矩/转速验收。
4. 若 fault，**复位前**保留从 `FAULT SNAPSHOT TIMEOUT_SUBREASON=...` 到 `END CPU_HZ=...` 的完整日志。若 UART 暂时背压，等任务续传；若任务无法继续，按新 ELF 符号只读 `foc_fault_snapshot`，不要用旧结构偏移。
5. 依次读 DOM/FAULT_REASON/FLAGS → TIMEOUT_SUBREASON → DT_US/MAX_US/LAST_US/PEND_US/PEND/MISS → STATE/STATE_MS → SPD_CMD/SPD_FILT/IqRef/Iq → CUR_STATE 及各 counters → hold/CPU cycles/D_MISS。ENC 类再读原 encoder DMA first_fault。
6. 独立保护链若被**人为停止采样**以验证关断，出现 ADC_GUARD/CUR_SAMPLE 是预期注入故障，不算随机失稳；自然运行故障必须与注入分开记录。
7. 30 秒未故障也保存 CURRENT VALIDATION 和时间统计；这只证明本次计算工况，不自动等于带电闭环通过。确定具体 timeout 子条件之后，再另议根因修复，不先加长 deadline。

## 6. 最终 15 问逐项回答

1. 来源数：按本轮电机停机语义 21 类时间来源，另 1 类数量上限；通信/回退/仿真另表，不混算成一个全仓数字。
2. 原来共享：电流首样本/断流/待确认、旧 ADC 间隔、旧桥时间/数量共 6 类共享 FOC_FP_TIMEOUT；另有失速两模式共享 reason 4、两种计算计时共享 COMPUTE_LATE。
3. 新枚举：上表 ID 1～22；另有 NONE、UNKNOWN 防御值。
4. 结构文件：`firmware_common/foc_timeout_diag.h`；实例在 `foc_fault_snapshot.inc`。
5. 捕获函数：`FaultDiag_CapturePacked()`，调用宏 `FaultDiag_Capture(...)`。
6. 首次捕获：是，valid 最后发布，后续不覆盖；原启动 clear/reset 才重新开始。
7. 实时路径日志：新增 fault 路径没有 printf/UART/heap/等待；详细打印不在 ISR。
8. Monitor：任务侧逐字段入队、背压续传、完整输出一次，不无限重刷。
9. 判别器：算法与 thresholds 完全未改，哈希冻结并有测试。
10. 超时常量：原值及 > / >= 边界保持，不放宽来通过验收。
11. hold：新增 total、最近/最大窗口及千分率，ISR 只增计数，窗口在任务中计算。
12. 编译：旧主工程 + A/B 正常/计算四目标均通过。
13. warning：无新增诊断 warning；既有 warning 未隐藏，明细见日志与上节。
14. RAM：快照 204 B；正常版总 RAM +600 B，计算版 +608 B。
15. 上板：按第 5 节人工部署匹配的功率关闭计算镜像，先保留完整首次 fault 日志，再分析具体来源；不自动启动电机。

TIMEOUT 子原因与 fault snapshot 已实现，代码已编译验证，等待人工上板测试
