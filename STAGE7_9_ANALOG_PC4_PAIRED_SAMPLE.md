---
title: Stage 7.9 - PC4 同通道双采样诊断
tags:
  - STM32G474
  - PD6010B
  - ADC2
  - 模拟量诊断
status: A-confirmed-hardware-observed
date: 2026-09-25
---

# Stage 7.9：PC4 同通道双采样诊断

## 动机与改动

Stage 7.8 在真实输入 12/14 V 时发现 `ANALOG VOLT` 偶发高估；换杜邦线后仍复现。为区分“ADC2 从 PC5 切到 PC4 后的首笔采样残留”和持续的模拟电压升高，在 A/B 源码加入一项**只在 `ANALOG SAFE` 已锁存时**运行的诊断：每个 10 Hz 周期先读 PC4 第一次，再保持同一通道立即读第二次，随后照旧读 PC5。原有 `ANALOG LIVE` / `ANALOG VOLT` 仍使用 PC4 第一次原始值，未加滤波、未改变 FOC 电流采样或保护阈值。

新命令：

```text
<REQ_ID> ANALOG PAIR
```

字段：`LAST1/LAST2` 为最近一对，`PEAK1/PEAK1_2` 为首读历史峰值及与它同对的第二读，`PEAK2/PEAK2_1` 为第二读历史峰值及与它同对的首读，`COUNT/ERR` 为双采样成功/失败累计数。峰值在 RAM 中，复位后归零。该命令只是诊断，不提供稳定电压或自动保护。

## 编译和升级

- A/B 均 clean build 成功：A Flash 223,604 B / 224 KiB、RAM 64,992 B；B Flash 223,292 B / 224 KiB、RAM 64,976 B。A/B 镜像余量仍很小，约 5–6 KiB。
- 仅将新 A 镜像（223,604 B，CRC32 `0xD1A426E7`）从已确认 B 槽通过现有官方 stream IAP 写入，6988 个块、重传 0，`FW END ... ATTEMPTS=2 RESETTING`。首次复位后 COM5 查询超时，第二次查询成功：`CURRENT=A CONFIRMED=A PENDING=- ATTEMPTS=0 GEN=218`，12 V、IDLE、`FLT=0`。
- A 槽重新进入 `ANALOG SAFE`，MCU 读回 `LATCHED=1 SD=0 MOE=0 FOC=0`，ADC2 继续更新。用户在本次复位后未再次物理测量 CTRL_SD；因此本次没有升压，仅在 12 V 下观察。B 板上仍是 Stage 7.8 的已确认旧镜像，新 B 源码只完成编译。

## 90 秒板上结果

`tools/analog_pair_monitor.ps1 -Port COM5 -ExpectedSlot A -Seconds 90 -PollMs 5000` 读到 `COUNT=505 -> 1414`、`ERR=0 -> 0`，结束时仍无故障且安全锁存保持。

关键峰值：

| 峰值发生位置 | 峰值 raw | 同对另一次 raw | 含义 |
|---|---:|---:|---|
| PC4 首读 | 866 | 第二读 584 | 首读瞬时高、第二读恢复 |
| PC4 第二读 | 1195 | 首读 579 | 第二读也可单独瞬时高 |

平时两次读数大多约 580。观察到的两类峰值都只占一对中的一次；不能把“切换通道后的**首次**转换残留”认定为唯一根因，也不能据万用表的 12 V 读数排除微秒级的模拟噪声。软件 `HAL_ADC` 没报错，只表示转换流程完成，不保证样本代表稳定信号。

## 结论与限制

- 换杜邦线没有解决；单次异常发生在停 PWM 后。问题范围缩小到 PC4 模拟路径、ADC2 采样/时序或瞬态干扰，但**未定根因**。
- 不能简单丢弃第一次采样：第二次也出现过独立高峰。后续若要形成可靠诊断值，应先测试三次采样的分布与中值，并保留原始异常计数；在验证前不启用运行中过压/欠压保护。
- 本轮没有升压、启动电机或主动触发过流。旧的 14 V 带桥臂过流事件与这里的 PC4 尖峰是否相关，尚无证据。

相关：[[STAGE7_8_ANALOG_SAFE_HARDWARE_SMOKE]]、[[STAGE7_7_CURRENT_FILTER_TRIP_AUDIT]]。
