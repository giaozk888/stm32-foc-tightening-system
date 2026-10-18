# 分段耗时与 PWM margin 上板记录（2026-10-17）

## 结论

本轮功率硬关闭测试 **未通过**：外层 normal ADC/FOC 最大 10103 cycles（59.43 µs），发生 1 次 50 µs deadline miss，按现有保护停止。不是 CUR_CONFIRM timeout；本轮 CUR_CONFIRM 为 1 enter / 1 clear / 0 fault。

采到 3727 帧有效 normal 分段数据，但未完成计划的 30 秒验收，也未完成应用健康确认。没有 START、没有电机运行、没有自动重试。

分段计时自身存在边界外开销，因此尚不能用本轮数据唯一解释原生产版本为什么从约 19.64 µs 增长到 42.06 µs。PWM 只获得功率关闭路径的假设提交点，实际 CCR 提交余量仍未测，不能宣称 warning 是误报警或 PWM 已通过。

## 1. 分段结果

时钟换算为 170 MHz。wall 包含抢占；CPU 是同区间 wall 减去已测 IRQ body 的并集，仍包含插桩和未被 hook 覆盖的异常进入/退出等成本。

| 阶段 | wall max cycles / µs | CPU max cycles / µs |
| --- | ---: | ---: |
| ADC read / 入口计时 | 1430 / 8.41 | 776 / 4.56 |
| 原码诊断 | 1065 / 6.26 | 482 / 2.84 |
| current validation | 1966 / 11.56 | 1383 / 8.14 |
| Clarke / Park | 986 / 5.80 | 403 / 2.37 |
| 电流 PI / 限幅 | 922 / 5.42 | 339 / 1.99 |
| inverse Park | 846 / 4.98 | 263 / 1.55 |
| SVPWM | 930 / 5.47 | 347 / 2.04 |
| duty dispatch（硬关闭分支） | 1188 / 6.99 | 605 / 3.56 |
| 其他诊断 | 1424 / 8.38 | 841 / 4.95 |

表中是各阶段独立峰值，可能来自不同帧，**不能相加**；duty dispatch 也不是实际 CCR 写入耗时。ADC 项包括入口和计时操作，不是仅两次 JDR 读取。

分段 normal total max 为 5677 cycles / **33.39 µs**；normal CPU max 为 4440 cycles / **26.12 µs**。同一个最坏分段帧的 wall 数组为：

```text
ADC  RAW  VALIDATE  PARK  PI  INV  SVPWM  DUTY  OTHER
1430 262  1938      278   214 138  222    480   715
```

该帧 IRQ 并集为 1237 cycles / 7.28 µs，其中 ADC 段 654、validation 段 583；5677 - 1237 = 4440。这是同帧可作的减法。

外层 normal max 为 10103 cycles / **59.43 µs**。外层与分段峰值不是已配对的同一帧，不能把二者相减当作精确的尾部开销。

## 2. 已定位的计时边界问题

对匹配 ELF 的源码/反汇编检查发现：

- `FocProfile_Begin()` 在分段开始时间戳之前清零 72 字节 frame；编译结果调用 `__memset_veneer`。
- `FocProfile_End()` 先记最后一个阶段，再执行统计归并：两个 9 项循环；刷新最坏帧时复制 72 字节，编译结果调用 `__memcpy_veneer`。
- 这些清零、归并、复制位于分段 total 边界之外，却位于 `ProtectedLoop_AdcProfileEnd()` 使用的既有外层 deadline 边界之内。
- 外层先读取 CYCCNT 得到耗时，再触发 `EmergencyOff(CL_COMPUTE_LATE)`。因此触发后故障快照本身不能解释已经记录的 10103 cycles。

这证明本次诊断插桩会扰动被测路径，也证明只看 33.39 µs 会漏计部分 ISR 工作；但尚未测到同帧 begin/reducer/tail 各自耗时，不能把全部差额归因于 memset、memcpy 或某一个 IRQ。

本轮最重的单个已分段 CPU 项是 validation（峰值 8.14 µs），数学变换/PI/SVPWM 不是目前唯一或已证实的主要回归来源。原 19.64、42.06 与本次 59.43 µs 需按同一镜像边界、插桩配置和抢占窗口对照，不能直接作算法性能排名。

下一步应先降低诊断归并成本，并记录同帧外层、分段、归并尾部和抢占，之后再决定移出哪些非必要统计。本轮仅上板取证，不额外修改固件或继续刷写。

