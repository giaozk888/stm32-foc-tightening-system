# 最新底层＋旧拧紧状态机

2026-10-15。本轮仅修改源码、离线测试和构建，不刷板、不复位、不启动电机。

## 保留什么、更新什么

| 部分 | 新配置使用的实现 |
| --- | --- |
| START/STOP、RUNDOWN、CONTACT_STOP、SEATING、TIGHTEN、HOLD、结果记录 | 原 TighteningTask 状态机、配方和状态转换；没有另写一套测试状态机代替 |
| IU/IV | 最新 TIM1 CH4 窗口规划、双 ADC 同步注入采样；ADC1 单一完成入口，先读并确认两路完成标志，再运算 |
| 在线筛选 | 最新优化的四点自适应孤立尖峰识别；安静区学习、有界 20～40 计数跳变阈值；只修补判定为孤立的中心点 |
| 零点 | 五点块中值、500 个物理采样一段的稳健估计；保留无效 ADC、突发异常、跨度、漂移及总异常预算检查 |
| FOC/编码器 | 最新反馈时间戳、测量/输出角分离、SPI DMA、编码器中断优先级、快速三角运算 |
| 热路径 | RAM 热函数、O2 有界内核、反馈/保护快速路径、同一受控区间内复用检查、紧凑独立中断 |
| 保护 | 最新筛选反馈 4 A 确认逻辑、修补密度预算、采样/外环超时、输出状态、编码器、计算超时等独立检查 |
| 启动接入 | 原 START 邮箱 → 原状态机重新检查 → 最新底层准入；STOP 立即关闭输出，再由原状态机报告结果 |

不是“旧版本只改几个数值”。新配置确实编入自适应筛选和最新底层。原 OriginalClosedLoopUpdated 和已保存历史镜像没有被当作这个新版本使用。

## 启动积分修正

输出关闭时，FOC 仍计算诊断数据，但电流 PI 积分不能累积后带入启动。因此：

1. 非运行态，实际 ADC 中断在 FOC 步骤前后清空电流 PI 积分。
2. 真正准入时，再清空电流 PI 积分、电流参考及上次 d/q 电压。
3. 不调用完整 FOC_ResetController，不重置旧状态机的位置、行程、配方或统计。
4. 运行态保留正常 PI 积分，不反复清空。

原状态机 CONTACT_STOP 虽然命令 IDLE，但仍属于忙碌状态，适配层不会误认为整轮结束。

## 新配置及边界

A/B 独立预设：`LatestFeedbackOriginalFsm`；标识：`FOC_LATEST_ORIGINAL_FSM`。

分别在 foc2_app_a / foc2_app_b 目录执行：

```powershell
cmake --preset LatestFeedbackOriginalFsm
cmake --build --preset LatestFeedbackOriginalFsm
```

配置身份可由 MOTOR TEST PROFILE、MOTOR TEST FILTER、MOTOR TEST ZERO ROBUST、MOTOR TEST RAM 查询。

保留上电不自启动、启动槽确认、本地显式 START、每次启动只准入一次、20 rpm 配方上限和 400 ms 独立测试租约。MOTOR TEST SPEED 被拒绝，不能绕过原 START/状态机。大于 20 rpm 的配方会被拒绝，不会偷偷改写 KVS。

这是“最新底层接回旧状态机”的限时验收候选，不是已验收的不限时工业拧紧版本。400 ms 租约可能在完整工艺结束前撤销输出；本次没有放宽工艺时长或工业转速。

硬关闭诊断分支的 FOC_ZERO_TOTAL_BUDGET_OFF 不是电机控制策略，不自动继承。本候选保留零点总异常预算 20。旧实验配置仍硬关闭，不把它直接改为可输出。

## 验证与资源

新增 7 项离线测试通过，包括实际适配层和 START/STOP 邮箱、规划期间 STOP/故障竞争、单次准入、独立租约、CONTACT_STOP 暂停、完成关断、运行/非运行 PI 积分分工、孤立尖峰修补、配置拒绝混用，以及 A/B 链接资源和整数保护调用链。

完整回归共 44 项通过：新增集成 7、原保护绑定 4、编码器优先级工具 4、紧凑闭环 7、自适应筛选 17、旧数值更新配置兼容性 5。构建最终完成后，另复核新 A/B 镜像的资源/身份及整数保护调用链 2 项，通过。工具测试首次因缺少 tools 模块搜索路径未加载，补充路径后 4 项均通过。

准入额外核对外环时间戳不超过 2 ms，不把“以前完成过外环计算”误当成当前仍新鲜。

实际 IRQ 包装层的积分测试使用会累加积分的 FOC 桩函数，验证包装层清零/保留的分工；不是完整电机数值仿真或实机效果证明。

