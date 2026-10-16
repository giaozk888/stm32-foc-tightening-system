---
title: Stage 7.8 - 12V 下 B 槽升级与 ANALOG SAFE 板上预检
tags:
  - STM32G474
  - PD6010B
  - FOC
  - 安全诊断
status: B-confirmed-safe-latched
date: 2026-09-25
---

# Stage 7.8：12 V 下 B 槽升级与安全诊断预检

## 实测过程

1. 最初 COM5 读到 A 槽已确认、无故障，但 `VBUS_EST_MV=13657`；暂停升级。用户将共用电源调回 12 V，随后万用表在 PD6010B 电源输入端确认 12 V。
2. 旧 A 固件在 12 V 下首次 10 次采样出现一次 PC4 原始值约 1538、换算母线最高 30,845 mV；万用表没有对应的电源升高，归类为**测量链瞬态异常，根因未定**。给 `tools/analog_idle_stability.ps1` 增加逐次 12 V ±10% 越界即停止的门槛。
3. 重新进行 30 次、约 30 秒只读采样：PC4 raw 577–615，VBUS 估算 11,672–12,334 mV，ADC/FOC 计数各增加 605,642，无模拟采样错误、无故障。一次通过不能排除偶发尖峰。
4. 使用 `tools/transfer_iap_stream.ps1` 将新 B 镜像写入非活动槽：222,684 B，CRC32 `0x8A229608`，6959 个 32 B 数据块，重传 0。`FW END TARGET=B ... ATTEMPTS=2 RESETTING`，随后 `CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0 GEN=215`。A 槽没有改写。
5. B 槽在 12 V 下 `MODE=IDLE FLT=0`，`ANALOG VOLT` 有效。`FAULT SNAPSHOT`、`FAULT FILTER` 均返回 `VALID=0`，只证明接口可用，未实测过流捕获。
6. 使用 `tools/analog_safe_smoke.ps1` 进入单向锁存安全模式：进入前 `SD=1 MOE=1 FOC=1`，进入后及 1.2 s 后均为 `LATCHED=1 SD=0 MOE=0 FOC=0`。停 PWM 后 ADC2 规则组采样数从 844 增至 855，错误仍为 0；`ANALOG VOLT` 仍有效。随后 20 次只读状态/电压查询均通过，母线估算范围 11,532–11,893 mV。
7. 用户随后用万用表在 PD6010B 实测 CTRL_SD 对 GND 为 **0 V**；再次运行 `tools/analog_safe_smoke.ps1 -VerifyOnly`，确认 B 槽仍已确认、安全锁存未解除，ADC2 采样持续增长。此时仍保持 12 V，未升压。
8. 用户确认继电器 COM/NO/NC 未接外部负载，保持 MCU 不断电、不复位，将共用电源缓慢调到 13 V；万用表确认输入 13 V、CTRL_SD 0 V。B 槽仍已确认，`FLT=0`、`LATCHED=1 SD=0 MOE=0 FOC=0`，估算母线 12,635–12,755 mV，无 ADC2 错误。
9. 再调到 14 V；万用表确认输入 +14 V、CTRL_SD 0 V。即时检查估算 13,698–13,758 mV，安全锁存与无故障状态保持。但 `tools/analog_safe_stability.ps1` 30 次轮询在第 11 次提前停止：`ANALOG LIVE` 读到 PC4 raw 635，而随后单独请求 `ANALOG VOLT` 得到 15,442 mV，越过 14 V ±10% 诊断界限 42 mV。两条命令不保证是同一 ADC 帧，不能把 635 raw 与 15,442 mV 直接配成一组样本。错误计数仍为 0；这证明偶发高估在停 PWM 时也能出现，**不能判定为 PWM 干扰，也不能判定实际母线升压**。
10. 用户随后将电源调回 12 V，万用表复测输入 12 V、CTRL_SD 0 V；COM5 再确认 B 已确认、`FLT=0`、安全锁存仍在、ADC2 样本计数增长，母线估算 11,672 mV。本轮未触发电机，也未复位。
11. 用户更换杜邦线并确认仍为 PD6010B 的 VBUS 信号接 PC4、输入供电约 12 V。COM5 先读到估算约 11.6–11.9 V，B 已确认、`FLT=0`、`ANALOG SAFE` 保持。随后 60 次连续采样在第 30 次提前停止：同轮 `ANALOG LIVE PC4_RAW=663 PC5_RAW=1346`，`ANALOG VOLT VBUS_EST_MV=13296`，超过 12 V ±10% 上界，错误计数仍为 0。换线**未消除**偶发高估；尚不能区分剩余共地/板端输出问题与 ADC2 采样问题。失败后再次只读核对 B 已确认、无故障、`LATCHED=1 SD=0 MOE=0 FOC=0`，估算恢复约 11.7 V。

## 当前边界与下一步

- 当前 B 槽已确认，MCU 报告 `ANALOG SAFE` 已锁存，电源已回到 12 V；**本轮不再升压**。复位或掉电会退出安全锁存并在启动流程中重新使能桥臂。
- PD6010B 的 CTRL_SD 已由用户实测约 0 V。若之后复位或掉电，安全锁存会解除，必须重新验证该引脚，不能沿用本次结论。
- PC4/母线估算多次出现异常高值（12 V 时约 30,845 mV；14 V 时 15,442 mV；换线后 12 V 时 13,296 mV），后两次发生在 `MOE=0` 后。需继续区分 ADC2 规则/注入转换交互、ADC 序列/时序、剩余共地/板端输出或模拟信号干扰；不能据此启用自动过压/欠压保护，也不能把软件估算值视为高可信电压计。
- 已增加 `tools/analog_safe_stability.ps1`，逐次检查安全锁存、ADC 样本新鲜度、错误数和估算电压界限；它在本次 14 V 测试中正确阻止了“偶发尖峰仍判 PASS”。
- 没有主动触发电机或过流；`FAULT SNAPSHOT` 捕获路径和 `START` 锁存拒绝路径尚未做危险动作测试。

相关：[[STAGE7_5_OVERCURRENT_FAULT_SNAPSHOT]]、[[STAGE7_6_ANALOG_SAFE_DIAGNOSTIC_MODE]]、[[STAGE7_7_CURRENT_FILTER_TRIP_AUDIT]]。
