# Deadline attribution 与编码器 IRQ 审查

## 本轮边界与结论

本轮只改诊断一致性和诊断编译开关。没有刷板、访问串口/调试器、启动电机或改变 B 槽启动选择；不把离线测试称作新的 50 µs 实测通过。

旧 52.359 µs 超时帧无法从现有无效记录追溯为精确分解。本轮为下一次人工板测准备可靠的首帧快照，未先降编码器优先级，也未重构编码器传输状态机。之前有效帧证明 TIM2/RX 确实抢占 ADC，但不足以证明那次超时的完整因果链。

## 1. 旧快照为什么无效

旧 `Stamp()` 先读取累计 IRQ 次数，再读取 DWT、cycles/count 多字段，最后检查次数是否改变。若某个高优先级 IRQ 恰好发生在读取期间，快照就被判为无效。`FocPreempt_End()` 仍把首次 miss 锁存下来，因此可能永久保留一帧无效的首个超时，而不是得到可用证据。不能把这种情况简单改成强行 `valid=1`。

## 2. 当前一致性方案

对当前 `OneCyclePwmPipeline` 配置采用 IRQ-assisted checkpoint：

1. ADC 请求一个读边界，直接读取 DWT、TIM1 CNT/DIR、编码器累计 cycles/count。
2. 若编码器 IRQ 打断这次多字段读取，它在更新任何累计账本前提供一份一致的替代边界。
3. 后续同级 IRQ 不覆盖该替代边界。ADC 恢复后使用它，而不是混合新旧字段。

没有关中断、设置 BASEPRI、重试循环或丢弃该帧。TIM2/RX/TX 均为优先级 1，互不嵌套；低于 ADC 的 TIM7 不计入抢占。依赖这些前提的 NVIC inventory 检查保留：未知高优先级 IRQ、优先级关系变化或账本恒等式失败时仍拒绝标有效，绝不伪造可靠性。

帮助边界可能落在读取过程中的 IRQ 入口，而非读取函数最初一条指令。返回给既有 deadline 保护和记录器的是同一个边界，因此二者不会各用一个独立最大值。边界/异常入退栈、hook 前后和测量本身的成本仍可能保留在 active estimate 中；它不是纯控制数学 WCET，也不是精确分离的硬件异常开销。

旧非 pipeline 的嵌套 TIM7=0 实验保留原归因读法，本轮不悄悄迁移其计时模型。

每帧：

`wall = exit_dwt - entry_dwt`

`preempt = TIM2_delta + RX_delta + TX_delta`（pipeline 中 TIM7=0）

`active_est = wall - preempt`

cycles/count、DWT 回绕使用无符号减法。IRQ inclusive max 仅用于单次展示，不把不同 IRQ/不同周期的最大值相加。

## 3. 首个 deadline snapshot

新增独立 `deadline_snapshot`，不改变旧 `FocPreTiming` 的 140 字节离线解码布局。包含 wall/active、TIM2 与 RX 的 cycles/count、other IRQ、preempt total、TIM1 CNT/DIR、entry/exit DWT 和 timer observation span。

`SaveDeadline()` 逐字段写完，设置 captured，再以 DMB + `valid` 最后发布。之后不覆盖，直到 reset 或人工在停止采样时清空该结构。无效 inventory 也会留下 `captured=1, valid=0` 的证据，防止之后的有效帧覆盖真正的首个故障。

`FocPreempt_End()` 使用既有 8500 cycles 边界，不修改 deadline 阈值；保留 observer-tail max，避免把快照收尾成本隐藏为“没有开销”。第一帧保存的成本可能影响后续调度，板测仍需观察。

任务侧继续打印 first-miss 的 wall/preempt/active 和 IRQ breakdown，额外打印 CNT/DIR/DWT/span。ISR 内无 printf、UART、格式化或分配。

`FocPreempt_CheckPriorities()` 现在在完成读取后发布结果，不再临时把已核验的 OK 清零，避免 MonitorTask 检查进行中被 ADC 打断而制造虚假的提交拒绝。没有设置任何 NVIC priority。

## 4. 编码器审查

| 实际中断 | 当前优先级 | 能否抢占 ADC=2 | 实际职责 |
| --- | ---: | --- | --- |
| TIM2 | 1 | 能 | SPI setup/hold/gap/BSY guard、采集周期、事务 deadline、控制 watchdog |
| DMA1 Channel4 RX | 1 | 能 | DMA 标志/错误检查、接收完成、时间戳与下一 guard |
| DMA1 Channel5 TX | 1 | 能 | DMA 发送错误处理，正常发送不启用 TC 中断 |
| ADC1_2 | 2 | — | 原 20 kHz current loop 和一拍 PWM pipeline |
| TIM7 | 3 | 不能 | 原软件 health guard |
| SysTick / PendSV | 15 | 不能 | RTOS |

