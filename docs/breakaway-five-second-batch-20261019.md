# Breakaway 自动逐档批测：每档 5 秒

**最新继续结果：+0.12、+0.15、+0.18 A 各约 5 秒已执行；准备 +0.20 A 时，尚未发 Iq 命令，板端发生 CURRENT_INVALID（连续 3 次 unresolved），故中止。** 见[升流继续记录](breakaway-five-second-continuation-20261019.md)。本次未继续负向、未刷固件或改保护，输出已关闭、MCU 停住。

**最新电机实测：仅第一档 +0.10 A 已运行约 5 秒并正常停止；随后静止检查因位置变化约 0.11°中止整批，未继续升流。** 未报板端保护 fault，FOC max=28.81 us、deadline/CCR late=0；位移记录无持续起转证据。见[首档实验记录](breakaway-five-second-first-motion-20261019.md)。输出已关闭、MCU 停住。

此前启动预检：A696 完成正常健康确认，零点与功率关闭 FOC 计算通过（27.18 µs、deadline/CCR late=0），该预检没有启动电机。见[计算验证记录](breakaway-five-second-compute-verification-20261019.md)。启动选择为 A，B 固件回退完整保留。

此前刷写阶段：用户关闭 12 V 后，A 恢复写入、完整回读及独立复核通过，当时尚未激活且 B693/metadata 未变。随后才执行上述 A696 计算验证。见[恢复记录](breakaway-five-second-stage-recovery-20261019.md)；[首次写入失败记录](breakaway-five-second-stage-failure-20261019.md)保留。下文“尚未刷写”描述的是先前软件准备阶段，不是最新板端状态。

本页取代上一版“每档 200 ms、必须人工逐条启动”的测试安排；旧镜像、旧记录和旧报告保留，不重标为新实验。用户已改为授权自动顺序批测。**本次完成软件准备，尚未刷写、复位或运行电机，没有新的 breakaway 实测值。**

## 执行方式

独立诊断预设 `BreakawayFiveSecondDiagnostic`：`FOC_BREAKAWAY_CURRENT_TEST=ON`、`FOC_BREAKAWAY_FIVE_SECOND=ON`。正式构建默认关闭。

主机依次执行：

- 正向：+0.10、+0.12、+0.15、+0.18、+0.20 A，每档 5 秒。
- 反向：−0.10、−0.12、−0.15、−0.18、−0.20 A，每档 5 秒。
- ±0.25 A 仍为 `LIMIT_BLOCKED`；没有把现有 ±0.20 A direct-Iq 限幅提高。

这不是带电平滑斜坡。每档仍由板端单次准入、独立 TIM7/ADC 租约结束；主机负责排序。到 5 秒后回 0 A/IDLE，SD/MOE/CCER 关闭。每档输出关闭后检查至少 1 秒、至少 10 次的静止证据：CTRL/DET 各不超过 1 rpm，位置范围不超过 0.10°。随后保存同次 SRAM/完整 Flash、校验和解码，只有安全、身份、记录及 Iq 跟踪检查通过才复位、重新校准并进入下一档。

期望的 `NO_MOTION` / `STICK_SLIP` 可以继续下一档；错误方向、保护故障、FOC/CCR 时序失败、参考值不匹配、Iq 跟踪不合格、记录不足、未知 ACK 或未能证明停机均中止整批。**不自动重试、不清除故障后继续、不热反转**。固定 Iq 没有速度闭环，可能逐渐加速；现有超速保护不改，触发后本批就结束，不保证每档一定跑满 5 秒。

一次批次 10 档，最多驱动 50 秒；加上逐档校准、5 秒时序报告、停稳和保存证据，实际总耗时更长。本工具不会自动追加三轮，也不会把每档一次的观察当作已经确认的最小起转电流。

## 5 秒记录

原 32×124 B + terminal 的 `cl_startup` ABI 保留；关键 dq/原码/PWM/encoder 状态帧每 200 ms 一次，约 25 帧覆盖 0–4.8 秒，停机 terminal 应在 5.000–5.050 秒。不会只保存前 200 ms 就宣称观察了全程。

另加 76 B `breakaway_motion`：在既有新鲜编码器外环任务中累计原码变化，记录净位移、绝对路程、正负最大偏移、正反向/静止次数、最长静止时间、末 1/3 窗口路程、采集覆盖/最大间隔以及参考值/门状态/编码器异常计数。编码器 wrap 按既有方向 −1 展开，不改变控制方向。该统计不放进 20 kHz ADC ISR。

离线分类使用任务级累计路程，而不是仅用 200 ms 帧间差，避免把帧间往返漏掉。要求至少 4000 个新鲜外环观察、覆盖至少 4.8 秒、最大间隔不超过 20 ms。dq 电流均值仍来自降采样关键帧，不能声称是全部 100000 对 ADC 的均值；也不能检测两次外环观察之间全部运动。`PWM applied` 仍只是 preload 寄存器读回。

