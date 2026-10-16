# Stage 6.1 — STM32G474 直接控制 RS485 继电器板

## 接线

- STM32 PC10 (USART3_TX) → 隔离 TTL/RS485 模块 RX
- STM32 PC11 (USART3_RX) ← 隔离 TTL/RS485 模块 TX
- STM32 3.3V/GND → 模块 Vin/GND
- 模块 RS485 A/B → 继电器板 A+/B-，两块板字母标法不同，先按 A 对 A、B 对 B；无响应时断电后交换 A/B 测试
- 继电器板由 12V 电源并联供电，通信开关设为 RS485
- 模块无 DE/RE 引脚，由模块自动切换收发方向

## 厂商协议（用户提供的指令图）

- 出厂地址：`0xFF` (255)，这是厂商约定，超出标准 Modbus 常用地址 1–247
- 出厂波特率：9600；串口校验位需按实际设备配置确认，当前第一试验采用 8N1
- 读 8 路继电器状态：`FF 01 00 00 00 08 28 12`
- 打开第 1 路：`FF 05 00 00 FF 00 99 E4`
- 关闭第 1 路：`FF 05 00 00 00 00 D8 14`
- 功能码 01 响应返回一个位图，bit0 对应第 1 路
- 功能码 05 的正常响应应逐字节回显请求
- 通信请求与响应均校验 Modbus CRC16（低字节先发）

## 本次代码

- 新增独立 USART3 PC10/PC11 的轮询式 Modbus RTU 诊断驱动，不触碰 COM5 所在 LPUART1
- 支持只读功能码 01/02（8 位）、03/04（1 个寄存器）
- 支持单路继电器 1～4 的功能码 05 ON/OFF，只有显式命令才会动作
- 应答检查地址、功能码、长度、CRC；功能码 05 再检查回显一致性
- 每次请求有界超时；只允许在电机 IDLE 且拧紧任务不忙时执行
- 命令入口在现有 Protocol V2：

```text
4000 MODBUS PROBE
4001 MODBUS PROBE 9600 255 1 0 N
4002 MODBUS RELAY 1 ON
4003 MODBUS PROBE
4004 MODBUS RELAY 1 OFF
4005 MODBUS PROBE
```

默认 `MODBUS PROBE` 等同 `9600 255 1 0 N`，应发出厂商的 `FF 01 00 00 00 08 28 12`。优先执行读命令，确认总线正常后才执行功能码 05。不要在继电器触点上接高压或负载做初次联调。

## 构建与当前验证状态

2026-09-24：

| 镜像 | 编译 | Flash | RAM |
|---|---|---:|---:|
| APP A | PASS | 215,884 / 229,376 B (94.12%) | 64,728 / 131,008 B (49.41%) |
| APP B | PASS | 215,572 / 229,376 B (93.98%) | 64,712 / 131,008 B (49.40%) |

在本地对手册示例校验 CRC：

```text
FC01 READ : 28 12  — 手册一致
FC05 ON   : 99 E4  — 手册一致
FC05 OFF  : D8 14  — 手册一致
```

初次尝试写 A 时，旧 B 的 `FW BEGIN` 返回 `ERR 105 FAULT`，没有开始擦写。当时 `STATUS` 为 `FLT=1 REASON=1`，源码中对应三相电流任一相超过 2.0 A 的软件保护。用户随后说明此前未开驱动板电源；恢复 12V 后故障仍锁存。通过 ST-LINK 软件复位，设备恢复 `MODE=IDLE FLT=0 REASON=0`，再执行升级。

最终板上结果：

| 镜像 | BIN CRC32 | 官方 Transfer 结果 | 启动/确认 |
|---|---|---|---|
| APP A | `0x7E79464F` | 215,884 B，6747 chunks，重传 0，`FW END` 校验通过 | `CURRENT=A CONFIRMED=A PENDING=- GEN=170` |
| APP B | `0xA1139676` | 215,572 B，6737 chunks，重传 0，`FW END` 校验通过 | `CURRENT=B CONFIRMED=B PENDING=- GEN=173` |

在 A 与 B 上分别发送 `MODBUS PROBE`，均得到：

```text
OK MODBUS READ ID=255 FC=1 ADDR=0 VALUE=0x0000 DEC=0 RX=6
```

这是经过地址、功能码、长度和 CRC 检查的 6 字节继电器状态响应；位图 `0x00` 表示各继电器当前关闭。B 上的 `STATUS` 为 `MODE=IDLE FLT=0 REASON=0`。

用户确认第 1 路 COM/NO/NC 触点没有接负载后，执行功能码 05 动作测试，并用功能码 01 交叉验证：

```text
3910 OK MODBUS READ ID=255 FC=1 ADDR=0 VALUE=0x0000 DEC=0 RX=6
3911 OK MODBUS RELAY=1 STATE=ON ACK=1
3912 OK MODBUS READ ID=255 FC=1 ADDR=0 VALUE=0x0001 DEC=1 RX=6
3913 OK MODBUS RELAY=1 STATE=OFF ACK=1
3914 OK MODBUS READ ID=255 FC=1 ADDR=0 VALUE=0x0000 DEC=0 RX=6
3920 OK STATUS STAGE=0 BUSY=0 MODE=IDLE FLT=0 REASON=0
```

用户确认第 2～4 路 COM/NO/NC 也均未接线后，逐路执行开、读回、关、读回：

```text
3941 OK MODBUS READ ID=255 FC=1 ADDR=0 VALUE=0x0000 DEC=0 RX=6
3962 OK MODBUS RELAY=2 STATE=ON ACK=1
3963 OK MODBUS READ ID=255 FC=1 ADDR=0 VALUE=0x0002 DEC=2 RX=6
3964 OK MODBUS RELAY=2 STATE=OFF ACK=1
3965 OK MODBUS READ ID=255 FC=1 ADDR=0 VALUE=0x0000 DEC=0 RX=6
3972 OK MODBUS RELAY=3 STATE=ON ACK=1
3973 OK MODBUS READ ID=255 FC=1 ADDR=0 VALUE=0x0004 DEC=4 RX=6
3974 OK MODBUS RELAY=3 STATE=OFF ACK=1
3975 OK MODBUS READ ID=255 FC=1 ADDR=0 VALUE=0x0000 DEC=0 RX=6
3982 OK MODBUS RELAY=4 STATE=ON ACK=1
3983 OK MODBUS READ ID=255 FC=1 ADDR=0 VALUE=0x0008 DEC=8 RX=6
3984 OK MODBUS RELAY=4 STATE=OFF ACK=1
3985 OK MODBUS READ ID=255 FC=1 ADDR=0 VALUE=0x0000 DEC=0 RX=6
3990 OK STATUS STAGE=0 BUSY=0 MODE=IDLE FLT=0 REASON=0
```

结论：STM32 → TTL/RS485 → 继电器板的读与 1～4 路开关控制均通过板上测试；每次只打开一路，结束时所有继电器关闭。测试脚本为 `tools/modbus_relay_smoke.ps1`。尚未测试带负载切换和长时间通信压力。

## 当前实现边界

这是一条可直接验证硬件的有界诊断路径。串口收发暂用低优先级协议任务中的 HAL 轮询，一次读超时最多约 180 ms；20 kHz ADC/FOC ISR 仍可抢占。后续需要连续轮询多设备时，应迁移到独立 ModbusTask 与 DMA/中断接收，并保持控制命令队列化。
