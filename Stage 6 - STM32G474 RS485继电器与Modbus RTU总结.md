---
title: Stage 6 - STM32G474 RS485继电器与Modbus RTU总结
aliases:
  - 第六章 继电器与Modbus RTU
tags:
  - STM32G474
  - FreeRTOS
  - RS485
  - Modbus-RTU
  - 继电器
status: bench-verified-no-load
date: 2026-09-24
---

# 第六章：STM32G474 控制 RS485 继电器板

> [!success] 本章结论
> 已完成 STM32G474 → 隔离 TTL/RS485 模块 → 继电器板的点对点 Modbus RTU 通信。第 1～4 路分别通过 **ON → FC01 读回对应位 → OFF → 读回 0** 的无负载板上测试；无应答超时、请求排队和 USART3 RX DMA 也通过测试。这不等于完成了带负载安全联锁或长时间可靠性验证。

## 1. 硬件和通信路径

```mermaid
flowchart LR
    PC[PC / COM5] -->|ST-LINK 虚拟串口| LU[LPUART1 DMA]
    LU --> RT[RouterTask / ProtocolTask]
    RT -->|请求队列| MT[ModbusTask]
    MT -->|USART3 PC10/PC11| TTL[隔离 TTL→RS485 模块]
    TTL -->|A/B 差分线| RB[12 V 继电器板]
    RB -->|响应| TTL
    MT -->|完成队列| RT
    RT -->|原请求 ID / Router 来源| PC
```

| STM32/模块侧 | 连接 | 用途 |
|---|---|---|
| PC10 / USART3_TX | → 转换模块 RX | STM32 发出 RTU 请求 |
| PC11 / USART3_RX | ← 转换模块 TX | STM32 接收 RTU 应答 |
| 3.3 V、GND | → 转换模块 TTL 侧 Vin、GND | 给转换模块供电并提供 TTL 侧参考地 |
| 转换模块 A/B | → 继电器板 A+/B- | RS485 差分总线；按实物丝印核对 |
| 12 V 电源 | → 继电器板电源端 | 继电器线圈/板卡供电，不接 MCU GPIO |

- 使用继电器板的 **RS485 通信模式**。隔离转换模块自动控制收发方向，没有外露 DE/RE 引脚。
- COM5 是原有 ST-LINK 虚拟串口，用于 PC 下发 Protocol V2 命令；USART3 是 STM32 到继电器板的另一条串口。USB-RS485 小蓝棒是可选的 PC 直连调试工具，不在这条已验证的 STM32 路径中。
- 继电器输出端为 NC/COM/NO 触点，本章动作测试时这些触点**没有接负载**。通信成功不代表触点可直接安全切换实际设备。
- A/B 名称在不同厂商设备上可能不一致；“交换 A/B”仅是断电、核对供电和波特率后的排查手段，**没有证据表明本项目最终必须交换过 A/B**。

## 2. 先读懂厂商协议

继电器板出厂地址为 `255 (0xFF)`、默认波特率 `9600`。本次按实测采用 `8N1`。地址 255 是厂家约定，不属于常规 Modbus 从站地址 1～247；驱动特意允许 255，同时允许 1～247 以便诊断其他地址。

| 操作 | 功能码 | 原始 RTU 帧（含 CRC16 低字节在前） | 验证重点 |
|---|---:|---|---|
| 读 8 路继电器状态 | 01 | `FF 01 00 00 00 08 28 12` | 返回位图；bit0～bit7 对应第 1～8 路 |
| 打开第 1 路 | 05 | `FF 05 00 00 FF 00 99 E4` | 正常应答须原样回显请求 |
| 关闭第 1 路 | 05 | `FF 05 00 00 00 00 D8 14` | 再用 FC01 读回确认关闭 |

源码在本地核对过这三帧的 CRC。当前诊断命令可读 8 位状态，但**只允许显式控制第 1～4 路**，不应误认为第 5～8 路已实现控制。

## 3. 实际实施顺序

### Stage 6.1：先把最小通信链路跑通

