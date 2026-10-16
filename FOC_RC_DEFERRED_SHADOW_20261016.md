# PWM 底点余量：下一周期计划的离线候选

状态：**2026-10-16 已完成一次功率关闭的上板试运行；因计算耗时达到 50 µs 停机，未通过。** 未运行电机、未发布控制占空比，随后已恢复原已确认 B 槽选择并停在入口。实测结果见末节。

## 为什么试一拍延迟

10 月 16 日低扰动诊断的 104387 对 ADC 样本中，约 3498 次出现软件估算的当前 PWM 底点余量告警。首次告警帧在进入中断时约剩 17.05 µs，而本帧执行约 28.98 µs；最差记录帧约剩 18.94 µs，执行约 39.47 µs。计算时间仍低于 50 µs，但结果赶不上**本次**底点。下一底点从几何上多一个约 49.99 µs 周期，这提示“计算第 n 帧、在下一更新边界采用”值得验证。这个推断并未计入完整 ISR 尾声、CCR 预装载时机、其他中断抖动和模拟电流稳定时间，不能据此直接使能电机。

## 本次代码

- `RcDeferredShadow` A/B 独立预设继承 `RcBoundaryLite`，保持原零点、滤波、过流、编码器、原拧紧状态机及 50 µs 计算停机条件。没有放宽保护阈值。
- `foc_rc_deferred_plan.h` 提供单槽计划原语：第 n 对 ADC 的计划只允许在物理序号 n+1 取出；覆盖、漏样/过期、故障或不安全状态都清空，不能重用旧计划。序号回绕也在主机测试覆盖。
- 候选固件在 READY 且输出锁定时计算并暂存计划，下一对 ADC 只检查序号并**丢弃**计划。该计划不写控制 CCR；`ProtectedLoop_Ready` 和原状态机 `LatestOriginal_Admit` 在此预设下均编译为拒绝，任务路径中的桥使能交易也编译掉。`MOTOR TEST DEFERRED` 只读返回 `STAGED/TAKEN/EMPTY/STALE/UNSAFE/REJECTED/PLAN_FAIL`，`MOTOR TEST REPAIR SNAP` 在任务上下文读取故障前的修补窗口计数。
- 此影子路径本身增加了 ADC 中断工作，**不能**用其耗时直接代表未来最简正式实现。单槽计划也不能证明实际 PWM 生效时刻；未来若研究正式版本，必须先量测 CCR 预装载、底点边界、最坏中断延迟和额外约一周期的相位滞后。

## 离线结果与边界

A/B ARM 构建通过，BIN 分别为 211340 / 210476 字节。RAM 分别占 126432 / 126408 字节，共 131008 字节，静态余量仅 4576 / 4600 字节；比前一个轻量观察版多约 424 字节，正式使用前必须审查任务栈与动态余量。仍有项目既存的 RWX LOAD 链接警告。

9 项本轮专项测试、7 项原状态机测试、4 项原 RC 优化测试通过。专项测试包含两处电机准入编译拒绝、A/B 链接镜像中 `RcActuationReady` 和 `CommitBeforeBottom` 固定返回 0、延迟槽失效与回绕，以及原已测镜像 SHA 未变。候选 SHA-256：A `6cec5bac9231fbb5199a0173db535512c283f41626733b4b39a9bc61bdd74fae`；B `27d6992b6e83567acab470e4e931c55ab2ebab02f774cbb0d9c9d795c378961c`。

下一步不是直接闭环启用，而是先在功率关闭条件下对照 `MOTOR TEST DEFERRED` 与 `MOTOR TEST REPAIR SNAP`，确认序号新鲜度和修补密度，同时测实际 PWM 装载边界。只有底点时序和反馈稳定性都满足，才能考虑把延迟计划转为输出路径；否则继续保留已确认的 B 固件。

## 2026-10-16 单次上板结果

新增 `tools/rc_deferred_shadow_board_test.py`，固定候选哈希和 B576 完整备份；4 项离线脚本测试检查非活动 A 写入范围、Flash 区域保护、计划过期/超时拒绝和串口命令限制。刷写前实读证明 CPU 已停在 B、SD/MOE/CCER/CEN 关闭，与 B576 完整 Flash 一致。A 槽写入及完整回读通过，槽外字节未变。用户确认 12 V、限流 0.5 A、无报警、U/V/W 动力线断开后，提交一次正常 bootloader 试运行。

实测在健康确认前停机，没有自动重试：

| 项目 | 结果 |
| --- | --- |
| ADC 样本 | 28312 对，MISS=0，PF=0 |
| 零点 | STATE=3、REASON=0、N=4000，U0=1562、V0=1561 |
| FOC 工作 | WORK=4308，MAX_US=50，LATE=1 |
| ADC 中断记录 | MAX_CYC=9206，约 54.153 µs；计量仍不包含完整尾声 |
| 延迟计划 | STAGED=4308、TAKEN=4307、EMPTY=1 |
| 失效计数 | STALE=0、UNSAFE=0、REJECTED=0、PLAN_FAIL=0 |
| 故障后待用计划 | VALID=0，已清空 |
| 反馈修补窗口 | HITS=1/6、RUN=0/4、TOTAL=78 |
| 故障 | FLAGS=256（CL_COMPUTE_LATE），REASON=3 |
| 输出 | ADMISSION=0、PUBLISH=0、SD=0、MOE=0、CCER=0 |

计划交接在故障前持续工作；未取出的最后一项在超时关断时被清空。此次停机是计算超时，修补预算没有耗尽。CPU_MAX_CYC=4477（约 26.34 µs）、PREEMPT_MAX_CYC=3906（约 22.98 µs）分别是独立最大值，不能相加还原同一故障帧。本次没有取得逐源抢占归因，不能断定具体由哪个中断造成。新增规划/交接及边界观察都增加执行成本，实测不能作为下一周期实际 CCR 发布或控制相位稳定性的证明。

故障后已发送 `ANALOG SAFE`、关闭输出并停住 CPU；用户关闭 12 V 后，通过既有 bootloader 恢复已确认 B。最终 `confirmed=B, pending=none, attempts=0, generation=579`，VTOR=0x08040000，CPU 停在 B 入口，SD/MOE/CCER/CEN=0。完整比对证明本次试运行与恢复期间应用和私有区没有改变。A 仍保留未确认的诊断镜像。全程 host_motor_commands=0，没有启动电机。

公开收据：

- [暂存及完整回读](safety_backups/protected-closed-loop-20261014/rc-deferred-shadow-stage-1792140289721385500.json)
- [单次试运行与故障快照](safety_backups/protected-closed-loop-20261014/rc-deferred-shadow-trial-1792140355810017000.json)
- [恢复已确认 B](safety_backups/protected-closed-loop-20261014/rc-deferred-shadow-restore-1792140423717718000.json)

下一轮优化应先减少影子路径的重复规划、复制及屏蔽中断开销，补充同一故障帧的已有轻量耗时字段；保持 50 µs 截止条件。只有新的实测覆盖计划交接、总耗时和实际 PWM 装载边界，才可讨论正式控制版本。