没有另加不存在的 SPI completion IRQ。TIM2/DMA 的正常获取路径不运行 float、角度换算、unwrap、速度或滤波；这些已在原 `FOC_EncoderSpeedUpdate()` 的低频任务路径。奇偶校验是四次移位异或，不是浮点重计算；它参与错误响应/ERRFL 读取，不能为“瘦身”擅自推迟到任务中并改变传输协议。

相关 IRQ 与故障 hook 未调用 FreeRTOS FromISR API，无 UART/HAL busy wait。FreeRTOS 的 syscall ceiling 为 5（编码后 0x50），优先级 0–4 不允许调用其 API；现有 1/2/3 均遵守。

本轮没有降级编码器 IRQ。理由不仅是超时因果尚待新快照确认：TIM2 的 CC1/CC4 还承担 deadline/watchdog 与原故障关闭路径，并不满足“已证实只是非安全数据处理”前提。将整个 ISR 推到 ADC 下方，可能让事务、CS 时序与关断延后，需另行拆分与验收，不能在本轮当作已完成。

TIM1 BREAK/BREAK2 在当前主程序仍为 DISABLE，未新增或臆造最高优先级硬件安全 ISR；独立驱动板关断的硬件响应也未在本轮验收。

## 5. Heavy profiling 开关

两槽 CMake 提供 `FOC_HEAVY_PROFILE_ENABLE`：诊断默认 ON（宏值 1）；后续正式耗时验收可用 OFF（宏值 0）。仍是原功率硬关闭 profile，不因为关诊断而允许功率输出。

关闭后：

- IRQ hooks 和重复的 inner pair/math/CPU 诊断不执行。
- 不生成 detailed attribution、hypothetical PWM 或 pending generation/commit max。
- 保留 FOC wall max/deadline miss 和实际 CCR late/min margin；保留原保护/功能性 health 计时，不撤销 deadline、ADC stale、watchdog 等保护。
- CCR admission、安全检查、三寄存器写入顺序及位置不变，仅将写后详细诊断 reducer 换成最小实际 margin/late 统计。

`ProtectedLoop_PwmEntry` 仍在 ADC 读数前，FOC 尾部仍只 stage pending，一拍延迟仍是 50 µs；无效样本的 PI freeze、保持 pending、启动/mode/fault epoch 处理均不变。pipeline binding 仅新增原诊断计时的条件编译，不修改调度逻辑。

未修改 current discriminator、CUR_CONFIRM、PI、SVPWM、PWM/ADC 频率、阈值、speed/position/tightening 或 CAN/Pigweed/IAP。

## 6. 构建、回归与证据

运行 `python tools/deadline_attribution_offline.py`。历史已上板镜像和其 hash 绑定的脚本保持原样；本轮产物位于 `build/AttributionReview`，不会覆盖历史 pinned ELF/BIN。

当前相关构建矩阵为 root Debug，A/B 的 FastCurrentReject、FastCurrentRejectComputeOnly、FastPathTiming、PreemptCommitProbe、OneCyclePwmPipeline，以及 A/B 的 OneCyclePwmPipelineLight，共 13 项。本矩阵不等同于重建仓库所有历史硬件实验 preset。

新增回归覆盖：辅助 checkpoint 的逐读取位置 IRQ 插入、entry/exit 两侧边界、DWT/累计账本回绕、首帧冻结与发布顺序、未知 IRQ 不能伪造有效性、轻量开关、15 种实际 CCR guard/异常/关闭状态对照、离线解码恒等式校验。所有回归不访问硬件。

新离线解码器 `tools/deadline_attribution_report.py` 要求同镜像 ELF/BIN/Flash/VTOR，并验证首帧 accounting identity；不可用不同固件 ELF 解码旧 SRAM。

最终编译/测试数量、镜像大小和警告见 `tests/foc_adaptive_build/deadline_attribution_evidence/receipt.json`。已有 unused-function/variable 和 RWX 链接告警不隐藏，新增源及轻量模式另做差分检查。

本次最终运行结果：13 项相关配置全部编译成功，20 个测试模块共 117 项测试全部通过。新增源语法检查无告警，修改过的主程序/IRQ/ADC/编码器编译单元在 heavy/light 两种配置下均未增加相对基线的告警。

A 槽 heavy 镜像 229348 字节，距离原 229376 字节槽上限仅余 28 字节；B 槽 heavy 为 228340 字节。A/B light 镜像分别为 226324 / 225308 字节。没有扩展槽边界或覆盖历史镜像；诊断版空间已很紧，不代表可以继续无预算地增加插桩。

这些结果只证明构建、模拟中断交错和回归成立，不构成新实机耗时、52 µs 根因或实际 margin 的测量结果。新首帧快照仍等待人工上板取得。

deadline attribution + encoder IRQ review 已完成，等待人工上板验证