1. 核对继电器板 12 V 供电、RS485 模式、模块 TTL 侧 3.3 V/GND、PC10→RX、PC11←TX、A/B 对应；先不接触点负载。
2. 新增独立 USART3 驱动，不改 COM5 的 LPUART1，也不改 20 kHz FOC 中断。首先实现只读 `MODBUS PROBE`：构造请求、CRC16、按地址/功能码/长度/CRC 检查应答。
3. 默认命令读取 8 路位图：`4000 MODBUS PROBE`。A/B 槽实测均得到 `VALUE=0x0000 RX=6`，说明继电器当时全部关闭且应答通过校验。
4. 在用户确认 NC/COM/NO 均不接负载后，才加入功能码 05 的 `MODBUS RELAY <1..4> <ON|OFF>`。每次只开一路，立即读回对应位，然后关闭并读回 `0x0000`。第 1～4 路预期位图分别为 `0x0001/0x0002/0x0004/0x0008`。
5. 加入电机 IDLE、拧紧任务不忙的前置检查和有界超时。此阶段 USART3 收发还是 HAL 阻塞轮询，适合最小硬件验证，不适合持续多设备通信。

### Stage 6.2：把 Modbus 等待移出 ProtocolTask

最初的直连实现会让处理 COM5 命令的 ProtocolTask 等待继电器应答。为避免无应答时拖住其他命令，加入专属 `ModbusTask`（低优先级）、深度均为 4 的请求队列和完成队列：

```text
ProtocolTask 入队（带原请求 ID / Router 回复目的地）
    → ModbusTask 串行操作 USART3
    → 完成队列
    → ProtocolTask 使用原请求 ID 回包
```

入队和执行前都检查电机状态；队列满时立即报错。`MODBUS STATS` 报告提交、完成、失败、队列满、超时和 CRC 错误。用不存在的从站 ID 247 制造约 150 ms 超时，同时发送 `PING`：实测 `PING` **先**回复，超时结果随后到达，证明 ProtocolTask 不再被 RTU 等待堵住。注意这时底层仍是阻塞 UART，只是阻塞被隔离到低优先级任务。

### Stage 6.3：USART3 接收改为 DMA

把回复接收改为 DMA1 Channel 3 / DMAMUX USART3_RX。每次**先启动 16 字节循环接收，再发送 8 字节请求**，防止继电器应答太快导致首字节丢失。ModbusTask 每 1 ms 查看 DMA `NDTR` 并让出 CPU，收齐当前支持的 5～8 字节应答或约 150 ms 超时后，调用 `HAL_UART_AbortReceive()` 清理，再处理下一请求。

LPUART1 的 TX/RX DMA1 Channel 1/2 保持不变；USART3 TX 仍是短帧阻塞发送，没有 TX DMA。这里是“**RX DMA + 任务轮询 NDTR**”，不是全中断异步串口，也不是通用的任意长度 Modbus 主站。

## 4. 遇到的问题与处理

| 已发生的问题或设计风险 | 查到的原因或证据 | 处理及经验 |
|---|---|---|
| 初期通信/升级排查时驱动板未开电源，随后 `FW BEGIN` 报 `ERR 105 FAULT` | `STATUS FLT=1 REASON=1`；对应已有的约 2.0 A 相电流软件保护，故障保持锁存。断电与保护触发的因果关系尚未单独验证 | 恢复供电后并不会自动清故障；用 ST-LINK 软件复位，复查 `MODE=IDLE FLT=0 REASON=0`，再升级和测 Modbus。不能把“供电恢复”当作清故障操作。 |
| APP 试运行/复位后第 1 路仍读回 `0x01` | 继电器板保持了之前的 ON 状态，MCU 重启不保证继电器复位 | 在无负载条件下显式发 `MODBUS RELAY 1 OFF`，再用 `MODBUS PROBE` 读回 `0x0000`。将来接真实执行机构必须另做掉电安全与急停联锁。 |
| 想测试超时时用了从站 ID 254，却得到参数错误 | 驱动只接受 1～247 或厂商专用 255；254 被输入校验拦下，根本没有发送 RTU 帧 | 改用总线上不存在的合法 ID 247，才测到真正的 150 ms 无应答超时，并确认后续对 ID 255 的正常请求仍可工作。 |
| 设计风险：阶段 6.1 的无应答等待会占住 ProtocolTask | 底层 HAL 阻塞收发位于协议任务上下文 | 阶段 6.2 建 ModbusTask + 两个有界队列；PING 超过等待中的 Modbus 超时回复，证明通信隔离生效。 |
| 设计风险：若接收准备晚，可能错过应答首字节；未记录实际丢首字节故障 | 继电器短帧响应可能紧随请求结束 | 阶段 6.3 在发送前先布置 RX DMA，等待时每 1 ms 让出 CPU；超时/错误后中止 DMA 并重新准备下一笔。 |
| 阶段 6.3 的 A 槽复位后第一次 COM5 查询超时 | 第二次查询成功且 A 槽已自动确认；现有证据不能确定是启动窗口还是串口时序 | 先等待启动完成再重查 `FW STATUS`；不能把一次查询超时直接判成 Bootloader 回滚，也不声称根因已经查明。 |

