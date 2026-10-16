# Stage 5.5 — Pigweed pw_rpc 最小移植

## 目标

在不改动 FOC 中断、Router 帧格式、A/B Flash 布局和 Bootloader 的前提下，
把真正的 Pigweed `pw_rpc::Server` 接入现有 STM32G474 + FreeRTOS 工程。

本阶段先验证最小闭环：

1. PC 生成 pw_rpc protobuf wire packet；
2. 现有 Protocol V2 / Router 使用十六进制文本承载该二进制包；
3. MCU 的 `pw_rpc::Server` 解码并查找 service/method；
4. Raw unary `Ping` 服务执行；
5. 回包保留 channel、service、method 和 call_id，并经 UART DMA 返回。

## 已加入内容

- A/B 两个 APP 都加入 `pw_rpc` common、server 和 raw server API。
- 服务名：`foc.Control`
- 方法名：`Ping`
- Channel ID：`1`
- 最大 RPC packet：`96` bytes
- Pigweed encoding buffer：`128` bytes
- 无动态内存；`PW_RPC_USE_GLOBAL_MUTEX=0`。
- 新命令：
  - `<ID> RPC INFO`
  - `<ID> RPC CALL <PW_RPC_PACKET_HEX>`
- 新测试脚本：`tools/rpc_smoke.ps1`

`Ping` 收到非空 payload 时原样回显；空 payload 返回 `PW_RPC_ALIVE`。

## 为什么使用 ASCII_HEX 传输适配层

现有 Router 和 Protocol V2 已经是稳定的行文本协议。直接改成 HDLC 或二进制 UART
会同时影响 Router、日志复用和 IAP，风险过大。因此 Stage 5.5 只在协议命令中承载
pw_rpc packet 的十六进制表示，pw_rpc 包本身仍是标准 protobuf wire format。

后续 `pw_transfer` 阶段再评估增加独立二进制/HDLC 通道；本阶段没有破坏旧命令。

## Host 测试

```powershell
cd 'D:\new project'
.\tools\rpc_smoke.ps1 -Port COM5
```

成功输出应包含：

```text
OK RPC READY=1 CH=1 ... RX=0 TX=0 ERR=0 TRANSPORT=ASCII_HEX
OK RPC ...
PW_RPC SMOKE PASS: request dispatched and correlated HELLO response returned.
OK RPC READY=1 ... RX=1 TX=1 ERR=0 TRANSPORT=ASCII_HEX
```

## 构建结果

```text
APP A: FLASH 191328 / 229376 bytes (83.41%), RAM 52240 bytes
APP B: FLASH 191016 / 229376 bytes (83.28%), RAM 52224 bytes
```

为了守住固定的 224 KiB 槽边界，仅 Pigweed middleware 使用 `-Os`；应用仍保持
Debug 构建。没有修改 linker layout、APP 地址或 A/B 槽大小。

## 实机结果

APP A 和 APP B 都完成了：

- IAP 写入 inactive slot；
- trial 启动；
- 5 秒健康门限自动确认；
- `RPC INFO` ready；
- Raw unary Ping 请求/响应；
- call_id 回显；
- `RX=1 TX=1 ERR=0`。

最终实机状态：

```text
CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0
```

## 知识点

- `pw_rpc` 不是 UART 驱动，它位于 transport 之上；ChannelOutput 决定如何发送包。
- service ID 是完整服务名哈希，method ID 是方法名哈希。
- Raw RPC 只跳过业务 payload 的自动 protobuf 编解码；RPC 外层仍是标准 protobuf。
- `call_id` 用于把异步响应与原请求关联。
- `ChannelOutput::Send()` 不应进入 FOC ISR；本工程仅在低优先级 ProtocolTask 调用。
- 小型 MCU 应先做 unary + 固定 buffer，再逐步增加 streaming/RPC services。