捕获标记：5 秒为 `0x42574135`，200 ms 旧模式为 `0x42574159`。匹配 ELF/BIN/完整 Flash/SRAM 后才解码，两个时长的 breakaway 捕获禁止混合汇总。新模式增加了全程运动证据，但仍不能单独证明真实转矩、电角度对准或真实机械摩擦来源。

## 工具与板端边界

`tools/breakaway_current_batch.py` 默认只输出计划，不打开串口或调试器。可执行操作明确分开：

```powershell
# 各自在 foc2_app_a / foc2_app_b 目录构建
cmake --preset BreakawayFiveSecondDiagnostic
cmake --build --preset BreakawayFiveSecondDiagnostic --parallel 6

# 离线计划，不运行电机
python tools/breakaway_current_batch.py
```

新脚本的实际刷写沿用已验证的“12 V 关闭、已停住且输出关闭的 B693 → 只写非活动 A”流程。它不会因为用户表示电源一直开启就伪造断电标志，也不把电源限流等同于母线电容已放电。`--stage-off --drive-off-fixed` 只可用于实际满足该状态时；目前未执行。带电批测是单独的 `--execute-batch <staging-receipt>`，要求现场监督准备参数 `--onsite-12v-05a-no-alarm-fixed-emergency-off`，且每一步仍做真实板端检查。

批测仅接受脚本固定的 A 镜像和 B693 基线，逐次核对全 Flash；不覆盖 B/bootloader/私有参数。首次通过原 bootloader mailbox 提交试运行、等待正常健康确认，后续只在前一档完全通过且 A 已确认后复位。没有修改 A/B 状态机；**实际运行会改变启动选择，批末停住 A，B 启动选择的恢复并未自动执行**。软件本轮没有实际改变板端启动选择。

协议保留每个 boot 一次准入；自动化仅存在于主机编排。每次 pulse 意图在发送前落盘，ACK 不明不得重发，失败也保存子收据。整批汇总不得把复制同一份捕获算作多次试验，`BREAKAWAY_IQ_POS/NEG` 仍需既有的 3 次重复及完整低档数据；单批只给首次观察。

## 构建与回归

| 构建 | Flash | RAM（链接统计） |
|---|---:|---:|
| A 5 秒诊断 | 228972 B | 130176 B |
| B 5 秒诊断 | 228060 B | 130160 B |
| A 正式完整状态机 | 228220 B | 130080 B |
| B 正式完整状态机 | 227204 B | 130064 B |

没有扩大分区或删保护。A 5 秒版剩 404 B Flash；RAM 链接余量不代表运行时栈/堆安全余量。初次 A 超出 492 B，最终只对新诊断采集函数及 `StartupTask` 使用 `-Os` 解决，不改变 FOC/PI/IRQ 编译选项。

镜像 SHA256：

- A BIN `6f45621b2c76b1b7e66a36cb0041cd2fa58ab985d2cb7614ccf8e25756f8fd95`
- A ELF `7ed371dc326690658fcb462d5e458953884f85f8a6cbaea6c413b7da6f91f157`
- B BIN `debd1f2660644385f577f5dba35c360d46a7a05016518502ecbfd5fd138b36b5`
- B ELF `e32e4db942b4b34a2820555eee4df9d1f2078f2f9549215c95527875ae318183`

正式 A/B BIN 与之前完全一致（A `a4848c2e…`，B `f7becb51…`）。新旧诊断的冻结 FOC/PI/保护函数比较通过，ADC timing 和 IRQ 对象逐字节一致。PI、相序、电角零点、current discriminator、CUR_CONFIRM、保护阈值、PWM pipeline 未改。

28 项 breakaway 定向测试通过，含真实 C owner 在 `-O2/-Os` 下执行：5 秒截止边界、全程记录、wrap/累计运动、所有幅值/方向准入、限幅拒绝、STOP/故障竞态、模拟匹配捕获、帧间往返识别、批次一次成功或首次失败即终止、ACK 不明不重发、失败仍停止/捕获、静止检查、默认不接硬件、不同租约不可混合。模拟捕获不是实机数据。日志：`tmp/breakaway5-tests-final.log`；另 44 项既有 torque 回归通过，日志 `tmp/breakaway5-torque-regression.log`。

全量测试 `tmp/breakaway5-all-tests.log`：1308 项、339.002 秒，1295 通过、9 失败、4 错误；13 个不通过方法与上一轮 `tmp/breakaway-all-tests.log` 逐名完全相同，新增/消失均为 0。全量发现之后补充的失败清理回归已包含在最终 28 项定向重跑中。未把已存在的不通过项隐瞒为全绿。构建保留旧 unused/RWX 告警，没有新增告警种类。**尚无新版板端 FOC max/CCR margin 实测，不以旧版耗时替代。**
