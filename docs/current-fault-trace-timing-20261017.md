# Trace A 上板时序实测（2026-10-17）

## 结论

新诊断 A 已实物运行。已观察的计算时序满足 50 us，真实 CCR late=0；
但原计划的 30 秒无故障观察未完成，电流判别器触发 CURRENT_INVALID，
**整轮验收 FAIL，不是完整控制或带电闭环 PASS**。没有发送 START，没有改保护。

| 指标 | 实测 |
|---|---:|
| FOC wall max | 5235 cycles / 30.79412 us |
| normal path max（故障快照） | 5235 cycles / 30.79412 us |
| suspect path max（故障快照） | 3834 cycles / 22.55294 us |
| unresolved path max（故障快照） | 3637 cycles / 21.39412 us |
| >50 us deadline miss | 0 |
| actual CCR commits | 475373 |
| actual CCR late / blocked / post-unsafe | 0 / 0 / 0 |
| actual CCR 最小 margin | 2231 timer ticks / 13.12353 us |
| CUR_CONFIRM enter / clear / fault | 185 / 185 / 0 |
| CUR_CONFIRM max cycles / elapsed | 2 / 100 us |

CPU 和 TIM1 均按现有 170 MHz 标定解码，未修改原 DWT 边界或判据。
heavy profiling 关闭，不能把 preemption 的未采集字段写成实测零。
hypothetical margin 同样未保留，不能替代上表 actual 值。

## 首故障

板端 timestamp_ms=25067，domain=2，reason=11，即 FOC_FP_CURRENT_INVALID，
timeout_reason=0。TWO_SAMPLE 的 unresolved_consecutive=3，达到既有
UNRESOLVED_LIMIT=3；measurement 判别故障，不是 FOC 超时、CCR late 或
CUR_CONFIRM 超时。原码终点 1563/1561 本身不能解释此前候选/参考演变。

故障快照：suspect_total=3544、confirmed_spike=3347、confirmed_transition=162、
unresolved_total=61、unresolved_max_consecutive=3。这里的 spike 是判别器分类计数，
不是独立仪器确认的物理尖峰数。不能据此把三次 unresolved 等同于三个连续电流尖峰。

## Trace 本身

16 帧 / 每帧 52 B 已在实机读取并按原 schema 解码：seq=28522..28537 连续。
首次触发 seq=28531，U/V raw=1897/1829，zero=1562/1561，
重建 U/V/W 电流计数=-335/-268/603，limit=595，over_mask=W。
该触发帧 discriminator=HOLD；随后两帧正常完成确认，seq=28533 恢复，
再记录四帧后按既定规则冻结（freeze_reason=2，fault_seq=0）。

因此这是**较早的 CUR_CONFIRM 触发与恢复窗口**，不是后来 reason=11 的故障窗口。
没有自动 rearm、覆盖首次窗口或修改触发策略。后来故障只有现有首故障快照，
还不能给出该故障前后连续原码。不能声称本轮已经捕获 reason=11 的完整连续窗口。

wall max 覆盖当前启动的初始 armed trace 和冻结后路径；没有分状态 cycle max。
30.79 us 是本轮已观察最大值，不是所有 trace 状态或上电运行条件的 WCET 保证。

## 镜像及过程

- A BIN：229316 B，SHA256 `4f886e22078594215d8436fa8ab35b09f2040fda4cd443cccfd1bc3463e6591d`。
- A ELF SHA256：`2d461690cbd6fc1183d189d0eb566f8ba166b60b026bb061b83cfeb4c9ef6e6e`。
- 原 B619 整片基线及实际板上 Flash 逐字节匹配后，仅写非活动 A。
- 暂存后完整回读成功，A 擦除页外字节和原 metadata 未变。
- 本轮一次正常 bootloader 试运行，APP 通过既有健康窗口后自动确认/复位到 A622。
- 未强制确认、未重试激活、未直接写 Flash metadata、未发送 START。
- 这是 HARD_OFF=0 的闭环候选诊断配置；不把它伪称为编译期 HARD_OFF=1。
  本轮仅其 READY 计算路径，所有采样状态均 SD=0 / MOE=0 / CCER=0。
- 故障后执行 ANALOG SAFE，再 SWD 停住、关闭 SD/MOE/CCER 和 TIM1，
  同一停止状态保存完整 Flash/RAM，VTOR=0x08008000；B 和私有数据未改。
- 截至本报告，MCU 已停住、功率输出关闭；启动选择仍为 A622。
  **尚未恢复 B 选择，须待用户关闭 12 V 后执行已有 bootloader 恢复流程。**

机器收据位于 `safety_backups/protected-closed-loop-20261014/`：

- `current-fault-trace-stage-1792238712413255200.json`
- `current-fault-trace-trial-1792238818857368100.json`

完整 Flash/RAM 继续保存在既有受限 private 目录，不复制到公开文档。

板测入口新加的 6 项离线/mocked 测试和健康确认等待的 17 项测试通过；
此前 firmware 的 54 项离线测试收据仍对应本轮精确镜像。本次没有修改 firmware。
