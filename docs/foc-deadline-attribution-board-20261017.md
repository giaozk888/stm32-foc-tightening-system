# Deadline attribution 上板验证（2026-10-17）

## 结论

取得了完整有效的首次 deadline-miss 同周期快照，修复后的归因链在本次实机触发中有效。整机时序验收仍未通过：正常路径出现一次 54.435 µs wall deadline miss，保护停止，不自动重试；未完成 30 秒观察或健康确认。

本次仅写非活动 A，并按 bootloader 正常试运行流程启动功率硬关闭诊断版。没有发送 START、强制健康确认、开启 SD/MOE 或连接电机功率输出。B 应用、槽外及私有配置保持不变；完整 Flash/SRAM 留在原 private 证据目录。

## 同一超时帧（不是不同最大值相加）

| 字段 | cycles / count | 时间 |
| --- | ---: | ---: |
| wall | 9254 | 54.435 µs |
| TIM2 抢占 | 2711 / 6 次 | 15.947 µs |
| DMA1 CH4 RX 抢占 | 662 / 2 次 | 3.894 µs |
| TIM7 / TX / 其他归因抢占 | 0 | 0 µs |
| preempt total | 3373 | 19.841 µs |
| active estimate | 5881 | 34.594 µs |

9254 = 5881 + 2711 + 662，DWT exit-entry = 258192525-258183271 = 9254。`deadline_snapshot.captured=1, valid=1`，状态 `VALID_FIRST_MISS`，与旧布局的 `first_miss` 一致。所有 28139 个已记录 ADC frame 的归因 invalid=0，未知高优先级 IRQ=0。

此次 54 µs 帧明确包含编码器 TIM2/RX 抢占约 19.84 µs，非抢占部分估计约 34.59 µs。证据支持“编码器链路抢占把这一帧推过 50 µs”，不再只是根据历史最大值推断。但 active estimate 包含提交适配、诊断插桩、IRQ hook 外异常成本等，不能称为纯 FOC 数学 WCET；也不能从本帧倒推旧 52.359 µs 帧的精确组成。

该帧 path=1，故障快照 normal max=9254，停机原因为 `FOC_TO_COMPUTE_DEADLINE`（18）、flags=256，而不是编码器协议错误、电流硬过流或 CUR_CONFIRM fault。编码器有效、协议错误计数为零。

## 一拍 CCR 提交

- 真实 CCR commit：4137 次，有效测量 4137 次。
- actual late / blocked / post-unsafe / latch crossing / mixed latch：均为 0。
- 最小实际 margin：2059 timer ticks / 12.112 µs，超过既有 170 ticks / 1 µs guard。
- 实际 CCR 写事务最大耗时：508 cycles / 2.988 µs，包含事务测量成本。
- 整个提交适配路径最大 wall：4163 cycles / 24.488 µs，不能当作三条寄存器存储耗时，且不能与上表独立最大值相加。
- pending generation max：1049 cycles / 6.171 µs，含诊断。
- hypothetical 尾部 margin 最小 -4.047 µs；该处真实写入为 0。它与 actual 入口提交账本完全分开。

TIM1 ARR=4249、PSC=0、RCR=0，center-aligned mode 1，TRGO2/ADC 触发沿用原配置；probe 未修改 update 行为。测量以真实入口写事务到目标 bottom 的保守余量为准，并非 ISR exit 粗判。没有直接外测内部 shadow latch，不能据此宣称长期无 late 或电机闭环通过。

正常 FOC 执行 4105 次，提交窗口约 0.207 秒；28139 个 frame 包含启动校准阶段。TIM7 对 ADC 抢占为零；TIM7 的 service wall max=37.206 µs 包含被高优先级 IRQ 打断，不能解释为它抢占了 FOC。

## 保持不变与后续方向

现场优先级仍为 TIM2/RX/TX=1、ADC=2、TIM7=3、SysTick/PendSV=15。未修改 IRQ priority、控制数学、电流判别器、CUR_CONFIRM、保护阈值或通信升级路径。

CUR_CONFIRM enter/clear/fault=0/0/0，本轮未覆盖该分支，因此只能说“未触发”，不能说重新验收了 CUR_CONFIRM。既有 2 个正常 sample / 最多 4 周期配置未变。

当前确认了本帧抢占来源，下一步应审查 TIM2 六次服务的聚集与状态推进成本。TIM2 还承担事务 deadline/控制 watchdog，不能直接整体降级；若要降级数据处理，应先拆清安全/CS 时序与非安全处理，再离线回归并另外板测。正式耗时还需独立测 heavy=0，而非将诊断版的 54.435 µs 宣称为已优化通过。

## 证据和停止状态

- 暂存收据：`safety_backups/protected-closed-loop-20261014/deadline-attribution-stage-1792218040048333300.json`。
- 试运行收据：`safety_backups/protected-closed-loop-20261014/deadline-attribution-trial-1792218107804562700.json`。
- 新 A BIN SHA256：`ce8cacaf9e106d0c80c980cbcd63a0410110dab32fb59c4e4bac0a51a7008a70`。
- 同镜像 ELF SHA256：`d6e0bf8143591a6d11fbf88566aa64ff59e78a8e724c1d8eea43a45e66c8bd21`。
- 最终试运行收据：SD=0、MOE=0、CCER=0、CPU halted；Flash 应用及私有配置字节未变。
- 此刻 confirmed=B、pending=A、attempts=1、generation=603，尚未恢复启动选择。已请用户关闭 12 V；确认后仅恢复原已确认 B 并停在入口，不再试运行。

本轮固件仍对应原 117 项离线测试的固定镜像；新增板测脚本的 4 项离线门禁/解码判据测试通过。
