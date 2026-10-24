# 600 rpm 编码器 control-stale：离线根因与候选修复

## 结论和范围

上次退出不是已证明的 RTOS 任务饥饿或 SPI 事务太慢，而是发现了一个可重现的配置冲突：高转速诊断允许命令 800 rpm、保护上限 1000 rpm，但瞬时速度合理性检查仍沿用 600 rpm。

新候选 `MechanicalHighSpeedEncoderFixCandidate` 只为这一独立高转速 A 模式启用 `FOC_ENCODER_CONTROL_ADMISSION_FIX`。**未刷板、未启动、未进行任何 SWD/串口操作**；原物理 B 和启动选择仍维持上次恢复状态。

## 原始证据

同一失败 receipt：`tmp/mechanical-ident-run-1792671182051071100.json`。

原 BIN SHA256 `442cef6ca8476b15e99e373b01394f881672e89fb5a2ff5a176323e0e3fcec1e`、ELF `22cf6efdeb090b2358c2f6d29942b68cd10601c87455160ead4dbbc1eef65490` 与 receipt 一致。测试再次逐字节核验 RAM SHA，再用同会话 ELF 解析以下值：

| 字段 | 值 |
|---|---:|
| 目标速度 | 600 rpm |
| 当时 S-curve 命令 | 585.90393 rpm |
| filtered speed | 580.64331 rpm |
| `encoder_prev_raw`（最后接受的原始角度） | 2508 |
| 最近成功 DMA `raw` | 2172 |
| `encoder_speed_dt_accum_s` | 0.002 s |
| `encoder_rpm_instant` | 615.234375 rpm |
| `encoder_speed_glitch_count` | 8 |
| `encoder_speed_glitch_streak` | 2 |
| 原 `SPEED_INSTANT_PLAUSIBLE_RPM` | 600 rpm |
| `control_due_us` | 10995976 |
| first-fault `now_us` | 10995977 |

现有方向 ENCODER_DIRECTION=−1，按实际 raw 和累计 dt：

`rpm = −(2172 − 2508) * 60 / (16384 * 0.002) = 615.234375`

该值高于旧 600 rpm 合理性门限，但低于用户已经批准的 1000 rpm 运行边界；接近目标速度时，正常运动加量化/波动即可跨过 600 rpm。不能把 600 rpm 当成 800 rpm 诊断中的“物理不可能速度”。

成功 DMA 样本耗时 150 µs；transaction timeout=0、DMA error=0、schedule miss=0，而 control_stale=1、FLAGS=32。被拒绝分支不发布角度、不更新 `encoder_prev_raw`、不清累计 dt，也不会走到末尾 `AS5047P_DmaAcknowledgeControl()`；连续两次拒绝后，2.5 ms 看门狗先于第三次异常检查到期。

另一个语义错误：该拒绝分支原来返回 HAL_OK，`ProtectedLoop_TaskService` 因而更新 `cl_session.outer_us` 和 `cl_outer_n`。这解释了“外层看似刚成功更新，但编码器确认看门狗到期”的不一致。**上次所谓‘控制侧未按时确认’是保护分类，不能再直接推断为控制任务没有被调度。**

完整 IRQ/任务历史仍未记录，因此不声称已经排除所有时序问题；但上述门限冲突及假成功返回值可以用当前证据和实际 C 分支离线重现。

## 最小修复

1. 仅新候选使用 `SPEED_INSTANT_PLAUSIBLE_RPM = FOC_RUNDOWN240_TRIP_RPM`，即已经批准的 1000 rpm；不增加一个超过运行保护的新门限。历史普通 A/B、原高转速诊断预设未开启该开关时仍为 600 rpm。
2. 仅新候选被拒绝但尚未达到三次故障的样本返回 **HAL_BUSY**，不再伪装 HAL_OK。原外层的 BUSY 路径已经不会更新 outer heartbeat 或继续处理 admission；没有添加喂狗路径。
3. 三次真正异常仍 HAL_ERROR 并关闭输出；连续拒绝、重复数据或没有新样本仍无法延长控制 watchdog。接受有效数据仍必须通过原 sample age、dt、transaction/status 检查及末尾实际 ACK 的到期检查。
4. `MOTOR TEST MECH LIMITS` 增加仅新构建字段 `PLAUSIBLE_RPM=1000 REJECT_BUSY=1`，后续板测应核验它们；没有新增启动或使能路径。

