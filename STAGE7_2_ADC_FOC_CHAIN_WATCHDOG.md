# Stage 7.2 — ADC/FOC 运行链停滞软件看门狗

## 做了什么

Stage 7.1 只在 `START` 前检查 ADC/FOC 计数是否仍在推进。Stage 7.2 在既有 1 kHz `MotorControlTask` 中复用相同的计数时间戳：运行零点校准完成后，如果 ADC 注入链或 FOC 控制链连续超过 50 ms 不推进，就锁存 `foc_fault`，拉低 `CTRL_SD` 禁用驱动桥。随后既有故障分支将电流/速度命令清零、电机模式切回 IDLE，`TighteningTask` 进入 FAULT，禁止自动重启。

| `STATUS REASON` | 含义 |
|---:|---|
| 5 | ADC 注入计数停滞 |
| 6 | FOC 控制计数停滞 |

先查 ADC，再查 FOC；已有 `adc_fault`/`foc_fault` 时不覆盖原故障原因。该检测只由 FreeRTOS 任务执行；若 CPU/调度器整体停止，不能代替独立硬件保护或独立看门狗。没有改动 20 kHz ISR、PWM 占空比算法、引脚、Flash 布局或 IAP 状态机。

## 构建与板上验证（2026-09-24）

| 槽 | FLASH | RAM | BIN CRC32 | IAP 结果 |
|---|---:|---:|---|---|
| A | 218,228 / 229,376 B（95.14%） | 64,864 / 131,008 B | `0x72BFECE3` | 全包 218,228 B，重传 0，`CURRENT=A CONFIRMED=A PENDING=- GEN=200` |
| B | 217,916 / 229,376 B（95.00%） | 64,848 / 131,008 B | `0xC131339F` | 全包 217,916 B，重传 0，`CURRENT=B CONFIRMED=B PENDING=- GEN=203` |

A/B 编译通过；存在原有的 unused-variable / unused-function 警告，没有新增编译错误。当前运行 B。A、B 的 `SELFTEST STATUS` 均为 `READY=1 MASK=0x000`，`STATUS` 为 `MODE=IDLE FLT=0 REASON=0`；两次查询间 ADC/FOC 计数各增长约 4500～4700。A/B 分别静置约 20 s 后复测，无误触发。B 上 Modbus 异步回归通过：ID 247 超时有界，随后 ID 255 可读；25 次连续只读均为继电器位图 `0x0000`，CRC 错误 0。没有发送 `START`，没有动作继电器。

B 升级复位后的第一次 COM5 查询曾超时，第二次正常且 B 已自动确认；类似现象在之前升级中发生过，启动窗口原因尚未定位。它不是本次看门狗故障的证据。

## 仍需验证的边界

目前只验证了正常运行**不误报**，没有人为停 ADC/FOC 链，因此没有实测故障码 5/6 的触发延时及 `CTRL_SD` 的实测关断波形。后续应在无负载、限流电源和示波器/逻辑分析仪监测 `CTRL_SD` 的条件下，设计可恢复的故障注入，且保留已确认槽用于回退。母线欠压、过温、驱动器告警和独立急停仍未实现；`READY=1` 不能代表这些硬件保护已具备。Flash 使用率约 95%，继续扩展须留意槽容量。

复测命令：

```powershell
pwsh -NoProfile -File .\tools\selftest_status_smoke.ps1 -Port COM5 -ExpectedSlot B
pwsh -NoProfile -File .\tools\modbus_async_smoke.ps1 -Port COM5 -ExpectedSlot B
```
