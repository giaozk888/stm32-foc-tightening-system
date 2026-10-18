# 2026-10-17：同周期抢占归因与真实 CCR 硬关闭探针实测

## 结果与最终状态

已取得新 A 镜像的同周期证据，但本轮验收 **FAIL**：试运行约启动后 1.387 s 首次记录定时器健康故障，未完成计划的 30 s 观察。不能据此宣称稳定通过或允许电机闭环。

用户关闭 12 V 后，通过原 bootloader 流程恢复原已确认 B595 的启动选择，元数据 generation=598、pending=0、attempt=0。MCU 停在 B 入口，VTOR=0x08040000，SD=0、BDTR=0、CCER=0。没有运行 B 应用，没有发送 START，没有自动重试。应用与私有区字节在恢复操作中未变；不是把 A 区恢复成旧镜像，新诊断 A 仍留存但未被选为待试运行槽。

本轮未改固件控制算法、阈值、IRQ 优先级或频率。新增板端编排/离线解码工具，并在 host 测试中增加 UDIS 健康检查冲突复现；该测试不改变已刷镜像。

## 镜像与证据归属

- A BIN：228524 B，SHA-256 `6673490d00bab3958583b73474efd065daa60f8332ea1938861bb59b027dba9c`。
- A ELF SHA-256：`781cc94baf551467098eb7045b6bb68feacdc71409f7bdb725f62e2237b6c161`。
- 全 Flash 回读核验 A 镜像；同一停止会话读取 SRAM 与 VTOR=0x08008000，再按精确 ELF 符号解码。不能拿别的镜像/不同周期的最大值相减。
- 本地收据目录：`safety_backups/protected-closed-loop-20261014/`。
- 暂存：`preempt-commit-stage-1792207831614525800.json`，PASS，A 外擦除页未变。
- 试运行：`preempt-commit-trial-1792207891441202700.json`，FAIL，但 `same_cycle_evidence_collected=true`。
- 恢复：`preempt-commit-restore-1792207960510738800.json`，PASS。
- 原始 Flash/SRAM 含私有数据，只保存在被忽略的本地 `private` 目录，不作为公开附件。

## 同周期抢占归因

共记录 25656 帧，676 帧因快照/观测无效不作有效抢占分解。运行期 IRQ 优先级核验通过，没有未知来源；TIM7=0，TIM2/RX/TX DMA=1，ADC=2，SysTick/PendSV=15。

本次最大有效抢占帧恰好也是 wall 最大帧，path=NORMAL：

```text
wall = 7095 cycles = 41.7353 us
TIM7 = 2346 cycles = 13.8000 us，2 次
其他已统计 IRQ：本帧均为 0
active_est = 4749 cycles = 27.9353 us
7095 = 2346 + 4749
```

因此本次最坏有效帧可明确分解为 **41.74 = 13.80 + 27.94 us**。未复现历史 59.43 us，不能倒推历史那次超时一定来自 TIM7。

全程 `active_est_max=31.7471 us` 是另一个帧的独立最大值，不能代入上式。`deadline_miss=0`，首次 miss 快照为空。`observer_tail_max=6.3706 us` 也是独立最大值，位于 wall 出口时间戳之后，不能直接加到 wall_max 冒充同周期实测。active_est 仍含 hook 边缘、未覆盖的异常边界与诊断开销，不是纯数学 WCET，也不是整个物理 ISR 的完整时长。

| IRQ | 次数 | exclusive 累计 cycles | 单次 inclusive max/us |
| --- | ---: | ---: | ---: |
| TIM7 | 51300 | 33960038 | 9.6529 |
| TIM2 | 105 | 46895 | 3.1588 |
| DMA1_CH4_RX | 42 | 14574 | 2.0412 |
| DMA1_CH5_TX | 0 | 0 | 0 |

这些累计次数覆盖采集窗口，不表示都发生在 FOC 内；只有帧内 delta 是该 FOC 的抢占量。

## 实际 CCR 写入和 hypothetical 的区别

实际写 CCR1/2/3 共 1623 次，有效结束观测 1622 次、无效 1 次；另有 23 次准入阻止。SD/MOE/CCER 使能未被执行，CCR4/UG 未由探针改动。

| 指标 | actual CCR 事务 | hypothetical duty 到达点 |
| --- | ---: | ---: |
| 有效观测 | 1622 | 1625 |
| 无效观测 | 1 | 22 |
| 相对原目标底点最小 margin/us | **-8.0588** | +4.1941 |
| margin<=0 次数 | 1622 | 0 |
| 真实写入次数 | 1623 | 0 |

