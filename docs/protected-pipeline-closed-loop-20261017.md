# 最新优化接入保留保护的闭环候选版

## 范围

新增 A/B 共用 preset `ProtectedPipelineClosedLoop`，继承 `FastCurrentReject`，显式启用 `FOC_PWM_PIPELINE_CLOSED_LOOP`、一拍 PWM pipeline 和 FOC-first 编码器后端。默认关闭 heavy profiling，保留 wall max、50 µs deadline miss、实际 CCR late 和最小 margin。

这是可经原本地 START 准入的候选配置，不是旧硬关闭镜像的强行解锁，也不是已经通过带电闭环验收的成品。本轮只构建和离线测试，未刷写、未复位、未访问板卡、未改变 A/B 启动选择、未发送 START。

## 已接入的调度

- ADC/FOC IRQ 仍为 priority 2。
- 编码器 TIM2、RX/TX DMA 仍为 priority 3；TIM6_DAC deferred service 为 4；不把角度计算重新放回事件顶半部。
- TIM7 软件健康保护仍为 priority 3；原中断优先级和 FreeRTOS ceiling 检查保留。
- ADC IRQ 入口提交上一拍已接受的 pending，当前拍尾部只生成 pending；固定增加一个 ADC 周期，即 20 kHz 下 50 µs。未更改现有角度预测、PI、Clarke/Park 或 SVPWM 数学。
- 异常采样继续冻结电流 PI；不制造替代电流，保持上一有效 PWM。CUR_CONFIRM 连续 2 个正常 sample 清除、最多 4 cycles 的逻辑与阈值不变。

## 启动与输出所有权

1. 启动／校准沿用现有硬关闭流程和 neutral 初始化。
2. READY 中仍运行真实反馈计算，但 **只允许 neutral CCR 进入硬件**；影子 FOC 结果不进入 pending。记录至少 1000 次安全 neutral 入口提交，确保 START 前跨过多个真实 preload 更新事件。
3. 原 `LatestOriginal_Admit()` 保留配方、零点、静止、ADC/编码器新鲜度、UART、启动确认、定时器、会话和保护准入。仅这个既有入口可执行原有功率使能事务。
4. START 时清 pending、清电流 PI 记忆，不再在任务中重写 CCR 或改变 UDIS；READY 已持续写入并锁存的 neutral 是初始输出。第一拍计算，下一拍才提交。
5. STOP、fault、shutdown、模式切换继续作废 pending。一次会话／20 rpm／400 ms 限时范围保留；不自动重试、不自动 START。

## 实际提交保护

`FocAdcTiming_PipelineCommit()` 不会使能 SD/MOE/CCER。旧诊断配置仍仅接受全关输出；新候选需要绑定层给出 READY/OFF 或已准入 RUNNING/ON 的权限，且实际门控寄存器必须完全匹配。

提交前重新检查：会话与保护状态、原有健康条件、ADC age/sequence、反馈独立超时、运行 lease。失效先关断；不能因 CCR 写入把硬件关断后的 MOE/SD 恢复。三个 CCR store 后再次检查门控和计数器。

CCR preload、ARR、RCR、时钟、DIR 和 DWT 几何校验保留。要求在本次下降计数到目标 bottom 前留出原有 170 timer ticks 提交 reserve；不以模运算得到的未来 bottom 掩盖当前 late。任何真实 late／无效提交均失败关断，不清历史计数。提交仅写 CCR1/2/3，不写 UDIS、UG、SR 或 CCR4。

新 pending 仍由现有采样窗口规划器生成，保留 RC recovery、dead time 和采样孔径约束。如果规划需要不同 CCR4，直接拒绝该计划并走原故障路径，绝不暗中移动 ADC trigger。

## admission 的时序语义

新候选使用 `PipelineActuationReady()` 检查实际入口提交：paired ADC 数量、有效 DWT、clock/geometry、plan/pair/commit 错误、真实 min margin、真实 late/blocked/post-unsafe，以及 FOC wall deadline 历史；绑定层另检查 neutral 提交数和原有 `cl_late`／current-cycle deadline。

旧 `stats.deadline_misses` 是“FOC 尾部耗时与入口到 bottom 的比较”，不是新的入口提交 deadline。该粗粒度／hypothetical 计数仍保留，并未关闭告警或清零；新候选的 `RcActuationReady()` 转接到真实入口提交证据。旧配置沿用旧准入逻辑。

因此，“尾部假设来不及”不能再等同于“入口真实提交过晚”；真正 wall 超过 50 µs、真实提交过晚或没有安全 margin 仍拒绝启动。所有实际／假设证据继续分离。

## 未改动

电流判别器及 reference rebase、CUR_CONFIRM、相电流阈值、硬件／软件保护通路、encoder stale 阈值、PWM/ADC 频率、PI 参数、SVPWM、速度／位置／拧紧状态机、CAN/Pigweed/IAP 和 A/B 元数据逻辑均未重写。接线和硬件保护的实物有效性不能由本轮离线测试证明。

## 可复现构建与回归

在工程根目录执行：

```powershell
python tools/pipeline_closed_loop_offline.py
```

工作流输出到 `tests/foc_adaptive_build/pipeline_closed_loop_evidence/receipt.json`，所有构建使用新的 `build/ClosedLoopIntegration/<profile>` 路径，不覆盖历史镜像。重建历史 17 个配置和新增 A/B 候选，并与旧 `encoder_health_evidence/receipt.json` 的 BIN 哈希比较，不更新历史镜像 pin。

新增 host 回归直接执行真实 binding、原 START admission 和真实 CCR adapter 的寄存器 mock；覆盖 neutral、下一拍提交、invalid hold/PI freeze、STOP/fault、模式切换、断开 MOE 后不恢复输出、超速、外环/ADC stale、lease 到期、更新中拒绝、采样窗口不匹配、启动期间异步 STOP/fault、未满 neutral 证据及 deadline miss 拒绝。

CUR_CONFIRM、电流判别、保护层、编码器协议／publication、pipeline 与 health-wait 等现有回归同时执行。编译／测试结果以最终 receipt 为准；host 运行时间不是板上 50 µs 证明。

最终验证矩阵为 19 个构建配置、168 项 unittest；新增 integration 模块还在 `-Os`/`-O2`、heavy=0/1 下执行 120 个 binding/commit 场景。16 个旧 BIN 与旧收据逐字节哈希一致。新增候选按源文件与既有 light 诊断配置比较警告集合，不隐藏原有 unused/RWX 警告。

| 候选镜像 | BIN 字节 | 链接 RAM 占用 | SHA256 |
| --- | ---: | ---: | --- |
| A | 228940 | 127944 | `b4d2368220699e6cf792b0a7032c52e3c74cb112351133363f97bcc4706cdd3e` |
| B | 227924 | 127928 | `4dad58d581755072d15a36da0492a809df2735dc654203f7b3e8a98b77b27ec8` |

A 槽仅剩 436 字节 Flash，B 槽剩 1452 字节；未超槽，但后续扩展必须先处理容量。链接 RAM 占用不是任务栈高水位／运行时余量验收。

## 下一步边界

候选必须用其自身 ELF/BIN 与新验收工具匹配，不可套用旧硬关闭镜像的地址／哈希／功率权限。新增提交准入检查会消耗 CPU 和 bottom 余量，必须先实测本镜像功率关闭的 wall、实际 commit margin 和停止采样关断，再决定是否进入人工确认的限时闭环测试。上轮诊断版的 31.25 µs／15.05 µs 数据不能移作本候选的实测值。

本轮停在软件候选交付，不自动刷板或启动电机。
