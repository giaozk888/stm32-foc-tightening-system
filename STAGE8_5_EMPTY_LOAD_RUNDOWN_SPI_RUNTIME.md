---
title: Stage 8.5 - 空载 RUNDOWN 中的 AS5047P 运行观察
tags:
  - STM32G474
  - AS5047P
  - FOC
  - 电机试转
date: 2026-09-25
status: empty-load-rundown-ended-safe-latched-not-full-tightening
---

# Stage 8.5：空载 RUNDOWN 中的 AS5047P 运行观察

用户要求使用现有完整拧紧流程做通电试转。现场确认电源设定 12.0 V、限流 0.5 A，PD6010B 输入端由用户报告实测 12 V；电机 U/V/W 已接回、电机固定、无工件且人员避开。测试前 B 槽已确认、IDLE、无故障，但 `ANALOG SAFE=1`，`START` 返回 `ERR 104 ANALOG_SAFE_LATCHED`。用户明确要求退出 SAFE；使用 ST-LINK Hot Plug 1 MHz 执行一次软件复位，随后复查 `SAFE=0 SD=1 MOE=1 FOC=1`、`SELFTEST READY=1 MASK=0x000`、`STATUS MODE=IDLE FLT=0`、`ANALOG VOLT VBUS_EST_MV=11601 PROTECT=0`。复位后没有立即启动，先完成上述检查。

接着发送 `4360 START` 并监测串口状态。`START` 接受并进入 `RUNDOWN TARGET=70rpm`。约 8 秒内三相控制链保持 `ADC/s≈20004`、`FOC/s≈20004`、`FLT=0`，编码器位置由约 0° 增至约 1888°。读取到的瞬时/窗口速度有明显波动，状态轮询显示 `CTRL` 从约 1.5 到 102 rpm，`DET` 从约 -3 到 119.8 rpm，`IqRef` 曾达到约 348 mA；这些是抽样日志，不构成严格的最大值统计。未观察到真正的工件接触，不应把速度波动或电流指令升高误判为可靠的接触检测。

最终自动结果：

```text
4360 OK START QUEUED
EVT REQ=4360 STARTED MODE=RUNDOWN TARGET=70rpm
TIGHTEN: RUNDOWN timeout/travel abort -> IDLE
EVT REQ=4360 COMPLETE RESULT=RUNDOWN_TIMEOUT
4362 OK STATUS STAGE=10 BUSY=0 MODE=IDLE OUTCOME=RUNDOWN_TIMEOUT CONTACT=0 START_REQ=4360 FLT=0 REASON=0
4363 OK RESULT DATA START_REQ=4360 OUTCOME=RUNDOWN_TIMEOUT CONTACT=0
```

结束后只读诊断：`ENC DIAG DWT=1 READS=92120 FAIL=0 OVER1MS=0 LAST_US=114 MAX_US=142`，MotorCtrl 栈高水位 `FREE_B=2168`。这些计数自本次复位以来累计，并非本轮 8 秒独立计数；它们支持“本次监测时未见编码器 SPI 报错”，但不能证明高速角度精度或测速算法已验收。`ANALOG VOLT VBUS_EST_MV=11701 PROTECT=0` 只是一笔停转后读数，不能排除第七章孤立尖峰。

测试结束后主动执行 `ANALOG SAFE`：`LATCHED=1 SD=0 MOE=0 FOC=0`；复查 `MODE=IDLE FLT=0 REASON=0 IqRef=0mA`。当前桥臂已在软件上停用。**这次只完成空载 RUNDOWN 试转，不是完整拧紧流程成功，也不证明第七章模拟量问题已解决。**在没有固定工件时，不应通过手握电机轴模拟接触；后续带载试验需单独设计夹具和风险控制。

相关：[[第八章_AS5047P_SPI磁编码器_Obsidian总结]]、[[第七章_设备自检与保护_Obsidian总结]]。
