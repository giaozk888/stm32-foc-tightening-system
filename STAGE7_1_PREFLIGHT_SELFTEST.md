# Stage 7.1 — 启动前自检状态与 START 双重拦截

## 现有机制与本次增量

工程原有 StartupTask 已进行 ADC 硬件校准、静态电流零点、AS5047P 检查、20 kHz ADC 注入链检查、PWM 开启后的运行零点校准，异常时保持/切回功率级禁用。原有 BootHealthTask 对 A/B trial 镜像要求连续 5 秒健康窗口；原有过流、编码器、失速等故障锁存仍保留。

本次增加只读 `<REQ_ID> SELFTEST STATUS`，以及 `START` 的两处统一预检：ProtocolTask 接受命令前一次，TighteningTask 真正启动前再次检查，避免排队期间状态变坏。查询不清故障、不启动电机、不动作继电器。

MotorControlTask 在已有 1 kHz 循环中记录 ADC 注入计数和 FOC 控制计数的最近推进 tick。超过 50 ms 不推进会令预检失败；这里不新增 ISR 工作，也不改变 PWM/FOC 控制律。

失败位图：

| 位 | 值 | 条件 |
|---:|---:|---|
| 0 | `0x001` | ADC 故障 |
| 1 | `0x002` | FOC 故障 |
| 2 | `0x004` | 编码器无效 |
| 3 | `0x008` | FOC 禁用 |
| 4 | `0x010` | 运行零点校准未完成 |
| 5 | `0x020` | UART 异步通道未就绪 |
| 6 | `0x040` | 电机不在 IDLE |
| 7 | `0x080` | 转速绝对值超过 2 rpm |
| 8 | `0x100` | 固件升级进行中 |
| 9 | `0x200` | 当前槽仍是 trial |
| 10 | `0x400` | ADC 计数超过 50 ms 未推进 |
| 11 | `0x800` | FOC 计数超过 50 ms 未推进 |

`READY=1` 仅表示以上软件可观测条件均满足。它**不代表**母线欠压、温度、外部急停、继电器负载等硬件保护已实现。若 `START` 的预检失败，返回原有的 FAULT/BUSY/ROTOR_MOVING 错误或 `PREFLIGHT_NOT_READY`，不会进入 RUNDOWN。

## 板上验证

2026-09-24：

| 镜像 | FLASH | RAM | BIN CRC32 | IAP/试运行 |
|---|---:|---:|---|---|
| A | 218,132 / 229,376 B (95.10%) | 64,864 / 131,008 B (49.51%) | `0xAAF2A4E7` | `CURRENT=A CONFIRMED=A PENDING=- GEN=194` |
| B | 217,820 / 229,376 B (94.96%) | 64,848 / 131,008 B (49.50%) | `0x97444BEE` | `CURRENT=B CONFIRMED=B PENDING=- GEN=197` |

两槽编译通过，官方 pw_transfer stream IAP 的整包 CRC32 校验通过、重传 0，并自动确认。当前运行 B。

```text
4301 OK SELFTEST READY=1 MASK=0x000 ADC=1 FOC=1 ENC=1 ZERO=1 UART=1 MODE=IDLE SPEED_OK=1 AAGE=0 FAGE=0 ADC_CNT=270355 FOC_CNT=260321
4302 OK SELFTEST READY=1 MASK=0x000 ADC=1 FOC=1 ENC=1 ZERO=1 UART=1 MODE=IDLE SPEED_OK=1 AAGE=0 FAGE=0 ADC_CNT=275256 FOC_CNT=265222
4303 OK STATUS ... MODE=IDLE ... FLT=0 REASON=0
```

B 槽约 200 ms 两次查询间 ADC/FOC 计数各增加 4901；A 槽相同检查各增加 4702。A/B 的 Modbus DMA 读、无设备超时恢复及连续 25 次读取回归通过，最终继电器位图为 `0x00`。没有发送 `START`，因此并未让电机进入拧紧流程，也未通过人为制造故障来实测各个拒绝分支。

复测：

```powershell
pwsh -NoProfile -File .\tools\selftest_status_smoke.ps1 -Port COM5 -ExpectedSlot B
pwsh -NoProfile -File .\tools\modbus_async_smoke.ps1 -Port COM5 -ExpectedSlot B
```

## 下一步边界

母线欠压、过温、门极驱动故障和真正的急停必须先确认驱动板采样/告警引脚、分压量程及接线，再做单独的硬件保护验证。不能仅凭本次 `READY=1` 声称具备这些保护。Flash 已用约 95%，后续增加功能前须关注槽上限。
