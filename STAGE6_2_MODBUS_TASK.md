# Stage 6.2 — Modbus 独立任务与异步协议回包

后续 USART3 RX DMA 改造与板上测试见 [Stage 6.3](STAGE6_3_MODBUS_RX_DMA.md)。下文“仍为 HAL 阻塞轮询”描述的是 Stage 6.2 完成时的状态。

## 范围与架构

在 Stage 6.1 的 USART3 PC10/PC11 RTU 驱动上增加独立 FreeRTOS 任务。ProtocolTask 不再直接等待 HAL UART 收发：

```text
PC/Router → ProtocolTask → Modbus request queue (4)
                              ↓
                      ModbusTask (priority 0)
                              ↓
                   USART3 → RS485 → 继电器板
                              ↓
                    completion queue (4)
                              ↓
              ProtocolTask → 原请求 ID/原 Router 来源回包
```

- 现有 `MODBUS PROBE` / `MODBUS RELAY` 命令格式与成功应答保持不变。
- 请求保存 ID、功能码、参数和 Router 回复目的地；队列满则立即返回 `ERR 101 MODBUS_QUEUE_FULL`。
- ModbusTask 是 USART3 唯一使用者，串行处理请求；在任务执行前再次检查电机 IDLE/拧紧任务不忙。
- 回复在 ProtocolTask 中发出，避免跨任务访问其临时 Router 回复上下文。
- 新增 `MODBUS STATS`：提交、完成、失败、队列满、超时、CRC 错误及两个队列深度。
- 不改 FOC、20 kHz ADC ISR、Bootloader、Flash 布局、APP A/B 地址。

## 本次验证

2026-09-24，A/B 两槽 clean build 与增量 build 通过。编译器仍报告工程原有的未使用变量/函数告警，无新增编译错误。

| 镜像 | FLASH | RAM | BIN | CRC32 | 板上确认 |
|---|---:|---:|---:|---|---|
| A | 217,180 / 229,376 B (94.68%) | 64,760 / 131,008 B (49.43%) | 217,180 B | `0x936E7D58` | `CURRENT=A CONFIRMED=A PENDING=- GEN=176` |
| B | 216,860 / 229,376 B (94.54%) | 64,744 / 131,008 B (49.42%) | 216,860 B | `0x0EFDEE35` | `CURRENT=B CONFIRMED=B PENDING=- GEN=179` |

两槽均通过官方 pw_transfer stream IAP 升级，整包 CRC32 验证成功、重传 0，Bootloader trial 后自动确认。

```powershell
cmake --build .\foc2_app_a\build\Debug --clean-first -j 4
cmake --build .\foc2_app_b\build\Debug --clean-first -j 4
pwsh -NoProfile -File .\tools\transfer_iap_stream.ps1 -Port COM5 -Image .\foc2_app_a\build\Debug\foc2.bin
pwsh -NoProfile -File .\tools\transfer_iap_stream.ps1 -Port COM5 -Image .\foc2_app_b\build\Debug\foc2.bin
pwsh -NoProfile -File .\tools\modbus_async_smoke.ps1 -Port COM5 -ExpectedSlot B
pwsh -NoProfile -File .\tools\modbus_relay_smoke.ps1 -Port COM5
```

异步回归的关键观测：

```text
4103 OK MODBUS READ ID=255 FC=1 ADDR=0 VALUE=0x0000 DEC=0 RX=6
4105 OK PING PONG
4104 ERR MODBUS TIMEOUT ID=247 FC=1 BAUD=9600 RX=0 UART=0x0
4106 OK MODBUS STATS SUB=2 DONE=2 FAIL=1 FULL=0 TIMEOUT=1 CRC=0 RQ=0 CQ=0
```

对无设备的 ID 247 发起请求时，PING 先于约 150 ms 的 Modbus 超时回复，证明 ProtocolTask 没被 RTU 等待阻塞。A/B 上第 1～4 路逐路 ON、读回 0x01/0x02/0x04/0x08、OFF、读回 0x00 均通过。最终 `MODE=IDLE FLT=0` 且继电器位图为 0x00。

## 遇到的问题与边界

- A 首次试运行后读回 0x01，表示第 1 路当时仍 ON；在确认触点无负载的前提下显式发 OFF，并读回 0x00。不要把 APP 重启视为继电器自动断开的保证。
- 超时试验最初用了 ID 254，但本实现只接受 1～247 或厂商 ID 255，因此得到参数错误；改用未接设备的 ID 247 才测到实际 RTU 超时。
- 目前收发底层仍是 HAL 阻塞轮询，只是移到了优先级 0 的专属任务。**尚未实现 USART3 DMA/中断接收**，也未完成连续高负载通信压力、带负载触点寿命测试。
- 请求在入队和执行前检查 IDLE；这不是运行中状态变化的硬实时互锁。继电器若将来连接执行机构，须另设计掉电安全状态、联锁和独立急停。
- Flash 已用约 94.5%，后续功能须继续关注 A/B 镜像上限。