这包含**高转速诊断数据准入范围从 600 调整到原批准的 1000 rpm**，不能笼统声称“一切阈值都没变”。独立超速仍为原 1000 rpm、连续异常仍为 3；没有提高任何电流、电压或时间保护上限。

## 明确保持不变

- SPI transaction 200 µs、schedule-late 200 µs、采集周期 1000 µs、sample-age 1500 µs、control watchdog 2500 µs。
- 20 kHz FOC、current/speed PI、S-curve、Ka=0.000046875 A/(rpm/s)、摩擦/BEMF、相序/电角度/编码器方向。
- one-cycle PWM pipeline、CCR 提交、CUR_CONFIRM、TWO_SAMPLE / CURRENT_INVALID、零点校准、硬过流。
- TIM2/RX DMA/TIM6/ADC/TIM7 IRQ 优先级和编码器驱动代码。
- 诊断 Iq ±0.50 A、电压 1.60 V、超速 1000 rpm、行程 30000°、10.5 s task closure、12 s 独立 lease。
- 原普通 A/旧诊断二进制身份、正式 B 源码及 B 实机镜像。

## 构建与回归

- 新 A `MechanicalHighSpeedEncoderFixCandidate`：Flash 208524 B，RAM 128776/131008 B，heap/stack 未缩减。
- BIN SHA256 `212ebe9c5c3a8b09a29ed3279ac9c78c100ef80276dfc75de0439c982a7eb862`。
- ELF SHA256 `dadb41e4dc5460c70bfce483b777abf7e0d85a4876ee97b059d816d247aac0e3`。
- B 在独立复核构建目录 `foc2_app_b/build/MechanicalReviewB` 编译通过，Flash 228300 B、RAM 128792 B；BIN SHA256 仍为 `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`，逐字节身份未变。这是本地构建，不是刷写或更新板上 B。
- 新旧 A 编译 warning 集合完全相同（已有 unused / RWX），无新编译错误。
- `tests/test_encoder_control_admission_fix.py`：用保存 RAM 重现 615.234375 rpm / 两次拒绝；在 −Os/−O2 下编译**实际预处理拒绝分支和原 outer service 前半段**，覆盖旧假心跳、正常 600~800 rpm、负方向对称、真正超范围拒绝、BUSY 不刷新、三次异常故障、重复/失败样本不刷新、有效恢复、真正晚到仍失败。接受发布和硬件/时钟为受控 stub，不将其冒充板测。
- 预处理逐函数核验：除明确的两处变动外 encoder-speed 函数一致；FOC/current PI、outer task、功率使能 owner、PWM、角度变换、速度命令、诊断任务完全相同。encoder/IRQ/ADC/zero/FSM/mechanical capture 对象与旧构建逐字节相同。
- 定向回归合计 **145 项通过**：encoder 系列 30（包含新增 4 项）、mechanical 系列 27、speed 系列 88。日志分别为 `tmp/encoder-control-encoder-regression.log`、`tmp/encoder-control-mechanical-regression.log`、`tmp/encoder-control-speed-regression.log`；`git diff --check` 通过。

## 板测边界

本轮没有刷板或启动授权执行。原 `tools/mechanical_high_speed_board.py` 仍固定原镜像哈希，**不会接受这个新候选**；不能直接用旧 receipt 或替换哈希绕过检查。下一次人工上板前需要为新候选做独立身份/limits 门禁和非活动 A 暂存流程，再先验证 600 rpm，保护触发不重试。

停止在：编码器准入候选离线修复完成，等待人工确认后续上板验证。
