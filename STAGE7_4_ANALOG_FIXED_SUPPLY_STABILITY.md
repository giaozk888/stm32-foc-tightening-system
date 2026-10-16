---
title: Stage 7.4 - 共用12V电源下的模拟量稳定性基线
aliases:
  - 第七章 模拟量稳定性基线
tags:
  - STM32G474
  - PD6010B
  - ADC
  - FOC
  - 安全诊断
status: verified-idle-only
date: 2026-09-24
---

# Stage 7.4：共用 12 V 电源下的模拟量稳定性基线

> [!success] 本阶段结论
> 当前 A 槽确认运行，继承 Stage 7.3 的 `ANALOG LIVE` / `ANALOG VOLT` 只读诊断。在电机 `IDLE`、现有 12 V 供电不变的条件下，连续 30 次、约 30 秒的采样有效，模拟采样错误数保持 0，20 kHz ADC/FOC 计数正常。**未改变电源电压、未操作继电器、未启动电机、未启用任何电压/温度保护。**

## 1. 为什么这一步没有做第二电压点

原计划通过另一个已知母线电压，核对 `VBUS = POWER/25` 的线性关系。但用户确认目前这路 12 V 同时给继电器板或其他设备供电。直接调节共用电源，可能让其他设备欠压、误动作或掉电，故本阶段**取消变压测试**，先在现有供电下建立只读噪声与采样链基线。没有第二测量点，不能声称完成两点校准，也不能据此设定最终欠压/过压门限。

## 2. 本次只读测试方法

新增 `tools/analog_idle_stability.ps1`，通过 COM5/Protocol V2 做以下检查：

1. `FW STATUS` 必须为预期已确认槽、`PENDING=-`；`STATUS` 必须为 `MODE=IDLE FLT=0`。
2. 记录起始 `SELFTEST STATUS` 的 ADC/FOC 计数。
3. 每秒读取 `ANALOG LIVE` 和 `ANALOG VOLT`，累计 30 次；检查 `VALID=1`、数据年龄不超过 500 ms、12 位原始值未到 0/满量程，记录 PC4、PC5、估算母线电压和 VTEMP 引脚电压的最小/最大值。
4. 记录末次 `SELFTEST STATUS`，检查 ADC/FOC 计数持续增长、模拟采样错误数未增加、设备仍为 IDLE 且无故障。

脚本只发送读取状态/诊断命令，不发送 `START`、`MODBUS RELAY`、`FW BEGIN` 或其他改变外设状态的命令。重现：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\analog_idle_stability.ps1 -Port COM5 -ExpectedSlot A -Samples 30 -IntervalMs 1000
```

## 3. 板上实测结果

| 指标 | 结果 | 解释 |
|---|---:|---|
| 采样次数/时长 | 30 次 / 30.2 s | 每秒轮询一次固件的 10 Hz 最新值 |
| PC4 / VBUS 原始值 | 583–594 counts | 跨度 11 counts |
| PC5 / VTEMP 原始值 | 1387–1453 counts | 跨度 66 counts；不能直接换算成 °C |
| `VBUS_EST_MV` | 11,692–11,913 mV | 使用启动时工厂 `VREFINT` 估计的 VDDA 和标称 25:1 分压；**不是校准后的保护测量** |
| `VTEMP_MV` | 1,113–1,166 mV | 仅是传感器引脚电压 |
| 模拟采样错误 | 0 → 0 | 30 秒内未出现新错误 |
| ADC / FOC 计数 | 各 +605,643 | 按 30.2 秒约 20.05 kHz，控制采样链持续运行 |

设备最终仍为已确认 A 槽、`MODE=IDLE FLT=0`。此基线只覆盖当前供电、当前负载和电机静止状态；PC5 的变化可能包含模拟噪声或板温变化，现有数据不能区分，不能据此推算温度。

## 4. 对后续保护设计的约束

- `ANALOG VOLT` 的 `PROTECT=0` 保持不变。当前读数仅供观察，不进入 PWM/驱动关断条件。
- 固件目前 **IDLE 才采集** PC4/PC5；电机活动时 `ANALOG LIVE` 会变为无效，故不能把它作为运行中欠压或过温保护输入。
- 真正的保护至少需要：活动状态下经验证不干扰 ADC2 注入相电流采样的持续测量、数据超时/断线检测、门限与去抖、故障锁存和安全停机路径、复位/恢复策略，以及故障注入测试。
- 欠压/过压门限必须依据驱动板和电机实际允许范围、独立供电下的第二测量点及误差预算确定；温度阈值还需 NTC 参数或实测校准点。
- 若将来要做第二电压点，先确认 PD6010B 可以独立供电，且共用 12 V 的其他设备不受调整影响；断电重新整理供电后，核对极性、地和电压范围，再进行只读采样。**不要直接调整当前共用电源。**

## 5. 相关记录

- [[STAGE7_3_POWER_SENSING_WIRING_AUDIT]]：VBUS/VTEMP 接线、上电快照、10 Hz IDLE 采样及工厂 VREFINT 电压换算。
- [[STAGE7_2_ADC_FOC_CHAIN_WATCHDOG]]：ADC/FOC 计数和链路健康检查。
- `tools/analog_idle_stability.ps1`：本阶段只读稳定性脚本。