| 镜像 | BIN 大小 | 链接 RAM 占用 | 链接剩余 RAM |
| --- | ---: | ---: | ---: |
| A | 209444 B | 122648 B | 8360 B |
| B | 208564 B | 122624 B | 8384 B |

链接剩余量不是任务动态栈峰值证明。构建保留现有未使用函数和 RAM 热代码 RWX 段警告，无编译错误。

A SHA-256：70bacc8845633412c2d42d30dd44c96a4e64952c0b2fbf05e1c880d200c9e598

B SHA-256：7adb6bb59b56d1d6b0358072a1cd64ed06611aa01a6b543ba26a343ffecf528e

50 µs 仍是实时截止条件，不是本镜像的实测最坏耗时。实际最坏耗时、带开关反馈、电机方向/反馈极性需用新镜像验证，不能沿用其他镜像的结果。

主要文件：firmware_common/latest_original_fsm.inc、latest_original_profile.h、两槽 Core/Src/main.c；回归入口为 tests/test_latest_original_fsm.py。

## 2026-10-15 上板暂存进度

用户确认驱动板 12 V 已关闭、MCU 供电稳定、电机空载固定及原接线符合短测准备条件后，完成：

- 读取完整 Flash 并保存至既有受限 private 目录，不公开原始参数内容。
- 确认上一版 B 仍处于故障停机，元数据为确认 A、待试 B、剩余 1 次、代次 542；SD/MOE/CCER 均关闭。
- 用现有 bootloader 的服务邮箱重新选择已确认且 CRC 有效的 A；在 A 复位入口硬件断点停止，未运行 A 应用。元数据变为确认 A、无待试槽、代次 543。
- 仅写入非活动 B 槽的 LatestFeedbackOriginalFsm 镜像，完整回读与 208564 字节、上述 SHA-256 对应镜像逐字节一致。
- A、bootloader、KVS 和参数区未变；暂存过程不改变元数据。CPU 保持复位暂停，SD/PWM 关闭。

暂存工具：tools/latest_original_fsm_stage.py。

证据：safety_backups/protected-closed-loop-20261014/latest-original-stage-1792053661005666800.json。

当前仅完成 B 槽写入、回读，尚未激活新版 B、未发送 START。仍不能声称闭环或扭矩精度验收通过。下一步需实际开启 12 V 后，正常试运行、健康确认和启动准入均通过才执行原 START 入口一次 20 rpm、最多 0.4 秒短测；失败不自动重试。

## 同日一次上电试运行结果：启动零点未通过

用户回复开启 12 V 后，执行一次现有 bootloader START_TRIAL。运行时身份确认 NAME=LATEST_ORIGINAL_FSM、ADAPT=1、FSM=ORIGINAL、HARD_OFF=0，确为上述新组合，不是历史 B 镜像。

启动零点结果：STATE=4、REASON=3、N=2405；稳健估计 OUTLIERS=21、MAX=20、FLAGS=8。源码核对 FLAGS=8 只对应 FOC_ROBUST_TOTAL_BUDGET，即五点块中相对块中值偏离超过 40 计数的采样对累计超过 20；不是 21 A，也不是在线四点筛选后还剩 21 个异常。块中值范围 U=1556～1570、V=1555～1566，但保留的总异常预算已触发，因此零点未准入。

MOTOR TEST TIMING 的 WORK=0、OUTER=0，FOC 计算尚未进入，不能用本次 ADC 包装层耗时冒充 FOC 50 µs 验收。编码器当时 READS=21，FAIL/TIMEOUT/IO/SCHED/STALE 均为 0；这不构成长时间编码器验收。

原 START 实测脚本调用次数为 0，未发送电机 START，也未闭环转动。没有清故障、放宽阈值或自动重试。

结束收到 STOP 和 ANALOG SAFE 回执：LATCHED=1、SD=0、MOE=0、FOC=0；调试器再次关闭 CCER/CEN 并暂停 MCU。完整回读确认应用、回退和私有区字节未变。最终元数据确认 A、待试 B、剩余 1 次、代次 545；CPU 停在 B，不声称已经运行回退 A。

实测工具 tools/latest_original_fsm_acceptance.py；新增 5 项主机准入/邮箱测试通过。证据 safety_backups/protected-closed-loop-20261014/latest-original-trial-1792053995011508600.json。已提示关闭驱动板 12 V，本轮不再启动。

## 按用户要求取消零点累计异常数量上限（尚未刷板）

20 点总量限制是此前合并控制版本时重新保留的，并非用户要求新增。现按用户要求移除本次新候选中“累计超过 20 个异常采样对就拒绝零点”的条件，OUTLIERS 仍累计显示，不再仅因这个总数导致失败。

