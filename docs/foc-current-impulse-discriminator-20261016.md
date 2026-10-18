# 两拍电流判别器：修复 last-valid reference 锁死

2026-10-16。本轮只改 Fast Current Reject 判别、统计、对应测试和文档。没有连接 ST-Link/串口，没有刷写、复位、提交启动元数据或发送 START；板端原 B 启动选择未改。PI 增益、SVPWM、速度/位置环、编码器、触发频率、任务频率、Tightening、CAN、Pigweed、IAP/bootloader 均未修改。

结论：**代码 + PC 测试完成，等待人工上板验证**。旧版测得的 19.64 µs 不代表新版耗时。

## 原因与修改位置

旧版 `firmware_common/foc_current_fast_reject.h` 的 `FocCurrentValidation_Push()` 只和 `last_valid_u/v` 比较，接受才更新、拒绝不更新；拒绝计数连续达到 3 后，`FocFeedbackSafety_Push()` 复用 `FOC_FP_CURRENT_INVALID` 故障。参考被小步带偏至 U=1626 后，接近零点的 1560 与参考相差 66>60；即使持续恢复，也会拒绝并锁死。

当前状态保存在 `FocCurrentValidation`：`reference`、`candidate` 都是完整 `CurrentRawPair`，状态只有 TRACKING / SUSPECT。SUSPECT 期间 `reference` 本身就是 old_reference，不额外复制第三对数据。只有同一个 ADC 所有者更新；实际调用持 PRIMASK，Monitor 只在短屏蔽区一致性复制。这里的 atomic pair 是“整对接受/更新并串行访问”，不是宣称 C struct 赋值是跨线程原子指令。

关键变化：

```diff
- 距 last_valid >60 -> reject，参考不动；第三次 reject -> fault
+ TRACKING 距 reference >60 -> 保存 candidate，SUSPECT，hold 一拍
+ 下一拍回旧值 -> 确认 isolated spike，接受本拍
+ 下一拍符合新值/有界 ramp -> 确认 transition，reference=本拍
+ 无法解释 -> 更新 candidate，累计 unresolved；第三次 unresolved -> 原故障链
```

## 状态与容差

所有距离均为整数 `max(abs(ΔU), abs(ΔV))`；无排序、窗口预测、浮点范数、动态分配或 ISR 日志。

| 状态/条件 | 操作 | 电流环 |
|---|---|---|
| TRACKING，d(reference,N)<=60 | 接受整对 N；reference=N | 正常计算 |
| TRACKING，大于60 | candidate=N；进入 SUSPECT；suspect++ | hold |
| SUSPECT，d(reference,N)<=25 | 若无 unresolved，spike++；否则 recovered++ | 接受 N，回 TRACKING |
| SUSPECT，d(candidate,N)<d(reference,N)，且 d(candidate,N)<=25 | transition++，reference=N | 接受 N，回 TRACKING |
| SUSPECT，更接近 candidate、d(candidate,N)<=60，且 d(reference,N)>=d(reference,candidate) | 有界向外 ramp，transition++ | 接受 N，回 TRACKING |
| SUSPECT，其余 | candidate=N，reference 不动；unresolved++ | hold；连续3次后故障 |

返回优先于 transition。25 是可配置初始值，不是已标定控制边界。ramp 额外要求距旧参考不缩短，使 CONFIRM 以外的确认不退化成任意“大跳后更接近另一个大跳”；相距 >60 的无关候选不直接接受。仍然无法仅凭两拍区分真实阶跃与相互接近的两枚干扰，这不是过流或电流测量准确性认证。

宏：`FOC_CURRENT_JUMP_THRESHOLD_COUNTS=60`、`FOC_CURRENT_RETURN_TOL_COUNTS=25`、`FOC_CURRENT_CONFIRM_TOL_COUNTS=25`、`FOC_CURRENT_UNRESOLVED_LIMIT=3`。有编译期范围检查，legacy repair 默认关闭。

只有 Case C 增加 `current_unresolved_consecutive`。初始 SUSPECT 不增加；确认 spike、transition 或恢复均清零。故障通过原 `FocFp_Trip(...FOC_FP_CURRENT_INVALID...)` 和 `ProtectedLoop_EmergencyOff()`，一次锁存只计一次。3 次 unresolved 是 150 µs；**加上最初的 suspect 一拍，从最后有效采样到故障为四个 50 µs 间隔，约200 µs**。原码过流/独立看门狗仍可先关断。

## 容差来自哪些数据

用 `tools/fast_current_reject_evidence.py --pair-distribution ...` 对保存的原码分析；分位数为 nearest-rank，中位数为通常中位数。每份3600对产生3599个相邻距离：

