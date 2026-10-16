# 延后采样接入保留保护的闭环候选版

## 最新上板结果：未通过计算时序验收

2026-10-16 已把本页固定哈希的候选版写入非活动 B，完整回读通过；A564、bootloader、元数据和参数在暂存阶段未变，原 B561 整片备份保留。随后在用户开启 12 V、电机动力线断开的条件下，只提交一次正常试运行，**START 次数为 0**。

| 实测项目 | 结果 |
| --- | --- |
| 筛选零点 | 通过：4000 对，U0=1561、V0=1560；范围 1555..1569 / 1555..1565 |
| 筛选修补 | 零点识别 35 个候选异常，稳健零点 FLAGS=0；不是本次停机原因 |
| 首次故障 | `CL_COMPUTE_LATE=256`；FOC 计时达到 50 µs，LATE=1，序号 29149 |
| 同一失败帧 | PAIR_US=12、MATH_US=37；WALL_CYC=8287、IRQ_CYC=3868 |
| ADC IRQ 历史最大值 | 9162 cycles / 170 MHz = 53.8941 µs；可能含故障处理，不能直接当作该失败帧的纯计算时间 |
| 双 ADC | PAIRS=29150、MISS=0、PF=0 |
| RC 更新余量 | BOTTOM_LATE=5146；READY=0、CHECK=0、FAIL=0，尚未进入电机 PWM 提交流程 |
| 编码器 DMA | FAIL/TIMEOUT/IO/SCHED/STALE 均为 0；MAX_US=38 |
| 后台统计 | DONE=109、栈余量 1864 字节；DROP_B=4 / DROP_S=1024，不是全程零丢块 |
| 最终状态 | SD/MOE/AOE/CCER/CEN 关闭，MCU 暂停；未健康确认 B、未自动重试、未启动电机 |

50 µs 保护区间、DWT 区间和整个 ADC IRQ 的边界不相同：同一失败帧的 8287 cycles 约为 48.75 µs，不与 50 µs 的微秒计时矛盾。纯 CPU 和抢占的各自历史最大值也不能直接相加。本轮 CPU_MAX_CYC=4457、PREEMPT_MAX_CYC=3948，说明需要进一步定位并压缩实际控制路径与抢占叠加；不能把问题归因为筛选电流越界，也不能通过删除截止检查宣称通过。

本次故障发生在正常健康确认的 5 秒观察窗之前，**没有完成预定 30 秒观察**。启动准入因余量告警保持关闭的行为得到观测，但真实变化占空比提交、模拟建立与电机闭环均未验收。

最终元数据为 confirmed A、pending B、attempts=1、generation=566；当前停在已锁定并暂停的 B，不是“已经回退运行 A”。保留 A564 供现有 bootloader 后续回退，本轮不再复位。最终整片回读与暂存相比，只有正常试运行元数据改变，APP 和私有区域均未变。

证据：[B 暂存回读](safety_backups/protected-closed-loop-20261014/rc-protected-stage-1792123087814274200.json)、[失败点及最终关闭证据](safety_backups/protected-closed-loop-20261014/rc-protected-trial-1792123335544055000.json)。完整 Flash 仅保存在既有受限备份目录，未输出私有内容。

验收脚本 `tools/rc_protected_board_test.py`、`tools/rc_protected_trial.py` 默认仅离线；实际运行需显式选择阶段。它们固定镜像和既有备份哈希，不提供 START、故障清除或强制确认入口。新增主机回归还覆盖真实失败记录必须被判为失败，不能误报计算／闭环通过。

本轮最后合并离线回归 **57 项全部通过**，其中包括上述失败记录的判定回归。这个离线通过不改变本轮实机时序失败的结论。对接脚本运行未修改固件源码或候选 BIN，两槽候选 SHA-256 仍为下表值。

## 现在做到哪里

已接入代码，并为 A、B 两个槽分别编译了独立候选镜像 `RcSamplingProtectedCandidate`。

它用的是：**原 START 入口和原拧紧状态机 + 最新四点趋势筛选 + RC 延后采样 + 现有保护链**。没有再写一套控制状态机，也没有改 PI、相序、编码器方向或保护阈值。

初次代码接入阶段没有操作板卡；后续本次上板结果以上节为准。**代码接入通过，不等于带电闭环验收通过。**

## 保留了哪些保护

| 项目 | 本版处理 |
| --- | --- |
| 电流反馈 | 沿用四点趋势筛选及一拍延迟，不换成未经验证的新算法 |
| 相电流过流 | 沿用 `TRIP_MA=4000`、`OC=2_OF_3` 分层判定，不是恢复成单点原码 4 A 立即停机 |
| 采样／编码器故障 | 保留配对、窗口、时钟、数据新鲜度和编码器检查 |
| 运算时限 | 保留 50 µs 计算截止和 TIM7 独立超时关断 |
| 超速／外环 | 保留 60 rpm 超速阈值、2 ms 外环新鲜度检查 |
| 试验范围 | 沿用原有 20 rpm、最多 400 ms、每次启动只允许一次的短测范围，没有扩大 |
| 故障处理 | 保留关闭 SD／PWM、首故障留证、锁定及不自动重试 |

原 `LatestOriginalStartupEvidence` 的累计零点修补次数仅统计策略也原样继承；本次没有新增关闭保护的选项。零点稳定性、连续无效反馈和保护判定仍走原路径。

## 延后采样怎么接进去

采样窗口与已测的硬关闭对照版使用同一规划器：U/V 名义低边导通后至少观察 1700 ticks（10 µs），选择顶点前最晚可用采样位置。窗口不够就拒绝，不自动缩短观察时间。

