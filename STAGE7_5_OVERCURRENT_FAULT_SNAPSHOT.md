---
title: Stage 7.5 - 过流跳闸瞬间快照（仅编译，未上板）
tags:
  - STM32G474
  - PD6010B
  - FOC
  - 故障诊断
status: build-only-not-flashed
date: 2026-09-25
---

# Stage 7.5：过流跳闸瞬间快照

> [!warning] 当前状态
> 用户要求暂停板上测试。本阶段只修改 A/B 槽源码并完成 clean build，**没有烧录、重启、改变电源或复现故障**。当前板上固件仍不包含新命令；旧故障的瞬时数据无法追溯。

## 为什么做

14 V 第二测量点的 `ANALOG VOLT` 约为 13.7 V，说明母线电压诊断链初步合理。但此前一份日志在启动后约 72–75 秒出现 `R=1 FLT=1 EN=0`，源码的 `R=1` 是三相任一相的**软件 2 A 电流跳闸**，不是 `VBUS` 保护（仍为 `PROTECT=0`）。旧版 RTOS 串口监视只打印 `R=1`，跳闸瞬间的三相电流虽保存在 RAM 中，却没有通过当前 ProtocolTask 暴露。另一份新日志仅到 45 秒，未再跳闸，不能证明原因已消失。

另外，日志中的 `MODE=IDLE EN=1`、启动日志中的 `CTRL_SD=HIGH` 表明 IDLE 仍使能桥臂/电流环。后续调压实验不能仅依赖 IDLE；本阶段**没有**新增安全调压模式。

## 代码变更

在 `foc2_app_a/Core/Src/main.c` 与 `foc2_app_b/Core/Src/main.c` 加入同一套诊断：

1. 仅当软件电流跳闸实际发生时，按原顺序先将 `CTRL_SD` 拉低并设 PWM 50/50/50，然后在 ISR 中保存**第一次**跳闸快照；不提高 2 A 阈值，不改故障锁存或复位行为。
2. 保存触发时间 `MS`、ADC 注入序号 `SEQ`、送入 FOC 的 U/V 已接受值 `UA/VA`、同一触发周期的物理 ADC 值 `UP/VP`、零点 `U0/V0`、计算出的 `IU/IV/IW`（mA）、最近一次 PC4 的原始 `VB`、该电压样本年龄 `VAGE`（ms）和有效标志 `VVALID`。`VB` 仅是最近的 IDLE 低频样本，**不是与电流同时采到的母线电压**。
3. 所有字段写完后才置 `VALID=1`。新增只读 Protocol V2 命令 `FAULT SNAPSHOT`；发送命令本身不清故障、不启动或关闭驱动。

未来安装并确认运行的是这版固件后，查询示例：

```text
2002 FAULT SNAPSHOT
```

无快照时回复 `VALID=0 REASON=<当前故障码>`；若确有软件过流，则回复 `VALID=1 REASON=1 ... IU=... IV=... IW=...`。快照只存 RAM，重启后丢失；须在故障发生后、复位前读取。其他故障码不生成过流快照。

## 离线验证

分别执行：

```powershell
cmake --build .\foc2_app_a\build\Debug --clean-first
cmake --build .\foc2_app_b\build\Debug --clean-first
arm-none-eabi-size .\foc2_app_a\build\Debug\foc2.elf .\foc2_app_b\build\Debug\foc2.elf
```

两槽均 clean build 成功，无链接错误：

| 槽 | Flash text+data | RAM data+bss | BIN 大小 | Flash 槽容量 |
|---|---:|---:|---:|---:|
| A | 221,136 B | 64,928 B | 221,148 B | 224 KiB |
| B | 220,824 B | 64,912 B | 220,836 B | 224 KiB |

以上只证明编译/链接通过，**尚未验证板上命令、跳闸快照正确性或运行稳定性**。当前已确认运行的 A 槽保持原样；B 槽也未烧录。未来上板前，先核对供电、线束和回退策略，不要直接以 14 V 复现故障。
