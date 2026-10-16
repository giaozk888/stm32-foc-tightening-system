---
title: Stage 8.4 - AS5047P SPI 实波形核验
tags:
  - STM32G474
  - AS5047P
  - SPI
  - 逻辑分析仪
date: 2026-09-25
status: digital-spi-waveform-verified
---

# Stage 8.4：AS5047P SPI 实波形核验

## 安全前提

B 槽已确认；电机 U/V/W 已断开。接探头前关闭 PD6010B 的 12 V，并用万用表在其输入端确认 0 V。调整探头接线时也应停止采集、断开 NUCLEO USB；USB 重新接通后须重新执行 `ANALOG SAFE`，确认 `LATCHED=1 SD=0 MOE=0 FOC=0`，再执行采样。逻辑分析仪不要接到电机 U/V/W、驱动板母线或 12 V。

## 接线

本次实际采集接线（STM32 引脚由 B 槽 `main.h` 和 `stm32g4xx_hal_msp.c` 核对）：

| 分析仪 | STM32 / 编码器信号 |
| --- | --- |
| GND | NUCLEO GND |
| CH0 | PA4 / AS5047P CSn |
| CH1 | PA5 / SPI1 SCK |
| CH2 | PA6 / SPI1 MISO |
| CH3 | PA7 / SPI1 MOSI |

不接分析仪 VCC。优先从 AS5047P 模块的同名信号测试点/排针并联探测，切勿拔掉正常 SPI 线。

## 采集设置及预期

- 采样率 24 MHz；CH0 下降沿触发；采集窗口建议至少 1 ms，包含 CS 上升后空闲段。
- SPI 解码：时钟空闲低（CPOL=0）、第二沿采样（CPHA=1，即 mode 1）、MSB first、16 bit/word、CS 低有效。
- SPI1 配置 170 MHz PCLK2 /32，名义 SCK ≈5.3125 MHz。24 MHz 分析仪每 bit 约 4.5 个采样点，适于查帧顺序，但不能替代示波器判断边沿模拟质量。
- 在 SAFE 下发送一次 `2001 ENC SAMPLE`；正常两帧的 MOSI 应依次为 `0xFFFF`（读 ANGLECOM）和 `0xC000`（读 NOP）。第二帧 MISO 才是本次角度响应；首帧 MISO 是流水线旧响应，不能当角度。
- 若角度响应置 EF，代码将额外发送 `0x4001, 0xC000` 读取 ERRFL，再发送 `0xFFFF, 0xC000` 重试角度；无需为本次验证刻意制造故障。
- 每帧 CS 应独立拉低/拉高；检查 CS 下降到首个时钟及 CS 高电平帧间隔，工程意图均大于 350 ns。24 MHz 数字采样的时间量化约 41.7 ns；要严谨验证模拟边沿/时序裕量仍需示波器。

## 本次测试结果

- PulseView、24 MHz 采样、CS 下降沿触发；SPI 解码映射 `CS=D0 CLK=D1 MISO=D2 MOSI=D3`，mode 1、MSB first、16 bit、CS 低有效。
- 原始采样已归档为 `stage8_4_spi_capture.sr`：sigrok session，100 万采样点（41.667 ms），SHA-256 `3AE3085FDF32C03A7DB1E85EB5B8DCB6F96010A32D3918755824112237DC8387`。时序数字为从该文件逐采样提取，而非从截图估计。
- 两次独立 CS 低电平及两组时钟均被捕获。MOSI 两帧依次解为 `0xFFFF`、`0xC000`，符合 ANGLECOM 读命令及 NOP。
- 第二帧 MISO 解为 `0x0C53`，即 14-bit 角度原码 `3155`；串口同轮 `2003 OK ENC SAMPLE HAL=0 RAW=3155 US=69 SAFE=1 SD=0 MOE=0 FOC=0`，数值一致。首帧 MISO `0x0000` 是流水线旧响应，不作为本次角度。
- 日志中此前还有一次 `RAW=3158 US=69`，属另一笔采样，不能与 `0x0C53` 混为同一帧。
- 串口 `ANALOG SAFE` / `ANALOG SAFE STATUS` 均报告 `LATCHED=1 SD=0 MOE=0 FOC=0`；监控 `ADC/s=0 FOC/s=0 EN=0 FLT=0`。本次仅验证无功率输出条件下的编码器 SPI。
- 每帧有 32 个 SCK 边沿，即 16 个完整时钟。由首边沿至末边沿的 70 个采样间隔（15.5 周期）计算，两帧 SCK 均约 `5.314 MHz`，与配置名义 `5.3125 MHz` 一致。采样时间量化为 41.7 ns，不应把此数值当作示波器级精度。
- 第一帧 CS 拉高至第二帧 CS 拉低间隔 `9.375 µs`；第二帧 CS 拉低至首个 SCK 边沿 `9.417 µs`；第一、二帧末个 SCK 边沿至 CS 拉高分别为 `11.875 µs`、`11.833 µs`。这些数字均明显大于工程要求的 350 ns。采集从第一帧 CS 已为低电平时开始，故**第一帧 CS 下降至首个 SCK 的建立时间不可由此文件测得**。
- 结论限定为本次无功率输出、静止条件下的数字 SPI 帧内容及可见时序。24 MHz 逻辑分析仪不能证明模拟边沿质量，也未覆盖 EF 错误恢复、最坏中断负载或电机运动；第七章模拟量尖峰仍阻止恢复电机供电。

相关：[[STAGE8_2_AS5047P_FAKE_SPI]]、[[STAGE8_3_AS5047P_TIMING_STACK_AUDIT]]。