这不是“10 µs 后模拟电流一定稳定”的保证，也不是 95% 占空比已可用。低边电流检测的模拟建立、反馈方向和实际 PWM 生效时刻仍未验收。

候选版另接了两道截止检查：

1. **START 前检查历史。** 已观察至少 1000 对样本、有 DWT 耗时证据，且没有采样配对失败、窗口失败、底部余量告警或提交失败，才允许进入原启动流程。出现过的失败不会被一个清零命令抹掉。
2. **运行中提交前检查时刻。** 必须仍在本次 ADC 中断内、定时器在下数阶段、未越过本次预期底部，且还留有暂定 170 ticks（1 µs）预算。检查不通过则不写这次 CCR，立即走 `CL_COMPUTE_LATE` 锁定关断。

170 ticks 是新增的暂定软件预留，**尚未实测证明它覆盖整个 CCR 预装载事务**。提交前检查不是物理 PWM 更新成功的证明，也不覆盖模拟建立；目前仍返回 `HW_VERIFIED=0`、`QUALIFIED=0`。TIM1 实际更新边界和完整端到端延迟还要测，不能只看函数返回值。

新增只读查询：

```text
ADC COMMIT
OK ADC COMMIT RC=1 READY=... CHECK=... FAIL=... BOTTOM_LATE=... GUARD=170 HW_VERIFIED=0
```

其中 `READY` 只是上述软件时序准入结果，不是整个电机已获验收许可。完整 START 还要通过原有零点、输出、编码器、会话等检查。

## 为什么还不能写“闭环已通过”

上一轮 A564 功率硬关闭实测的 FOC 最大值是 44 µs，低于 50 µs；但到下一计数底部的粗粒度余量告警增加了 26032 次。**“一周期内算完”与“赶上要求的 PWM 更新边界”是两件事。**

新候选没有删掉这个告警。若同样的问题重现，会拒绝启动，或在运行中拒绝提交并关断。此前的超速根因也没有因这次代码接入而被证明解决；不能据此直接宣称反馈极性、相序或模拟电流正确。

上一轮硬关闭证据见 [延后采样实测记录](FOC_RC_SAMPLING_CANDIDATE_20261015.md)。后续候选试运行的失败证据见本页首节，不追加电机／功率桥启动。

## 离线验证

初次集成合并回归 **45 项全部通过**；下面的规划器／双缓冲脚本另行通过。这些离线测试没有访问串口、ST-Link 或板上 Flash；后续实际刷写和试运行是首节单独记录的操作。

- 主机执行真实时序适配器，在 `-Os`／`-O2` 下分别覆盖 14 种情形：正常提交、掩码保留、DWT 回绕，以及无 DWT、非中断、UDIS、上数、余量不足、跨周期、IRQ 已退出、定时器停止、空计划、已有告警等拒绝路径。
- 执行真实旧状态机绑定，覆盖启动拒绝、成功准入、提交失败锁定、故障后不重启，以及规划期间 STOP／独立关断的竞争；拒绝后不再发布占空比。
- A/B 头文件和真实 CMake 配置均验证混用诊断配置、缺少证据配置或缩短 RC 预算被拒绝。
- A/B 链接结果确认新检查、ADC 中断和独立关断位于 RAM 路径，实际 ADC 调用受保护 SetDuty，后者调用提交检查及紧急关断；这不是整条事务全在 RAM 的声明，原 `CommitPrepared` 仍在 Flash。
- 原状态机、ADC 时钟、快速数学、实际 A/B 电流 PI 和诊断脚本回归一并执行。
- 规划器另独立检查 1,752,355 个成功计划；双缓冲两主机线程处理 5,120,000 对样本。线程和寄存器模型验证不能代替 MCU 上板结果。

复现：

```powershell
$env:PATH='D:\software\arm\bin;D:\software\ninja;'+$env:PATH
cd 'D:\new project\foc2_app_a'
cmake --preset RcSamplingProtectedCandidate
cmake --build --preset RcSamplingProtectedCandidate -j 6
cd 'D:\new project\foc2_app_b'
cmake --preset RcSamplingProtectedCandidate
cmake --build --preset RcSamplingProtectedCandidate -j 6
cd 'D:\new project'
$env:PYTHONPATH='D:\new project\tools;D:\new project\tests'
python -m unittest test_foc_rc_protected_candidate test_foc_adc_rc_policy test_foc_adc_clock test_foc_startup_evidence test_latest_original_fsm test_foc_fast_math test_control_chain_reconnect.ReconnectAdapterTests.test_actual_ab_current_pi_uses_filtered_frame_and_original_limits test_rc_sampling_board_test test_rc_sampling_trial -q
powershell -NoProfile -ExecutionPolicy Bypass -File tests/foc_adc_window_host.ps1
```

## 候选镜像

| 槽 | BIN 字节 | 静态 RAM（含链接保留） | SHA-256 |
| --- | --- | --- | --- |
| A | 211604 | 125096 / 131008 | `ff7660fb65aef3527a3d5c81a71d11d6a13e440facd90704dfb6c3fea366fb7c` |
| B | 210724 | 125080 / 131008 | `61abcdc9ee6c92a34c4920562e8a3e6e9ac6404653e56b7466020f4257b752df` |

位置：`foc2_app_a/build/RcSamplingProtectedCandidate/foc2.bin` 与 B 槽对应目录。静态 RAM 余量约 5.9 KB，不证明运行栈余量；链接器原有 RWX LOAD 段警告仍存在。

现有硬关闭 A/B 本地镜像和旧 B561 本地电机镜像均按固定 SHA-256 回归核验，未被本次构建覆盖。候选镜像使用独立目录，不会自动替换板上固件；本次用户授权的显式暂存已将板上非活动 B561 替换为候选 B，其备份保留，A564 不变。
