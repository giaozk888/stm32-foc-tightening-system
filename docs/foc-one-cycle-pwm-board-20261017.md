# 一拍 PWM pipeline 上板验证（2026-10-17）

## 结论

整体验收未通过：出现一次 FOC 50 µs deadline miss。此次短窗口内，真实 CCR 入口提交未发现 late-write，TIM7 对 ADC 的抢占为零。不能据此宣称长期 WCET、内部 shadow latch 或电机闭环已验收。

仅试运行一次功率硬关闭的 A 槽诊断镜像，未发送 START、未启用功率桥，电机动力线断开。故障发生在启动健康确认之前，未完成原计划的 30 秒观察。正常 FOC 计算 4335 次；包括保持周期的提交窗口约 0.218 秒。ADC 总计 28365 对，包含启动校准阶段。

## 关键结果

| 项目 | 实测 | 判断 |
| --- | ---: | --- |
| 真实 CCR 提交 | 4363 次 | 全部有有效测量 |
| actual late / blocked / post-unsafe | 0 / 0 / 0 | 短窗口内未发现异常 |
| 最小实际提交余量 | 1599 ticks / 9.406 µs | 超过既有 170 ticks / 1 µs guard |
| 跨 latch / 可能混合提交 | 0 / 0 | 未观察到 |
| 实际 CCR 事务最大耗时 | 508 cycles / 2.988 µs | 包含事务测量开销 |
| 完整提交适配路径最大耗时 | 2908 cycles / 17.106 µs | 含诊断及短临界区外抢占，不能当作三次寄存器写耗时 |
| pending 生成最大耗时 | 1041 cycles / 6.124 µs | 包含统计开销 |
| TIM7 抢占 ADC 最大耗时 | 0 µs | 优先级调整生效 |
| FOC wall 最大耗时 | 8901 cycles / 52.359 µs | deadline miss = 1 |
| 有效归因帧的 active estimate 最大值 | 32.553 µs | 尚未达到 <30 µs 目标 |
| CUR_CONFIRM enter / clear / fault | 1 / 1 / 0 | 最多 2 周期 / 100 µs；配置仍为 2 / 4 |

实际提交目标为本次 ADC 入口之后的 bottom，提交上一有效周期的 command。根据向下计数 CNT 与 DWT 写事务时长计算到该目标的保守余量；没有修改 UDIS 或 update 行为。TIM1 ARR=4249、PSC=0、RCR=0，center-aligned mode 1，ADC 仍使用 TRGO2 OC4REF。

actual 与 hypothetical 分开保存。尾部假设提交余量最差为 -0.706 µs，但该位置不执行真实 CCR 写入。旧 IRQ 尾部粗粒度 BOTTOM_LATE=4304 也不能替代入口真实提交账本；真实提交 late=0。未关闭任何告警。

## FOC 超时归因的边界

有效的最坏抢占同周期证据：

- wall = 46.347 µs。
- preempt = 13.794 µs：TIM2 10.041 µs（4 次），DMA1 CH4 RX 3.753 µs（2 次），TIM7/TX 为零。
- active estimate = 32.553 µs，三项满足 wall = preempt + active。

首次超时帧 wall = 52.359 µs，但其抢占快照 `valid=false`。该帧原始累计差为 TIM2 15.524 µs、RX 3.753 µs，只能作为排查线索，不能据此给出可靠的同周期 active 分解。字段 active_est=0 是无效快照哨兵，不是实际计算耗时为零。

因此：有效证据指向编码器 TIM2/RX 抢占仍占用时间，TIM7 已不再抢占；但 52.359 µs 那一帧的精确归因尚未完成，下一步应查快照一致性及编码器中断聚集，不应直接更改保护或控制数学。

现场优先级读回：TIM2/RX/TX=1，ADC=2，TIM7=3，SysTick/PendSV=15。TIM7 自身服务 wall 最大 36.488 µs 包括被子中断抢占，不是其对 ADC 的抢占时长。

停机快照为 `FOC_TO_COMPUTE_DEADLINE`（18），保护 flags=256；不是 CUR_CONFIRM fault。未自动重试。本轮没有修改固件控制算法、阈值或中断优先级。

## 最终恢复

用户关闭驱动板 12 V 后，通过现有启动流程恢复原已确认 B：confirmed=B、pending=none、attempts=0、generation=601。CPU 停在 B 入口，VTOR=0x08040000，SD=0、BDTR=0、CCER=0。A/B 应用及私有配置字节校验未变；无强制健康确认、无直接元数据写入、无电机启动命令。

证据收据：

- [暂存](../safety_backups/protected-closed-loop-20261014/pwm-pipeline-stage-1792211237823693600.json)
- [单次试运行](../safety_backups/protected-closed-loop-20261014/pwm-pipeline-trial-1792211316429761600.json)
- [B 槽恢复](../safety_backups/protected-closed-loop-20261014/pwm-pipeline-restore-1792211380702854900.json)

本次仅新增验收脚本、对应离线测试和本报告。验收脚本 4 项离线测试通过；镜像沿用此前 111 项测试通过的固定构建，没有为通过板测而更改控制代码。
