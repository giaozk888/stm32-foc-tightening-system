# PWM 更新余量：低扰动诊断候选

上次逐源归因诊断版在 52 µs 触发原有 50 µs 计算停机保护，且它自身增加了中断负担。不能用它的耗时断言原控制版超时。本候选只减少**测量开销**；2026-10-16 已完成一次功率输出关闭的上板试运行和回退，未运行电机。结果见下文。

## 改动

- 新增独立 A/B 预设 `RcBoundaryLite`，继承 `RcSamplingOptimizedCandidate`。原 B570 镜像、滤波、零点、FOC、保护和原拧紧状态机不改。
- 沿用 ADC 中断原有的 DWT 起止读数与 TIM1 入口计数，不在 TIM7、TIM2、编码器 DMA 入口/出口增设源统计。轻量路径只保存一个入口稳定标记；仅当原有 `cycles >= remaining` 告警发生，才调用 RAM 中的记录函数，冻结首次与最差帧。
- 串口只读命令 `ADC BOUNDARY LITE`、`ADC BOUNDARY LITE FIRST`、`ADC BOUNDARY LITE WORST` 在任务上下文复制小快照并格式化，不在 ISR 中打印。结果是软件粗估，不含完整 ISR 尾声、CCR 活动影子值或模拟电流稳定性证明；因此始终标注 `HW_VERIFIED=0`。
- 诊断版 `FocAdcTiming_RcActuationReady()` 固定返回 0，`FocAdcTiming_CommitBeforeBottom()` 固定拒绝控制占空比发布。`MOTOR TEST PROFILE` 标为 `RC_BOUNDARY_LITE ADMISSION=0 QUALIFIED=0`。保留原有 50 µs 超时停机、反馈与零点故障关断，不改优先级或阈值。

与原优化候选相比，目标 ARM 编译结果中 `FocAdcTiming_IrqEnter` 从 112 增至 124 字节，`FocAdcTiming_IrqExit` 从 68 增至 80 字节，合计多 24 字节；较重的记录函数单独位于 RAM，只在告警帧调用。上一版逐源诊断的这两个函数分别为 180 和 456 字节，且四类 IRQ 都有额外钩子。**机器码大小不是运行时间**，只能说明路径明显收窄，不能代替上板测量。

## 离线验收

- A/B 均编译通过：A BIN 212196 字节、RAM 126000/131008；B BIN 211324 字节、RAM 125984/131008。仍有既存的 RWX LOAD 警告。
- SHA-256：A `2c5fecc39d6649a08da49cffba26d63fd77614a590b26eb5d8f5451abc3be8fc`；B `7ed9daad5474f413257c140164b05cf0ef3c78ded564e83a422d4852a2a70dc8`。
- 59 项相关回归通过，包括真实 timing adapter 的 `-Os/-O2` 寄存器模拟、DWT 回绕、首次/最差帧冻结、异常入口排除、无电机准入/无控制占空比发布、原已测镜像哈希未变，以及链接镜像中四类源 IRQ 无逐源钩子、记录函数确实位于 RAM。

## 2026-10-16 上板实测

驱动板刷写时 12 V 关闭；电机 U/V/W 动力线断开。非活动 A 槽写入 212196 字节镜像并完整回读；已确认 B573 和槽外私有数据不变。随后在 12 V、限流 0.5 A、无报警条件下，只试运行 A 一次，不发 START，不关闭保护。试运行在启动健康确认前因**反馈修补预算耗尽**触发停机（`MOTOR TEST PROTECTION REASON=9`，`FLAGS=0`），不是 50 µs 计算超时：`MOTOR TEST TIMING MAX_US=44 LATE=0`，零点校准 `STATE=3 REASON=0`，编码器 `FAIL=0 TIMEOUT=0`。没有正常确认 A，不算通过。

在约 104387 对 ADC 样本时，粗略底点余量告警 `LATE=3498`，约 3.35%。首次被记录帧 `SEQ=27591 REM=2898 WALL=4927 OVER=2029`；最差帧 `SEQ=54017 REM=3219 WALL=6710 OVER=3491`。这里 `REM/WALL/OVER` 是计时器／DWT 计数比较的**软件粗估**，并不包含完整硬件边沿和所有 ISR 尾声，`HW_VERIFIED=0`。重要区别是：计算在 50 µs 周期内完成，不代表结果总能赶上当前 PWM 底点；部分帧在 ADC ISR 进入时剩余时间已经小于实际执行时间。该诊断版 `ADC COMMIT READY=0`，未向电机发布控制占空比。它与先前 B570 约 3%～4% 的粗余量告警同量级，未显示明确改善；两次运行时长和输入噪声不同，不能用这一对比证明相位根因。

单次试运行后 `ANALOG SAFE` 锁定，并在用户关闭驱动板 12 V 后经 bootloader 恢复已确认的 B 槽选择。最终元数据 `confirmed=B, pending=none, attempts=0, generation=576`，CPU 停在 B 入口，SD/PWM 关闭；完整回读证明应用区和私有配置除正常启动元数据外未变。A 槽仍保留未确认的轻量诊断镜像，不自动试运行。公开收据：

- [写入与回读](safety_backups/protected-closed-loop-20261014/rc-boundary-lite-stage-1792130533504430100.json)
- [单次试运行和故障快照](safety_backups/protected-closed-loop-20261014/rc-boundary-lite-trial-1792130588821995900.json)
- [恢复 B 与输出锁定](safety_backups/protected-closed-loop-20261014/rc-boundary-lite-restore-1792130700845604500.json)

因此下一步应分别处理两个问题：一是诊断与原 B 均出现的底点余量告警，需要在不引入源跟踪开销的条件下核实采样触发相位／中断抢占和 PWM 实际装载时刻；二是反馈修补预算偶发耗尽，应保留故障快照并检查输入噪声与滤波修补密度。不能把本次 `MAX_US=44` 当成闭环电机、物理 PWM 装载或稳定性验收，也不应为通过测试而直接放宽保护。

后续一拍延迟计划影子候选的改动与单次实测结果见 [FOC_RC_DEFERRED_SHADOW_20261016.md](FOC_RC_DEFERRED_SHADOW_20261016.md)；候选因计算达到 50 µs 停机，原已确认 B 已恢复。
