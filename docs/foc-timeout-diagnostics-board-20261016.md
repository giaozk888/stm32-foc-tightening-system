# TIMEOUT 诊断版上板记录（2026-10-16）

本轮范围：功率硬关闭、U/V/W 动力线断开，只验证 ADC/FOC 计算、超时子原因和首次故障快照；不发送 START，不做电机闭环验收。

## 暂存阶段

用户确认驱动板 12 V 已关闭，沿用本轮约定的 MCU 供电、动力线断开及 IU/IV 接线。ST-Link 为 NUCLEO-G474RE 的既有探针，COM5；只读连接测得 MCU 供电 3.29 V、VTOR 指向 B，SD=0、MOE=0、CCER=0。

新计算版 A：

- `foc2_app_a/build/FastCurrentRejectComputeOnly/foc2.bin`，227476 B。
- SHA-256：`97820d106378bdb4479b58dbded7324fc670fbf3b141a1db35932801e9d62210`。
- 匹配 ELF SHA-256：`65579dee7dfee9cfba0b3a04e00905bc2da9e4e2a53059afd2287f7ec25c3790`。
- 快照从该 ELF 定位，大小 204 B，不复用旧版硬编码 RAM 布局。

新验收入口 `tools/timeout_diagnostics_board_test.py` 的 4 项离线测试通过：镜像/邮箱身份、快照字段布局、命令禁用范围及暂存不激活检查。未修改固件算法、保护阈值或超时常量。

首次在受限环境读取历史私有回退备份被拒绝，尚未连接硬件或编程。经权限审核后按原路径执行，没有更改备份权限或绕过逐字节检查。

暂存收据：`safety_backups/protected-closed-loop-20261014/timeout-diag-stage-1792159197184877400.json`。

已验证板上完整 Flash 与上一份 B 回退收据逐字节相符，再仅擦写 A 镜像覆盖的页面并完整回读。B 镜像、bootloader、参数及其他槽外字节均未改变；启动元数据仍为 generation 585、confirmed B、pending NONE、attempts 0。CPU 停在 bootloader，SD/PWM/定时器关闭，尚未提交 A 试运行。

复用的历史底层脚本有固定提示文字 `B576` / `deferred shadow`，不代表实际版本；本记录以新入口锁定的镜像哈希、元数据和逐字节收据为准。

## 尚未完成

等待人工开启驱动板 12 V、确认无报警，继续保持限流 0.5 A、U/V/W 动力线断开。之后只提交一次 A 槽计算试运行，保存首次 fault 日志与 RAM 快照，或观察 30 秒。当前没有新的 FOC 耗时、TIMEOUT 子原因或运行通过结论。

## 2026-10-17 启动前检查被拦下

用户回复开启 12 V 后执行一次验收入口。收据：`safety_backups/protected-closed-loop-20261014/timeout-diag-trial-1792198987135310200.json`。

第一项门禁返回 `CPU not already halted`，在完整比较、邮箱写入和复位命令之前停止。后续收尾确认实际 PC 为 `0x08056392`（B 槽），关闭 SD/PWM 并停住 MCU。完整 Flash 仍与已暂存镜像相符，generation 585、confirmed B、pending NONE、attempts 0 未变。没有提交 A 试运行，没有 START，也没有自动重试。

该收据继承的 `trial_requests=1` 是进入函数时预置的计划次数，**不是实际提交成功次数**；本次 `activation_submitted` 缺失，门禁发生在写邮箱之前，实际提交为 0。

发现并修正了验收工具的 RAM 归属检查：此前仅检查 A 镜像已暂存，就误用 A 的 ELF 解码仍在 B 中运行的 RAM。上述收据中的 `fault_snapshot` 全部作废，不能当作 ADC、FOC 或故障证据（其 valid 也为 0）。新入口要求试运行实际已提交，且与 RAM 同一停机会话读取的 VTOR 为 A，才允许按新 ELF 解码；未发布的 valid=0 也不展示其余字段。新增归属回归测试后共 5 项通过。

结论：本次是启动前状态不匹配，不是新版 FOC 算法失败或 TIMEOUT。尚未获得新版板端耗时或有效 fault snapshot。先关闭驱动板 12 V；后续需要重新核验并准备 bootloader 停机状态，不能直接跳过门禁。

## 2026-10-17 重新准备启动状态

用户确认 12 V 已关闭后，执行新增的 `--prepare-from-stage`。先完整比较板上 Flash 和原暂存收据，再复位停在 bootloader，清除陈旧 RAM 请求的有效标记，锁定 SD/PWM 和定时器；没有写 Flash、提交试运行或运行应用。前后完整 Flash 字节相等，启动元数据仍为 confirmed B / generation 585 / pending NONE / attempts 0。

收据：`safety_backups/protected-closed-loop-20261014/timeout-diag-prepare-1792199397739266800.json`。工具离线回归增至 6 项，包含准备流程没有编程/运行/激活命令的检查。