## 3. PWM warning 取证

捕获的 TIM1 几何参数：center-aligned CMS=1、ARR=4249、PSC=0、RCR=0，CH1/2/3 PWM1，CH4 PWM2，TRGO2=OC4REF，ADC injected rising trigger。RCR=0 时 top 和 bottom 都有自然 update event；CMS=1 的 CC 中断方向选择不等于只在 bottom 更新。

现有提交逻辑目标是在下数 bottom 前完成 CCR preload 写入；不能用整个 50 µs 周期作为可写余量。UDIS 包围的 CCR 事务也不等于硬件已锁存的证据。

本轮 **实际 CCR writes = 0**，实际 min margin、实际写入耗时均为未测，不是 0 µs。实际 late count=0 也不代表通过。

功率关闭路径的假设 duty 点有 3727 个有效观察、1 个无效观察：

- 相对 ISR 入口所指向的同一个 bottom，最小有符号余量为 **-3411 ticks / -20.06 µs**。
- 最坏配对入口：DWT=254965712，CNT=437，下数。
- 对应假设提交点：DWT=254969560，CNT=3388，上数。
- 入口到假设提交点经过 3848 cycles / 22.64 µs，而入口距该 bottom 仅约 2.57 µs，已经跨过该 bottom。
- 单次 timer/DWT 观察跨度为 23 cycles，远小于上述负余量。

因此不能把错过本轮 bottom 后的“下一次 bottom”重新折成正数，来宣称本轮及时。但这仍是**假设提交点**，不是带实际 CCR 写入的控制路径。入口为何已经接近 bottom（触发相位、ADC 转换/IRQ 延迟、实际触发 CCR 等）仍需同时间线证据。

旧粗粒度统计 `BOTTOM_LATE=3728`，`HW_VERIFIED=0`。目前不能完成用户要求的 A/B 最终分类：有真实的 entry-anchored 预算不足迹象，但没有实际 CCR latch/写入证据，不能认定已发生真实晚写，也不能认定只是误报警。warning 保留。

## 4. 未改动及离线验证

本次上板新增测试编排/解码工具，不改 FOC、PI、SVPWM、discriminator、阈值、reference rebase、CUR_CONFIRM（2 个 good、最多 4 cycles）、硬过流保护、PWM/ADC 频率或其他业务算法。ISR 无 printf/UART。

本轮重新运行以下离线测试，共 **16 项通过**：

```text
python -m unittest discover -s tests -p test_fast_path_profile_board_test.py -v
  7 tests OK
python -m unittest discover -s tests -p test_foc_path_profile.py -v
  9 tests OK
```

其中覆盖镜像/ELF 身份、匹配 RAM 解码、禁止启动、断电阶段门禁、CUR_CONFIRM 不变、生产控制内核不变及构建告警检查。先前完整编译与 90 项离线回归见前置报告；离线通过不抵消本次实机 deadline 失败。

## 5. 镜像、收据及最终状态

实际测试 A BIN：229220 字节。

```text
BIN SHA256 69f98bc70f9216ed33d9e16af9cc3b9e06b65ac363a0cbc84d57727e5ef610e7
ELF SHA256 3e12f18329d567ea688e5d3577ced86a93fa1917bd8d168b69bec98fe147b774
```

完整收据保留本地，不上传私有 Flash/RAM：

- 暂存：`safety_backups/protected-closed-loop-20261014/fast-path-profile-stage-1792204072052311200.json`，PASS。
- 单次试运行：`safety_backups/protected-closed-loop-20261014/fast-path-profile-trial-1792204610080408100.json`，FAIL；快照 VTOR=0x08008000，与匹配 A ELF/Flash 解码。
- 恢复：`safety_backups/protected-closed-loop-20261014/fast-path-profile-restore-1792204669557311400.json`，PASS。

用户确认 12 V 已关闭后，通过既有 bootloader 恢复原已确认 B 启动选择：metadata generation=595、confirmed B、pending=0、attempts=0。MCU 停在 B 入口（VTOR=0x08040000），SD=0、BDTR=0、CCER=0、TIM1 停止。恢复前后应用和非 metadata 私有区逐字节未变，未重刷 B 或 bootloader，未强制确认。诊断 A 留在非活动槽，不再 pending。

本轮到此停止。耗时归因及实际 PWM warning 分类尚未完整闭合，不作为闭环电机验收通过。
