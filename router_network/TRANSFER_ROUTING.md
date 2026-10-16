# Router 与官方 pw_transfer（2026-10-06）

## 到底支持了什么

Router 现在增加了 **通用二进制包转发通道**：不按日志、编码器或固件资源号解释中间包。
符合帧格式且不超过 1024 字节的二进制 RPC 包，都能按目的节点经过 UART、USB 虚拟串口、
ESP32 TCP 或鲁班猫/PC 的软件 Router 转发。大文件由 pw_transfer 分成许多小 RPC 包；
1024 字节是单个二进制包上限，不是整个文件大小上限。

“通用转发”**不等于“允许任意操作”**。STM32 本次只注册官方 `Transfer.Read`：

| 资源号 | 内容 | 本次边界 |
| --- | --- | --- |
| 3 | 固定历史日志快照 | 最多 16 条、3056 字节；传输期间持有记录引用 |
| 4 | AS5047P 最新已完成样本快照 | 固定 40 字节；状态、时间戳、原始角度、CRC32 |

没有网络 Flash Write、参数写入、电机控制或旧控制台入口。未来增加资源需要显式注册
Handler 并更新端点白名单；转发层本身不用为每种文件重写一套状态机。

## 分层与协议

`应用资源 → 官方 Transfer Client/Service/Thread → pw_rpc → R1 type 9 分片 → Router/端口`

保留旧 type 7 诊断、type 8 短只读 RPC。新 type 9 的负载格式为：

```text
XFER 32位包ID 16位偏移 16位总长 32位CRC HEX数据
```

数值固定长度大写十六进制；每片最多 88 字节，单包最多 12 片。整包 CRC32/IEEE 校验成功
才交给 RPC。接收端两块固定 1024 字节空间；支持乱序与重复，拒绝冲突片、错误长度、广播、
坏 CRC；不完整包从首片起 2 秒超时。没有动态扩容或无界重试。

官方 Transfer 负责握手、窗口、超时、重传、取消和完成确认。Router 不重写官方状态机。
STM32 当前引擎的 RPC MTU 是 128 字节、数据块 32 字节、窗口 64 字节、同时一条下载流。
1024 字节转发能力并不表示这个端点能接收任意 1024 字节 RPC 请求。

转发去重使用包 ID/偏移/CRC，而不是只看会在重连后复用的 R1 短序号。
主机进程启动时随机初始化传输包 ID。官方 call/session ID 与包 ID 是不同概念。
最终 ACK 仅短期缓存用于丢包重试；开始新请求或链接 epoch 改变时清理旧会话/缓存，
避免客户端重启后复用 call/session 1 时错误确认新文件。主机发送按每帧至少 75 ms 节流，
保留现有 TCP/ESP 流量限制，不通过放开限流来发送突发流量。

## AS5047P 的 CRC 在哪里

传感器 SPI 仍是 **奇偶校验 + EF + 14 位数据**。没有伪造 AS5047P 的硬件 CRC。
资源 4 是软件封装快照，采用小端格式：

| 偏移 | 内容 |
| --- | --- |
| 0、4 | `ENC1` 魔数、版本 1 |
| 8、12、16、20 | 样本序号、采样/完成/快照时刻（微秒、允许 32 位回绕） |
| 24 | AS_DMA 状态；非 0 不能当正常角度 |
| 28 | 原始角度低 16 位、SPI 响应高 16 位 |
| 32 | ERRFL、errfl_valid、recovered |
| 36 | 前 36 字节的 CRC32/IEEE |

只读 `AS5047P_DmaSnapshot` 在短临界区复制现有样本与时间，不进行 SPI 事务、不启动周期采样、
不更新控制心跳、不检查/改变截止时间。没初始化或没有已完成样本时返回不可用。
主机还要检查 `age_us`；“CRC 正确”不意味着角度新鲜、磁铁正常或采样状态正常。

## 使用

先做离线验证/编译：

```powershell
./tools/test_router_transfer.ps1
./tools/build_router_network.ps1 -Transfer
./tools/build_router_network.ps1 -Esp32 -Transfer
```

STM32 的 `RouterTransferReadOnly` 配置启用编码器 DMA 和 Transfer；
`RouterTransferSamplingReadOnly` 另外启用 ADC 双缓冲，默认 `UNCONFIRMED` 检测拓扑，功率启动
保持失败关闭。它不是未经电流检测硬件核对就可运行电机的固件。
新功能默认关闭，旧配置不会自动开启 Transfer。刷写/部署需要另外完成现场安全确认。

部署了新 STM32/ESP32 固件和鲁班猫软件 Router 后，才可使用：

```powershell
python -m router_network.transfer_client --usb-serial COM5 --resource 3 --output history-new.bin
python -m router_network.transfer_client --tcp 192.168.50.1:21000 --resource 4 --output encoder-new.bin
```

根据实际网关地址调整 TCP 参数。`--resource 4` 会校验样本文件 CRC 并打印时间/状态。
文件只能新建，不覆盖旧文件。主机工具使用本次编译的原生官方 C++ Client/TransferThread，
Python 只管连接与 Router 转发，没有另写一个“看起来像 Transfer”的 Python 状态机。
USB 虚拟串口驱动打开可能引起板级信号变化，不能保证所有硬件都绝不复位。

## 验收与限制

后续实机更新（2026-10-06）：已通过 PC→鲁班猫→Wi-Fi ESP32→UART STM32 的真实日志／
编码器下载；在专用隔离固件中同时运行约 20 kHz 原 FOC 数学计算和正式 FreeRTOS 双缓冲
统计任务。两客户端限流 80 次 RPC＋4 次 Transfer 通过，8 请求突发复测也通过；首次突发
第 4 轮曾超时，根因未确定。功率级始终关闭，这不是带载电机验收。
详见 [真实网络与并发验收](../ROUTER_TRANSFER_FREERTOS_FOC_ACCEPTANCE_20261006.md)。

以下是此前离线阶段的历史记录，不能把合成输入的主机回归当作实机证据。

已通过：A/B 真实 Router C 核心与官方 Client/Service/Thread 的主机端联调；1024 字节二进制
转发、3056 字节/空日志下载、握手/数据/最终 ACK 丢失重试、编码器快照 CRC、跨 TCP 转发及
客户端重启换资源；旧诊断与短 RPC 回归。主机日志/编码器输入是合成测试数据，不是实机测量。

已完成 ARM A/B 和 ESP32 编译。**尚未刷写、部署或验证实际 UART/Wi-Fi 链路**。
新 Transfer 线程静态栈 1536 字（6 KB）、低优先级 1；本机编译栈报告不等于实机最高栈深度验证。
ESP32 当前应用分区余量约 2%，未扩分区。

后续已补 ADC 双缓冲核心的限时隔离 SRAM 实测：7组共28,007对样本、109个完整块，
无丢块，停止并恢复原上下文通过。它没有部署本联合固件、运行完整RTOS或验证网络
Transfer，详见 [双缓冲隔离验收](../ADC_DOUBLE_BUFFER_ISOLATED_ACCEPTANCE_20261006.md)。

CRC、节点 ID、Router TTL 都不是鉴权。本通道只用于可信局域网，不应直接开放到公网。
CAN 当前仍使用原有独立通道；这次没有增加 SocketCAN Router 端口或 MCU 原生 USB CDC。
Transfer 数据及 ASCII 编码仍存在拷贝，不能称为端到端零拷贝。