> [!warning] A/B 无响应的排查顺序
> 先查继电器板电源和模式、转换模块 TTL 侧供电及 RX/TX、串口参数、A/B 丝印与接线，再看 `MODBUS STATS` 的 TIMEOUT/CRC/UART 计数。确有需要时断电后试换 A/B；本项目记录**没有**证明曾以交换 A/B 修复故障。

## 5. 板上验证与阶段结果

| 阶段 | 主要验证 | 阶段末 A/B 镜像占用（历史值） |
|---|---|---|
| 6.1 | A/B 均能读回 `0x0000`；1～4 路逐路 ON/读回/OFF/读回；最后全关 | A Flash 215,884 B；B 215,572 B |
| 6.2 | A/B 均通过请求排队、PING 超时超车、继电器 1～4 路无负载动作测试 | A Flash 217,180 B；B 216,860 B |
| 6.3 | A/B 均通过 RX DMA、无应答恢复、1～4 路动作；B 连续 25 次只读均为 `0x0000` | A Flash 217,100 B、RAM 64,856 B；B Flash 216,780 B、RAM 64,840 B |

Stage 6.3 末历史 IAP 状态分别为 A `CURRENT=A CONFIRMED=A GEN=182`、B `CURRENT=B CONFIRMED=B GEN=185`，均 `PENDING=-`；完整镜像 CRC32 校验通过、无重传。**这些是第六章当时的记录，不是当前 Stage 7 运行槽或当前镜像内存占用。**

典型测试回包：

```text
MODBUS PROBE → VALUE=0x0000
MODBUS RELAY 1 ON → ACK=1
MODBUS PROBE → VALUE=0x0001
MODBUS RELAY 1 OFF → ACK=1
MODBUS PROBE → VALUE=0x0000

不存在的 ID 247：MODBUS TIMEOUT
同时下发 PING：PING 先返回 PONG
```

## 6. 复现命令与安全边界

在 COM5 串口助手中，以 115200 8N1 发送带请求号的文本命令：

```text
4000 MODBUS STATS
4001 MODBUS PROBE
4002 MODBUS PROBE 9600 255 1 0 N
```

以下会**真实改变继电器触点状态**，仅在确认对应 NC/COM/NO 没接负载、设备为 `MODE=IDLE FLT=0` 时使用：

```text
4003 MODBUS RELAY 1 ON
4004 MODBUS PROBE
4005 MODBUS RELAY 1 OFF
4006 MODBUS PROBE
```

工程脚本（从项目根目录执行）：

```powershell
pwsh -NoProfile -File .\tools\modbus_async_smoke.ps1 -Port COM5 -ExpectedSlot A
pwsh -NoProfile -File .\tools\modbus_relay_smoke.ps1 -Port COM5
```

`modbus_async_smoke.ps1` 在发现 1～4 路已有 ON 状态时会发 OFF；`modbus_relay_smoke.ps1` 会逐路真实开关。因此**两者都不是纯只读脚本**，运行前必须确认触点安全。脚本结束会核对全关，但通信故障、板卡掉电或 MCU 复位时仍不可依赖软件保证触点状态。

本章未验证：带负载触点寿命、长时间压力、断线抖动注入、FOC ISR 抖动量化、完整 Modbus TCP/多设备通用主站。继电器控制是通信功能，不应替代独立硬件急停或功率级安全保护。

## 7. 源码和原始阶段记录

- `foc2_app_a/Core/Src/modbus_probe.c`、`foc2_app_b/Core/Src/modbus_probe.c`：USART3 初始化、CRC16、短帧请求/应答、RX DMA。
- `foc2_app_a/Core/Src/main.c`、`foc2_app_b/Core/Src/main.c`：Protocol V2 命令、队列、ModbusTask、完成回包。
- [[STAGE6_1_MODBUS_DIRECT]]：直连和第 1～4 路无负载动作验证。
- [[STAGE6_2_MODBUS_TASK]]：独立任务、队列与异步回复。
- [[STAGE6_3_MODBUS_RX_DMA]]：RX DMA 与板上回归。
- `tools/modbus_relay_smoke.ps1`、`tools/modbus_async_smoke.ps1`：自动测试过程。