新候选为 A/B 的 `LatestFeedbackOriginalFsmCountOnly`，继承最新底层＋旧拧紧状态机，显式选择 `FOC_LATEST_ZERO_COUNT_ONLY=ON`。历史有上限镜像、构建目录、实测工具哈希及证据不覆盖，也不把旧工具的 MAX=20 校验偷偷改成接受新镜像。

只改总量判据，不改每五点块的孤立异常判断，不减少 4000 对物理校准窗口。以下保持原样：块内多个异常拒绝、ADC 码值有效性、零点距名义中点范围、块内跨度、中心跨度、分段漂移、超时，以及在线四点筛选、4 A 确认保护、运行反馈有效性／时效、编码器、50 µs 截止、独立短测租约和旧状态机。

运行时 `MOTOR TEST ZERO ROBUST` 应报告 `MAX=OFF`、`HARD_OFF=0`；这是总量只计数，不表示所有质量检查关闭。新选项只允许与 latest/original-FSM 组合；历史 `FOC_ZERO_TOTAL_BUDGET_OFF` 仍只用于原硬关闭实验，未借用它解锁控制。

编译命令：在每个槽工程运行 `cmake --preset LatestFeedbackOriginalFsmCountOnly`，再运行同名 build preset。

新 A：209436 B，RAM 122648 B，SHA-256 `3b6638ddfbc2790e1ea83a134b336cde569da981a02d25674d014b97bc05db80`。

新 B：208564 B，RAM 122624 B，SHA-256 `689c533abc257fd0ef6933ae9855c07bff5126fa277b3f079f854c74e469d909`。

新增 tests/test_latest_zero_count_only.py 覆盖 20／21／80 个孤立异常、连续异常、非法码、中点偏离、漂移、完整窗口、在线筛选输出不变、实际适配层、配置拒绝和 A/B 链接身份。合成回放可完成含 80 个独立异常的零点，且其他失败用例仍拒绝；不是实机零点质量或闭环控制精度证明。

A/B 编译均通过；完整回归 56 项通过。追加运行时 MAX=OFF／HARD_OFF=0 文本断言后，实际适配层旧／新两项重验也通过。构建仍有既有未使用函数及 RAM 热段 RWX 警告，无编译错误。

本次只改源码、构建和离线验证，没有连接硬件、刷写、复位或发送 START。板端仍是上一轮暂停且输出锁定的有上限 B；未因源码修改自动变更。

## 后续 count-only 版本实机验证：总量取消已生效，复位后块内异常失败

用户随后要求验证，并确认 12 V 已关闭、接线不变。通过现有 bootloader 选择原 A 回退并停在 A 入口，正常元数据代次变为 546；仅将新 count-only B 写入非活动 B，完整回读一致，槽外字节与参数未变。证据：safety_backups/protected-closed-loop-20261014/latest-count-only-stage-1792054737463119300.json。

用户确认 12 V 开启、限流 0.5 A、无报警，保持电机空载固定及接线不变后，仅进行一次正常 B 试运行，不发送 START。首次启动未报告零点失败，并通过 5 秒连续健康门槛，应用请求 bootloader 正常确认后自动复位。

自动确认复位后的第二次启动，零点重新校准失败：N=1380、OUTLIERS=15、MAX=OFF、FLAGS=4；块中值 U=1555～1569、V=1556～1565。FLAGS=4 在源码中仅对应 FOC_ROBUST_BURST，即同一五采样对块内 rejected>1；不要求这两个点在块内相邻，也不能仅凭此标志断言是某根线、连续过流或某种具体硬件噪声。总数只计数确已生效，本次不是 20 点上限，也未新增限制。

故障后采集的 WORK=0、OUTER=0 只描述复位后的本次启动，不能据此抹去首次 5 秒健康确认，也不能代替首次运行的具体耗时统计。没有取得首次 FOC 最坏耗时快照，因此不能声称这轮完成了 50 µs 实时性验收。

结束：STOP 与 ANALOG SAFE 均收到回执，LATCHED=1、SD=0、MOE=0、FOC=0；SWD 关闭 CCER/CEN 并暂停 MCU，完整回读确认应用及私有区未变。最终元数据确认为 B、无待试槽、尝试数 0、代次 549，CPU 暂停在 B 的故障锁定态。A 镜像仍保留，但不声称已回到运行中的 A。

结论：取消累计异常数量上限的功能已验证生效；启动重复性和完整 FOC／电机闭环验收未通过，没有发送 START 或转动电机。已提示关闭 12 V，不自动重试。

