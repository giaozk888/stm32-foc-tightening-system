# Stage 5.6 — pw_transfer V2 分块、恢复与 A/B IAP

> 后续更新：Stage 5.8 已增加官方双向流端点
> `pw.transfer.Transfer/Write`。本章的 Unary
> `foc.Transfer/Exchange` 继续保留为恢复兼容回退接口。

## 本步范围

本步接入 Pigweed 官方 `pw_transfer::internal::Chunk` 的 V2 protobuf 编解码，
并在现有 `pw_rpc` Server 上建立一个最小可靠传输端点。

资源 1 是 512 字节 RAM 测试缓冲区；资源 2 连接现有的 inactive-slot Flash
writer。Flash 擦除、顺序写入、向量表检查、整镜像 CRC32 和 mailbox trial 提交
仍复用原 IAP 状态机。

## 数据路径

```text
PC transfer_smoke.ps1
  -> Protocol V2 ASCII HEX
  -> pw_rpc Server
  -> foc.Transfer/Exchange (Raw unary)
  -> pw_transfer Chunk::Parse
  -> RAM resource 1
  -> pw_transfer Chunk::Encode
  -> pw_rpc response
  -> UART DMA TX
```

## 已实现协议状态

- V2 `START`
- `START_ACK`
- `START_ACK_CONFIRMATION`
- `PARAMETERS_CONTINUE`
- `DATA`
- 错误 offset 时 `PARAMETERS_RETRANSMIT`
- 完成时 `COMPLETION/OK`
- session ID 检查
- resource ID 检查
- 最大分块 32 bytes
- 总容量 512 bytes
- 完成后的 CRC32
- resource 2：仅写非当前 APP 槽
- Flash 写入继续要求 32-byte 非末包和 8-byte 对齐
- 完整镜像校验通过后才允许 `FW END`

## 调试命令

```text
<ID> XFER STATUS
<ID> XFER RESET
```

状态字段包括：

```text
READY RESOURCE CAP ACTIVE SESSION OFFSET CHUNKS RETRANSMIT CRC32
SERVICE METHOD PROTO
```

## 自动测试

```powershell
cd 'D:\new project'
.\tools\transfer_smoke.ps1 -Port COM5
```

脚本执行：

1. RESET RAM transfer；
2. V2 START/START_ACK；
3. START_ACK_CONFIRMATION；
4. 写入第一个 32-byte chunk；
5. 故意发送 `offset=99`；
6. 确认 MCU 保持 `OFFSET=32` 并令 `RETRANSMIT=1`；
7. 从正确 offset 重发；
8. 验证最终长度和 CRC32。

实机结果：

```text
OFFSET=57
CHUNKS=2
RETRANSMIT=1
CRC32=0xAAACBD44
PW_TRANSFER SMOKE PASS
```

## 完整固件传输

```powershell
cd 'D:\new project'
.\tools\transfer_iap.ps1 -Port COM5 `
    -Image .\foc2_app_b\build\Debug\foc2.bin
```

流程：

```text
FW BEGIN（擦除非当前槽）
 -> pw_transfer START resource=2
 -> 32-byte DATA chunks
 -> XFER/FW offset 双重检查
 -> FW END 整镜像 CRC + vector 检查
 -> mailbox START_TRIAL
 -> Bootloader trial
 -> APP 5 秒健康门限自动确认
```

实机完整传输结果：

```text
SIZE=194276
CHUNKS=6072
RETRANSMIT=0
FW RX=194276/194276
CRC32=0x7AE0D24E
FW END ... COMMIT=BOOTLOADER ATTEMPTS=2 RESETTING
```

## 构建占用

```text
APP A: FLASH 194588 / 229376 bytes (84.83%), RAM 52800 bytes
APP B: FLASH 194276 / 229376 bytes (84.70%), RAM 52784 bytes
```

链接脚本和 A/B 地址未修改。

## A/B 实机结果

两个槽都完成 clean build、IAP trial、RPC/transfer 测试和自动确认。最终状态：

```text
CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0 GEN=143
```

FOC、KVS、Router、旧 Protocol V2 命令均保持正常。

## 当前限制与下一小步

这一步使用 pw_transfer 的标准 Chunk wire format 和恢复状态，但 RPC 方法暂时采用
Raw unary `foc.Transfer/Exchange`，而不是完整的官方双向 streaming Transfer service。

inactive-slot Flash Handler 已完成，并保留当前 `FW BEGIN/DATA/END` 作为回退路径。

下一小步是把 Raw unary `Exchange` 升级为 Pigweed 官方双向 streaming Transfer
service，并为长传输增加窗口扩展、超时定时器和 host 主动重试策略。
