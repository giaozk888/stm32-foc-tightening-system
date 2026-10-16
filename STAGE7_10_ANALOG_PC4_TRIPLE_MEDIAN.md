---
title: Stage 7.10 - PC4 三采样中值实验
tags:
  - STM32G474
  - PD6010B
  - ADC2
  - FOC
status: A-confirmed-12V-safe-mode-tested
date: 2026-09-25
---

# Stage 7.10：PC4 三采样中值实验

## 目标与实现边界

Stage 7.9 发现 PC4 连续两次采样的任意一笔都可能单独尖峰，不能简单丢弃“首读”。本阶段只在 `ANALOG SAFE` 单向锁存、PWM 停止后，以 10 Hz 周期连续读取 PC4 三次，保留三笔原始值并计算中值，然后继续读取 PC5。正常 FOC 路径不增加 ADC 转换；既有 `ANALOG VOLT` 仍使用第一次 PC4 原始值，**中值仅用于诊断，不用于电机保护**。

新增 `<REQ_ID> ANALOG TRIPLE`：`R=a,b,c` 为最近三笔，`M` 是中值，`MV` 是按上电 VDDA 估算的中值母线电压；`PR` 保存“历史最高单笔 raw”对应的完整三元组，`PM` 保存“历史最高中值”对应的完整三元组；`SP` 为最大组内跨度，`D` 为三笔跨度超过 60 count 的组数，`N/E` 为成功/失败组数。全部只存 RAM，复位即清零。

## 编译和升级

- A/B clean build 均通过。三采样初版 A Flash 224,940 B / 224 KiB、RAM 65,040 B；B Flash 224,628 B / 224 KiB、RAM 65,024 B。
- 首次板上 `ANALOG TRIPLE` 已抓到 `1149,585,586` 这样的单笔峰值，但长格式回复被 `Protocol_HandleLine()` 的 `msg[192]` 截断，尾部错误计数不可读。将回复压缩至最坏情况下小于 192 B，不改变三采样算法；增量重新编译通过。最终 A Flash **224,772 B / 224 KiB（97.99%）**、RAM **65,040 B**；B Flash **224,460 B / 224 KiB（97.86%）**、RAM **65,024 B**。
- 已从确认 B 槽通过官方 stream IAP 升级最终 A 镜像 224,772 B、CRC32 `0x25C0D868`，7025 块、重传 0。A 经 trial 自动确认：`CURRENT=A CONFIRMED=A PENDING=- ATTEMPTS=0 GEN=224`。B 槽板上仍是**长回复被截断的初版三采样镜像**；最终 B 源码已编译但尚未烧录。
- A 在 12 V 下重新执行 `ANALOG SAFE`，MCU 回读 `LATCHED=1 SD=0 MOE=0 FOC=0`，无故障。用户在本次复位后未再实测驱动板 CTRL_SD，因此本轮**没有升压**，只做 12 V 观察。

## 120 秒板上结果

命令：

```powershell
.\tools\analog_triple_monitor.ps1 -Port COM5 -ExpectedSlot A -Seconds 120 -PollMs 5000
```

- `N=247 -> 1459`，新增 **1212** 组三采样；`E=0 -> 0`，`D=5 -> 43`（新增 38 组跨度 >60 count，约 3.1%）。期间安全锁存保持、`MODE=IDLE FLT=0`。
- 历史最高单笔 raw **1279**，对应三元组 `577,577,1279`；用启动时 VDDA 估算，相当于约 **25.61 V** 的单笔读数，但真实输入由用户维持在约 12 V，不能解释为真实母线达到 25.61 V。
- 历史最高三笔中值 raw **596**，对应三元组 `596,715,580`；估算约 **11.94 V**。最近样本中值常在约 580–590 附近。

## 结论与下一步

在本次 12 V、停桥、约两分钟的样本中，三笔中值压住了观测到的孤立尖峰；这**不是**模拟输入/ADC 根因已解决的证明，也不是运行中母线保护可以启用的证据。尚未测试更长时间、其他真实电压、PWM 运行时的行为或同一组两笔同时异常的情况。保持 `ANALOG VOLT` 与保护逻辑不变。

若继续，先考虑模拟路径/ADC2 规则组时序的根因检查；任何中值驱动的保护功能须另行设计失效判据、校准和多工况验证。Flash 余量已经很紧，继续加功能前需控制体积。

相关：[[STAGE7_9_ANALOG_PC4_PAIRED_SAMPLE]]、[[STAGE7_8_ANALOG_SAFE_HARDWARE_SMOKE]]。