| 输出关闭记录 | median | P95 | P99 | P99.9 | max |
|---|---:|---:|---:|---:|---:|
| 10月12日 off-repaired-a-1791801336398511500 | 5 | 25 | 91 | 289 | 337 |
| 10月13日 off-1791879204193467700 | 4 | 20 | 72 | 211 | 306 |

两份含异常和返回沿，没有人工标注“真实正常”样本，故**不能声称上表是纯正常分布**。条件筛掉相邻距离>60后的分布也由脚本明确标成 conditional，不能用它证明60正确。取两份较大的 P95=25 作为返回/稳定确认的保守窄初值；不用 P99/最大值把旧 jump=60 一起放宽，也不把20计数离线阈值当在线拒绝门限。真实运行的 R/L、电压、转速及电流阶跃仍需人工上板验证。

输入文件（Git忽略的原始收据）：

- `safety_backups/switch-feedback-20261012/off-repaired-a-1791801336398511500.json`；SHA256 `df4d7aa3733370b13520cd310c773250b4195fceb46e1071fbdeb3f600f5ee0c`。
- `safety_backups/switch-trend-compare-20261013/off-1791879204193467700.json`；SHA256 `c5961fb3d261e18babb0a6624204800ce55f0f6877aa70c710b3189fa70fcd77`。

## Freeze 与 safety 核对

`ProtectedLoop_Pair()` 返回就绪之后，`protected_adc_irq.inc` 才进入 `FOC_CurrentLoopStep()`。SUSPECT/Case C 不生成 frame，不执行 Clarke/Park、电流 PI、积分、Vd/Vq、inverse Park、SVPWM 或 PWM compare/preload 写入，甚至 READY 的 PI reset 也不执行。不是把旧电流再次送进 PI。

保留原角度时间推进（避免转子时间基准少一拍），不推进电流 PI。独立任务的原速度/位置环代码没有修改；不把“IRQ电流环冻结”扩称为暂停整个 FreeRTOS 系统。正常情况下保持上一有效 PWM 计划，既有 preload 仍可在硬件更新事件锁存。STOP、过流、采样超时或其他故障可以覆盖 hold 并关闭输出。

`FocFp_PushRawSafety()` 仍先处理**每个**物理 U/V 对，再进入判别器：原 4 A / 2-of-3、原始 U/V 和有符号重构 W、序列/时间、driver fault、输出锁与独立 TIM7 看门狗都保留。原码保护已故障时不再更新判别统计，避免把安全故障误叫 transition/spike。FOC 的 W 仅在整对接受后生成；raw safety 自己的 W 仍从每对原码独立计算，不受反馈 hold 屏蔽。

现有 TIM1 Break / Break2 配置仍为 DISABLE；通用 driver fault 标志入口不等于已验证实物硬件链。本轮未修改/伪造它们，也未用驱动板声称的保护替代原码保护。

## 统计

`FocCurrentValidation` 提供 samples、suspect、confirmed_spike、confirmed_transition、unresolved_total/consecutive/max、measurement_fault_count，以及 unresolved 后恢复计数。`FocCurrentCycleStats` 独立统计 normal / suspect / unresolved 的 last/max cycles、总体 last/max、deadline miss。

MonitorTask 每5秒输出 `CURRENT VALIDATION samples=... suspect=... spike=... transition=... unresolved=... run=... max_unresolved_run=... fault=... recovered=... normal_max_cycles=... suspect_max_cycles=... unresolved_max_cycles=... last_cycles=... max_cycles=... deadline_miss=...`。仅 confirmed_spike 用 spike 命名，且仍是算法分类；suspect/hold 数绝不能直接称物理毛刺数。ISR 中只有整数计数和 DWT 记录，格式化留在任务侧。计数饱和、不因 START 清零。

8500 cycles/50 µs 判据和原时序告警不变。外层 DWT 区间含抢占，不包含异常入/退栈及 recorder 尾部；事后计时不是 WCET 证明。

## 离线验收结果

8项新 unittest 和24项旧保护/原 FSM/整数 guardian/feedback 测试全部通过。覆盖10组用户指定用例：稳定、正/负单点、step、ramp、1626恢复、交替不相干数据、仅U、仅V、U/V同时异常；另测容差边界、长重复脉冲、unresolved恢复、原码U/V/W过流、硬件标志、超时/序列、计数饱和和DWT边界。

真实 IRQ 包装在 `-Os/-O2` 下用有副作用的 PI/PWM stub 验证 SUSPECT/Case C 都不修改积分、Vd/Vq或PWM。实际绑定验证 Case C 关门极、原码保护优先、计算版拒绝 START。

