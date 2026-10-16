---
title: 第八章｜STM32G474 + AS5047P SPI 磁编码器验证总结
tags:
  - STM32G474
  - AS5047P
  - SPI
  - FOC
  - 单元测试
  - 逻辑分析仪
date: 2026-09-25
status: 编码器数字通信已验证；电机运行未验收
---

# 第八章：AS5047P SPI 磁编码器

> [!note] 2026-10-06增量，非本章历史实机数据
> 新增独立 `EncoderDmaReadOnly` 试验配置，使用DMA/定时器、有绝对截止时间的采样状态机。主机模拟测试和A/B编译通过，未刷写、未实机测时，详见 [[嵌入式实习面试笔记/17_SPI_DMA定时采样_白话实现与验证]]。以下8.1–8.5的逻辑波形/计时属于旧阻塞驱动，不证明新版严格硬实时。

> [!summary] 结论
> A/B 源码的 AS5047P 协议、角度计算和完整事务通过主机测试；B 槽已在板上确认运行，空闲时连续约 18,890 次角度读取未见失败或超过 1 ms 的事务；真实逻辑波形的命令、响应和串口原码一致。随后按用户要求做过一次 12 V、空载试转，进入 RUNDOWN 后自动以 `RUNDOWN_TIMEOUT` 结束、无接触、无故障，已重新锁存 SAFE。**这完成了编码器数字通信验证和一次有限的空载动态观察，不等于带工件的 FOC/拧紧验收。**第七章 PC4/PC5 模拟尖峰仍未排除。

## 1. 架构与实际边界

```text
AS5047P 磁铁/芯片
    │ 16-bit SPI mode 1，CS 软件控制
    ▼
STM32G474 SPI1：PA4=CS、PA5=SCK、PA6=MISO、PA7=MOSI
    │ 每约 1 ms 在 MotorControlTask 更新机械角度/速度
    ▼
20 kHz ADC 注入 ISR：使用角度预测执行电流环
```

编码器用**偶校验位**及 EF/ERRFL 报错机制，**不是 CRC**；SPI 外设硬件 CRC 未开启。正常读 ANGLECOM 是 `0xFFFF` → `0xC000` 两个 16-bit 帧，第二帧 MISO 才是本次角度。EF 错误处理可扩展到读取 ERRFL 并重试，总共最多六帧。当前不是“20 kHz SPI 读角度”：20 kHz 是电流 ISR，真实 SPI 角度更新在约 1 kHz 前台任务中。

## 2. 按步骤完成的工作

| 阶段 | 主要工作 | 证据 |
| --- | --- | --- |
| 8.1 纯函数 | A/B 共用思路的 `as5047p_protocol.h`：读命令偶校验、响应检查、EF/ERRFL 决策、14-bit 回绕、转速与电角度；主机运行两槽测试 | A、B 各 147,483 项检查通过；[[STAGE8_1_AS5047P_HOST_TESTS]] |
| 8.2 完整事务 | `as5047p_transaction.h` 注入 16-bit 传输回调，用假 SPI 设备核对正常两帧、EF 六帧、传输和奇偶错误；失败不覆盖旧角度 | A、B 事务测试各 52 项检查通过；总计 `ctest` 4/4 通过；[[STAGE8_2_AS5047P_FAKE_SPI]] |
| 8.3 运行时诊断 | 加 DWT 整次事务计时、失败/超 1 ms 计数、MotorCtrl 栈高水位，以及 SAFE 下的单次 `ENC SAMPLE`；B 槽经 IAP 试运行并确认 | `CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0 GEN=234`；约 18,890 次读数，`FAIL=0 OVER1MS=0 MAX_US=141`；[[STAGE8_3_AS5047P_TIMING_STACK_AUDIT]] |
| 8.4 真实数字波形 | PulseView 24 MHz 同采 CS/SCK/MISO/MOSI，mode 1、16 bit 解码；保存 `.sr` 并逐采样复核时序 | MOSI=`FFFF/C000`，MISO 第二帧=`0C53`=3155，与串口 `RAW=3155 HAL=0 US=69` 一致；[[STAGE8_4_AS5047P_SPI_WAVEFORM]] |
| 8.5 空载动态观察 | 经用户确认接线/固定和 12 V、0.5 A 限流后复位退出 SAFE，一次 `START` 进入 RUNDOWN；结束后重新锁存 SAFE | 约 1888° 运动，`RUNDOWN_TIMEOUT CONTACT=0 FLT=0`；累计编码器诊断 `FAIL=0 OVER1MS=0`，但测速波动明显；[[STAGE8_5_EMPTY_LOAD_RUNDOWN_SPI_RUNTIME]] |

8.1/8.2 笔记中的“尚未烧录”描述是**当时的阶段快照**；随后 8.3 已将诊断版 B 镜像升级并在板上确认。不能把这些历史状态误读为现在 B 槽未验证。A 槽有相应源码和离线构建，但本章没有把最新诊断版 A 烧入板上；A 仍作为已知可用的回退槽。

## 3. 关键测试结果与内存

