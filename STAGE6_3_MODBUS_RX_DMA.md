# Stage 6.3 — Modbus USART3 接收 DMA

## 改动

在 Stage 6.2 的独立 ModbusTask/请求与完成队列基础上，把 USART3 的回复接收从 `HAL_UART_Receive()` 阻塞轮询改为 `HAL_UART_Receive_DMA()`：

```text
ModbusTask → 启动 DMA1_Channel3 / DMAMUX USART3_RX
           → USART3 发送 8 字节请求
           → 每 1 ms 读取 DMA NDTR 并让出 CPU
           → 收齐 5/6/7/8 字节或 150 ms 超时
           → HAL_UART_AbortReceive 清理 DMA
           → 原有地址/功能码/长度/CRC/FC05 回显检查
           → 完成队列 → ProtocolTask 回包
```

DMA1 Channel 1/2 保持给 LPUART1 的 TX/RX，Channel 3 专供 USART3_RX。DMA 16 字节循环缓冲区覆盖当前支持的 5～8 字节响应。接收在发送前启动，避免响应过快而漏掉首字节；任务每次等待都 `vTaskDelay(1)`，不再忙等接收字节。USART3 TX 仍为 8 字节、约 8 ms 的阻塞发送，未改成 TX DMA。DMA 完成中断未启用，当前由低优先级任务读取 NDTR，故不能称为“全中断异步 UART”。

出错或超时会中止并清理 RX DMA，下一请求重新启动。无响应的 ID 247 返回 `TIMEOUT`，随后对有效 ID 255 的请求仍成功。原有 RTU CRC16、异常帧和 FC05 回显检查保持。

## 构建和板上结果

2026-09-24：

| 镜像 | FLASH | RAM | BIN CRC32 | 板上 IAP/trial |
|---|---:|---:|---|---|
| A | 217,100 / 229,376 B (94.65%) | 64,856 / 131,008 B (49.51%) | `0xD9BC323B` | `CURRENT=A CONFIRMED=A PENDING=- GEN=182` |
| B | 216,780 / 229,376 B (94.51%) | 64,840 / 131,008 B (49.49%) | `0x94BC3ADF` | `CURRENT=B CONFIRMED=B PENDING=- GEN=185` |

两槽编译通过，并经官方 pw_transfer stream IAP 升级，完整 CRC32 校验通过，重传 0，trial 自动确认。A 槽刚复位后第一次 COM5 状态查询曾超时；再次查询成功且已自动确认。尚未确定首次超时是启动窗口还是串口时序，后续上电/复位测试需观察。

在 A/B 两槽：

- `MODBUS PROBE` 读继电器位图，CRC 等校验通过，值为 `0x0000`。
- 向无设备的 ID 247 发起读取时，后发的 `PING` 先回复，随后得到有界 `MODBUS TIMEOUT`；之后有效设备读取恢复正常。
- 第 1～4 路分别 ON → FC01 读回 `0x01/0x02/0x04/0x08` → OFF → 读回 `0x00`，全部通过。
- 最终 `MODE=IDLE FLT=0`，继电器全部关闭。B 槽又完成 25 次连续只读请求，全部读回 `0x00`，`MODBUS STATS CRC=0 FULL=0`。

复测：

```powershell
pwsh -NoProfile -File .\tools\modbus_async_smoke.ps1 -Port COM5 -ExpectedSlot B
pwsh -NoProfile -File .\tools\modbus_relay_smoke.ps1 -Port COM5
```

## 边界

- 这只解决短帧 RX DMA 和让出 CPU；没有实现通用 Modbus 主站、长帧 DMA/帧间隔检测、多设备并发或 Modbus TCP。
- 没有做长时间压力、断线抖动注入、带负载触点测试，也没有量化 FOC ISR 抖动。
- 驱动板和继电器触点的安全联锁仍需按真实负载用途设计；继电器板可能保持最后一次开关状态，不能依赖 MCU 重启自动断开。