当前等待只开启驱动板 12 V（不重新插拔 MCU/ST-Link 或按复位），保持动力线断开，再继续原 A 计算版的单次试运行；A 镜像不需要重复刷写。

## 2026-10-17 有效 A 试运行：首次原因已定位

收据：`safety_backups/protected-closed-loop-20261014/timeout-diag-trial-1792199446456485400.json`。A 槽确已启动，串口身份 `FAST_CURRENT_REJECT HARD_OFF=1 METHOD=TWO_SAMPLE`；保存 SRAM 的同一停机会话读到 VTOR=`0x08008000`，新 ELF 与板上 A 镜像逐字节匹配。首次 RAM snapshot valid=1，UART 完整打印至 `END CPU_HZ=170000000`，print index=52。没有 START，功率输出始终关闭。

**验收拆分：诊断捕获成功；30 秒稳定计算未通过。** 故障在应用 tick 2442 ms 捕获，未完成试运行所需的 5 秒连续健康确认。没有人为停止 ADC 注入超时。本轮没有修改固件算法、时限或保护配置。

### 首次故障及采样时间线

- domain=2（独立保护），fault reason=6（FOC_FP_TIMEOUT），timeout reason=3（FOC_TO_CURRENT_CONFIRM / `CUR_CONFIRM`）。
- pending 起点/reference：2449527 µs。
- 保护层上一个已接收物理采样：2449577 µs，即起点后 50 µs。
- 故障时刻：2449630 µs，pending elapsed=103 µs，大于原 confirm deadline=100 µs。
- 当时 pending=1、misses=1：此前已有一个正常采样，但还没凑齐清除 pending 所需的两个正常采样。
- 距上一个保护层样本仅 53 µs，因此本次不是 sample stream 断流超时，也不是未产生首样本。
- 故障前抓到的当前原码为 U=1570、V=1565，运行零点 U0=1563、V0=1560。它不是最早建立 pending 的原码，不能据此反推出首个越界的幅度/通道。

源码 `FocFp_Poll` 先判断 pending 超时，`FocFp_PushRawSafety` 随后才处理本次原码并累计正常 misses，满两个清除 pending。20 kHz 下，单次越界后的两个正常样本名义上恰好需要 100 µs；本次多 3 µs 就会先触发超时，而不是接纳第二个正常样本后清除。

离线用真实 `FocFp_PushRawSafety` 复现：同一初始 pending 状态，+50 µs 收到第一个正常样本；第二个正常样本在 +100 µs 时清除，在 +103 µs 时得到相同 CUR_CONFIRM / pending=1 / misses=1 / last=start+50。测试中的首个越界幅度为合成输入，**不是实机抓到的首个异常值**。新增回放在 -Os/-O2 下通过，新诊断 5 项 unittest 仍通过。

因此已确定直接触发条件及其“确认清除需要两个周期、时间预算恰好两个周期”的边界冲突；尚未证明首个越界样本的物理来源，也没有证明多出的 3 µs 一定来自某个中断。不能据此宣称实际没有过流，或直接关闭/放宽保护。

### 计算与反馈统计（截至首次故障）

| 路径 | 最大 cycles | 170 MHz 换算 |
| --- | ---: | ---: |
| normal / 全路径最大 | 7078 | 41.635 µs |
| suspect | 3321 | 19.535 µs |
| unresolved | 3313 | 19.488 µs |

FOC cycle deadline miss=0。ADC timing 另有 BOTTOM_LATE=593 / HW_VERIFIED=0，因此不能把“本次已执行计算低于 50 µs”说成“全部 PWM 提交时序或带电闭环通过”。

有效判别统计：samples=22760、suspect=143、isolated spike=132、transition=8、unresolved=4、最长连续 unresolved=1、measurement fault=0；hold_total=147（143+4）。累计 hold 占验证样本约 6.46‰，仅为本批累计比例；snapshot 的最近窗口 hold_ms=0 表示尚无完整窗口，hold_ppt=0 不是“零 hold”。

零点：运行零点 STATE=3 / REASON=0 / N=4000 / U0=1563 / V0=1560；未筛选原码资格另报 RAW_STATE=4 / RAW_REASON=2，二者不能混称全通过。故障时 speed command=0、IqRef=0、Iq≈−0.0703 A、Id≈−0.0255 A；未启动拧紧状态机。编码器 valid=1/errors=0。任务栈观测 FREE_B=1896；这不是完整系统栈峰值验收。

### 测试结束状态

SD/PWM/定时器已关闭，MCU 已停住；bootloader、两槽镜像及私有区与试运行前逐字节相同，只有既有 bootloader 的试运行元数据更新：generation=587、confirmed B、pending A、attempts=1。**尚未恢复 B 启动选择**，不能宣称已回退。

已请求人工关闭 12 V。关闭后只通过既有恢复流程选择原确认 B，并停在入口；不再试运行 A。完整 UART、RAM 和首次故障已保存，不需要复位重采来确认本次 CUR_CONFIRM。