- 主机测试：MSVC + CMake/Ninja，`ctest` **4/4** 通过；纯函数 A/B 各 147,483 项、事务 A/B 各 52 项检查通过。
- 8.3 离线构建记录：A `FLASH=226856 B`、`RAM=65120 B`；B `FLASH=226488 B`、`RAM=65104 B`。每槽 Flash 224 KiB（229376 B），对应余量 A 2520 B、B 2888 B。这是当时构建结果；本章后续未修改固件。
- B 槽 IDLE、未连接电机：`READS=18890 FAIL=0 OVER1MS=0 LAST_US=135 MAX_US=141`。MotorCtrl 栈配置 3072 B，观测最小剩余 `FREE_B=2168`，约使用 904 B。SAFE 后的手动单次读取约 69 µs。
- 原始波形：[stage8_4_spi_capture.sr](stage8_4_spi_capture.sr)，24 MHz、100 万采样点；两帧各 16 时钟。SCK 由数字边沿估算约 **5.314 MHz**，接近配置名义 5.3125 MHz；CS 两帧高电平间隔 **9.375 µs**，第二帧 CS 建立时间 **9.417 µs**，两帧末钟到 CS 拉高分别约 **11.875/11.833 µs**。
- 首帧 CS 下降沿发生在采集窗口之前，因此**首帧 CS 建立时间未测得**。24 MHz 数字采样不能证明模拟边沿质量或纳秒级裕量。

## 4. 遇到的问题与处理

1. **“CRC”概念不符。** 先核源码和协议，将结论改为偶校验 + EF/ERRFL，主机测试覆盖全部 14-bit 地址和响应奇偶位；不宣传硬件 CRC。
2. **纯函数通过不代表 SPI 事务正确。** 增加可注入传输层和假设备，逐帧核对 `FFFF/C000`、EF→ERRFL→重试及失败保持旧值。
3. **驱动板 0 V 下 B trial 无串口响应。** SWD 只读确认 PC 落入 `Error_Handler`，电流零点仍为 0；启动零点校准需要有效电流采样中点，故这不是编码器新驱动的直接证据。随后在 U/V/W 断开绝缘、板端 12 V 与 CTRL_SD 检查后完成 B 启动和确认；进入 `ANALOG SAFE` 才做静态诊断。
4. **第一次逻辑分析仪探头/解码映射不一致。** 最终实际映射为 `D0=CS、D1=SCK、D2=MISO、D3=MOSI`，mode 1 即 CPOL=0、CPHA=1；最初的低采样率也调为 24 MHz。用原始 `.sr` 再算边沿，避免只凭截图估时。
5. **两笔 RAW 不能混比。** 串口先后返回 3158 和 3155；本次保存波形的第二帧 `0x0C53` 对应 3155。相邻角度数值略变不是解码错误。

## 5. 复现与安全操作

主机测试和固件离线编译，在工程根目录执行：

```powershell
cmake --build .\tests\as5047p_host\out
ctest --test-dir .\tests\as5047p_host\out --output-on-failure
cmake --build .\foc2_app_a\build\Debug -j 4
cmake --build .\foc2_app_b\build\Debug -j 4
```

串口诊断命令的数字只是请求 ID，可换成未使用的编号：

```text
2000 FW STATUS
2001 ENC DIAG
2002 ANALOG SAFE STATUS
2003 ENC SAMPLE
```

`ENC SAMPLE` 只有在 `ANALOG SAFE LATCHED=1 SD=0 MOE=0 FOC=0` 时才被允许；它不启用桥臂。SAFE 锁存会在 MCU 复位后消失，而驱动板 0 V 时复位可能让启动电流零点校准失败。任何重新接线、断电或复位后的操作都必须重新核对**真实电源电压、输出安全状态和当前固件槽位**，不能沿用旧日志推断当前安全。

## 6. 知识点和未完成边界

- AS5047P 的响应有一帧流水线延迟；首帧 MISO `0000` 不代表本次角度为零。原码 `0x0C53 & 0x3FFF=3155`。
- DWT 是测微秒级整次事务的合适工具；`HAL_SPI_TransmitReceive(..., 10U)` 的 10 ms 是**每帧超时参数**，不是正常耗时。EF 六帧或 SPI 断线时，现有阻塞调用仍可能使 1 kHz 任务明显超期。
- `FREE_B=2168` 是已观察运行场景的 FreeRTOS 栈高水位，不覆盖所有中断、故障恢复和电机运动工况。转速更新仍用固定 `dt=0.001 s`，若调度丢周期可能带来估速偏差。
- 逻辑分析仪验证的是数字帧、频率和可见时序；磁铁偏心、角度精度、噪声裕量、模拟电流采样和功率级交叉导通需要其他测试手段。
- 本章可归档为**编码器数字通信阶段完成，附一次有限空载试转**。真实 EF/断线最坏延迟、高速旋转精度及带工件的 FOC/拧紧稳定性未验收；一次无故障运行不能证明第七章模拟尖峰已解决，不能把它当作后续反复通电试验的安全依据。

相关：[[第七章_设备自检与保护_Obsidian总结]] · [[STAGE8_1_AS5047P_HOST_TESTS]] · [[STAGE8_2_AS5047P_FAKE_SPI]] · [[STAGE8_3_AS5047P_TIMING_STACK_AUDIT]] · [[STAGE8_4_AS5047P_SPI_WAVEFORM]] · [[STAGE8_5_EMPTY_LOAD_RUNDOWN_SPI_RUNTIME]] · [[STAGE9_1_PWM_ADC_STATIC_TIMING_AUDIT]]。