`tests/foc_current_impulse_kernel.c` 编译成 Cortex-M4 ARM 对象，判别核无 VFP、外部调用、除法、循环或输入相关存储；实际链接入口无旧修补/分配/日志调用。不是通过PC时间估算MCU微秒。

`tools/fast_current_impulse_replay.py` 编译真实 C 核回放上面两份原码，Os/O2一致：

| 原码记录 | 接受 | hold | suspect | confirmed spike | transition | unresolved | max unresolved | fault |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 10月12日3600对 | 3571 | 29 | 27 | 25 | 2 | 2 | 1 | 0 |
| 10月13日3600对 | 3573 | 27 | 26 | 25 | 0 | 1 | 1 | 0 |

第二份另有1次 unresolved 后恢复，不叫单点 spike。这只是保存原码的 selector 回放，不是新采集、带电控制通过或物理噪声真值。旧实际失败批次只保存终点而无完整前窗，故不能声称回放过其全部2988对。人工构造 `(1563,1561)→(1594,1585)→(1626,1609)→(1560,1557)×3` 已验证恢复；指定 `1626→1560→1561→1562` 同样只 hold 一拍、不 fault。

已有 `fast_current_reject_evidence.py` 的旧版 RAM 摘要也离线重跑通过：仍是2988/29/最后参考1626,1609；没有用新版结构去解释旧RAM。

## 编译、告警、占用

四个 A/B `FastCurrentReject` / `FastCurrentRejectComputeOnly` 镜像均编译链接通过。新旧同源 main 语法编译对照未新增 warning；保留已有未使用函数/变量告警及 linker RWX 告警，没有全局屏蔽。

| 镜像 | Flash /229376 B | RAM /131008 B | BIN SHA256 |
|---|---:|---:|---|
| A 正常候选 | 226884 | 125728 | `7e14d84b6ce5ac34451525fdcdeedb0c9e23c9f423a30aad8eb0803aa95ba0f4` |
| B 正常候选 | 225852 | 125712 | `20efa72a160f2a4e18c05af3f7d48622308f80a99b2cc7cf3afd1868ab66e379` |
| A 计算版 | 225068 | 125560 | `cd2539cad04e76685dd5dcc72b4e82071512b9813ecbd8c1eedffb1c69f5b11e` |
| B 计算版 | 224020 | 125544 | `7af544737578d13ef791a43864249dbc3fcef9d3971e845bd4af83128a2f7bb6` |

A计算版实际链接 ADC IRQ代码从4288到4404字节（+116），总Flash +72、总RAM +144；判别状态新增12字节、周期统计新增8字节，其余含代码/RAM布局与对齐。代码尺寸不是执行耗时；RAM静态占用不是运行栈峰值。新版没有板端 DWT、栈水位或30秒验收结果，不能声称仍为19.64µs或已达到最坏50µs。

## 后续上板记录

上述离线阶段结束后，用户另行请求上板，已完成一次功率硬关闭的实物试运行。
三路径观察最大值为41.82／27.75／14.85 µs，但启动期间因独立保护链
`FOC_FP_TIMEOUT`停止，未完成30秒验收；已恢复原B并停在入口。
详细边界与证据见 [本轮上板记录](foc-current-impulse-board-20261016.md)。
下节保留原离线交付时的流程说明，不代表仍未上板。

## 复查命令与下一次人工上板

当前无需执行任何刷写/复位命令。可离线复查：

```powershell
Set-Location 'D:\new project'
python -m unittest discover -s tests -p test_foc_fast_current_reject.py -v
Set-Location 'D:\new project\tests'
python -m unittest test_protected_closed_loop test_latest_original_fsm test_foc_guard_fast test_foc_feedback_fast -v
Set-Location 'D:\new project\foc2_app_a'
cmake --build --preset FastCurrentRejectComputeOnly -j 4
```

回放/分布命令在项目根目录：

```powershell
python tools/fast_current_impulse_replay.py safety_backups/switch-feedback-20261012/off-repaired-a-1791801336398511500.json safety_backups/switch-trend-compare-20261013/off-1791879204193467700.json
python tools/fast_current_reject_evidence.py --pair-distribution safety_backups/switch-feedback-20261012/off-repaired-a-1791801336398511500.json --pair-distribution safety_backups/switch-trend-compare-20261013/off-1791879204193467700.json
```

旧 `tools/fast_current_reject_board_test.py` 固定旧镜像 hash/B579历史基线，**不能用于本版部署**，保留其历史证据语义，不能只改SHA强行重跑。人工决定上板后，需先核验当前实际已确认B/元数据，再另建绑定本轮镜像的新暂存/回读流程。先测非活动A计算版、保留B，确认输出关闭，再看三个DWT分支/计数/30秒稳定性；不自动启动电机。本轮到此停止。