实测工具 tools/latest_zero_count_only_acceptance.py（本次未启用其可选运动参数），绑定独立新 B 哈希及 MAX=OFF 准入策略，不篡改旧镜像哈希或旧证据。旧准入工具仍默认 MAX=20，新工具显式检查 MAX=OFF；6 项主机准入回归通过。实测证据：safety_backups/protected-closed-loop-20261014/latest-count-only-trial-1792054959589196800.json。

## 同日完整链路短测：零点通过，原 START 后超速锁定，整体验收失败

用户确认电机空载固定、12 V 开启且无报警、限流 0.5 A、可立即断电后，仅复位现有已确认 B549 一次，不重新刷写、不提交待试邮箱。离线回归 59 项通过；通过零点和三次输出关闭的健康快照后，调用原 motor_motion_smoke.py，经原 START／旧拧紧状态机做一次 20 rpm、最多 0.4 秒短测。不是 MOTOR TEST SPEED 旁路，不是带负载完整拧紧验收。

| 项目 | 本次实测 | 结论 |
| --- | --- | --- |
| 启动零点 | 4000 对，U0=1564、V0=1561，名义中点 1561；OUTLIERS=32、MAX=OFF、FLAGS=0 | 本次通过，累计 20 点限制确已取消；不代表重复启动稳定性已解决 |
| 保护计算统计 | WORK=84862、MAX_US=49、LATE=0 | 此观察窗口该计时口径未超过 50 µs，不等于形式化 WCET 或全采样时序验收 |
| ADC 包装层 | MAX_CYC=8392（170 MHz 下约 49.36 µs）、MISS=0、PF=0、LATE=5229 | 此处 LATE 比较 IRQ 耗时与距定时器周期边界的剩余 ticks，与上一行口径不同；不能声称所有迟到计数为零 |
| 原 START | 请求 7826 已入队；位置 0.02°→8.41°，变化约 8.39° | 编码器观测到运动，但未完成稳定闭环或拧紧工艺 |
| 停机 | 板端会话 US=28879；首个主机回读约 70.4 ms 时已故障，CTRL=60.7 rpm | 实际会话约 28.879 ms，不能把主机轮询时间当精确跳闸时刻 |
| 后台原码双缓冲 | DONE=421、DROP_B=4、DROP_S=1024、FREE_B=1860 | 存在诊断数据丢块，不能宣称并发无丢失验收通过 |

故障 FLAGS=1056=0x420，按 protected_closed_loop.h 解码为 CL_OVERSPEED（1024）与 CL_BAD_ENCODER（32）。运行中速度绝对值超过 60 rpm 会置超速位，记录 60.7 rpm 与此相符；本次不是因零点累计异常数量或已证实的 4 A 越界而停机。

编码器位不能直接解释为 SPI DMA 再次超时：本轮 READS=4081，FAIL/TIMEOUT/IO/SCHED/STALE 均为 0，无有效 DMA 子故障快照。源码的 ProtectedLoop_TaskService 在已有 foc_fault 时也会调用 EmergencyOff(CL_BAD_ENCODER)，且 FOC_EncoderSpeedUpdate 会在既有故障后清 encoder_valid，因此它可能是超速停机后的连带标志。现有快照未分别保存每一标志的首次时间，不能严格证明两位的先后顺序，也不能确定超速的物理根因。下一步应离线检查启动速度 PI／积分交接、加速度、电角度与反馈极性，再决定定向采证；不能单纯调高超速门槛当作修复。

STOP 已收到，SD/MOE/CCER 均为 0。原烟测脚本还要求 CTRL<2 rpm 才承认停止；故障后 CTRL 一直显示最后的 60.7 rpm，故输出 STOP/IDLE unverified。该提示表示其速度停止条件未得到证实，不是最终输出仍开启的证据，也不能仅凭此断言转子已静止。独立 ANALOG SAFE 回执为 LATCHED=1、SD=0、MOE=0、FOC=0；随后 SWD 再次关闭 SD/MOE/CCER/CEN 并暂停 MCU，最终输出关闭检查通过。

所有临时 RAM 配方参数恢复并回读，未执行 SAVE。完整 Flash 与测试前逐字节一致，仍为确认 B、无待试槽、代次 549，A 回退及私有配置未变。没有自动重试，没有解除保护。已通知用户关闭驱动板 12 V，后续仅分析保存数据；尚未收到本轮关电确认，不将 MCU 输出关闭等同于驱动板断电。

本轮结论：零点与前置计算门槛通过，确实进入原 START 控制链，但运动阶段故障，整体验收失败；不能宣称稳定转速、完整拧紧或实际扭矩精度通过。证据：safety_backups/protected-closed-loop-20261014/latest-count-only-trial-1792055325392397800.json。