两组最小值不是同一周期，不可相减当作 planner/probe 固定开销。

actual 最差 margin 的同帧起止证据：

```text
entry: DWT=236173851，CNT=3145，向下，读点包络=23 cycles
end:   DWT=236178366，CNT=1347，向上，读点包络=23 cycles
elapsed=4515 cycles
margin=3145-4515=-1370 ticks=-8.0588 us
```

真实 CCR 写入结束已在原计划底点之后，所以本诊断镜像中确有 **missed intended bottom**，不是仅靠 ISR 总时长推测，也不是只存在于 hypothetical 告警。

但另一个问题必须分开：从事务开始锚定的下一个自然 UEV，最小剩余 `latch_margin=+16.9353 us`，有效事务 `latch_crossings=0`、`possible_suppressed_uev_count=0`。这说明有效观测未显示 UDIS 事务横跨其下一个自然 UEV，不能声称观察到三 CCR 分裂生效或内部 shadow latch 本身。硬关闭探针允许记录 late write，正式生产 `CommitBeforeBottom()` 的拒绝规则未改。

实际寄存器：CMS=1、ARR=4249、PSC=0、RCR=0，CCR preload 开启，CH4/TRGO2=OC4REF；自然 UEV 包括顶点与底点。相对原目标底点迟到，和从已迟到事务开始到随后 UEV 仍有余量，并不矛盾。

CCR 事务测量包络 max=1060 cycles=6.2353 us，包含读取/屏障和可能的抢占，并非三条 store 本身的纯 CPU 耗时。

## 本次提前停止的原因与证据边界

首个冻结故障的 `protection_flags=128`，对应 `CL_BAD_TIMER`；`timeout_reason=0`、wall deadline miss=0。后续状态出现 132（128+CL_BAD_ADC），不可把后续复合标志误读成首次故障来自 ADC 尖峰。CUR_CONFIRM 为 enter=1、clear=1、fault=0、max_cycles=2、max_elapsed=100 us，本轮未因 CUR_CONFIRM 停机。

代码中存在可复现的诊断冲突：

1. `FocAdcTiming_HardOffCommitProbe()` 在写三个 preload 的短事务内设置 `TIM1.CR1.UDIS`，按本轮要求不屏蔽高优先级 IRQ。
2. TIM7 可以此时抢占，调用 `ProtectedLoop_Health()`。
3. 该检查调用 `FocAdcTiming_FastCanStart()` → `TimerGeometryReady()`；后者要求 UDIS=0。
4. 所以合法的诊断事务窗口会被当成 `CL_BAD_TIMER`，执行现有紧急停机。

新增 host 断言在真实适配器的 mock barrier（UDIS 已置位）调用 FastCanStart：事务前 true、事务中 false、事务后 true；`-Os/-O2` 均复现。这证明谓词冲突。板端首故障 128、真实事务后失效计数 `post_unsafe=1` 与该路径相符，但本轮未冻结 TIM7 发现故障瞬间的 CR1，因此尚不能排除其他同属 CL_BAD_TIMER 的触发条件，不能把推断写成已直接抓到 UDIS=1 的硬件快照。

`post_unsafe=1` 同时涵盖 CEN 被关或 gate 条件不符，不等价于 SD/MOE 曾被打开。该事务的结束点被标无效，不能隐藏这一笔写入或用有效点证明它的 latch 时序。

下一轮应修复并验证探针事务与 guardian 健康检查的并发契约，保留硬关闭、独立保护和原阈值；不能简单取消 timer fault 或提高优先级掩盖冲突。本轮按验证范围停住，不修改固件、不再次试运行。

## 离线复核

- 原镜像构建收据：9 项配置、102 个离线测试通过，见 `tests/foc_adaptive_build/preempt_commit_evidence/receipt.json`；它是刷写前记录，不冒充本次物理验收。
- 本次追加复核：`test_foc_preempt_commit_probe.py` 6/6，通过（含更新后的 UDIS 谓词断言和原编译 warning 对比）。
- 板端编排/解码器：`test_preempt_commit_board_test.py` 5/5，通过，测试不会访问设备。
- 控制固件未在本次故障后再改动，A/B BIN 哈希保持固定；未新增控制算法、保护阈值、频率或 NVIC 改动。
