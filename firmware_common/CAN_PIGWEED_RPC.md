---
title: CAN上的Pigweed只读RPC与官方历史日志导出
date: 2026-10-04
updated: 2026-10-05
tags: [STM32, Pigweed, CAN, RPC, Transfer, 日志, 鲁班猫]
status: 主机验证通过；MCU A/B已刷写并通过IAP验收，鲁班猫客户端与CAN导出实机待验收
---

# CAN 上的 Pigweed 只读 RPC 与官方历史日志导出

## 现在做到了什么

历史日志导出已从项目自定义的 `foc.ReadOnly.ReadLogChunk` unary 拉取，改为官方 `pw.transfer.Transfer.Read` V2 双向流。STM32 使用真正的 `TransferService`、`TransferThread` 和只读 `Handler`；HMI 使用真正的 `pw::rpc::Client`、`pw::transfer::Client::Read` 与 `TransferThread`。

握手、窗口推进、偏移检查、数据重传和传输状态由上游引擎负责，不再由项目自写下载状态机代替。应用仍需提供日志 Reader、CAN 适配、容量限制、界面状态和文件保存。使用官方引擎不等于自动获得所有资源、并发或跨重启续传能力。

最初改造阶段仅修改源码、生成接口、编译和主机测试，没有操作设备。2026-10-05 后续已通过 UART IAP 将含新引擎的正常 A/B 固件写入 STM32，验证自动确认与健康失败回退，最终正常 B 已确认、驱动关闭锁存。详情见 [A/B 实机验收记录](../嵌入式实习面试笔记/13_AB升级实机验收_20261005.md)。**新客户端尚未部署到鲁班猫，CAN 历史导出与链路故障仍未实机验收。** 实时 CAN 日志、UART 升级路径、控制限制和 FOC 逻辑保留；没有发送电机运动指令。

## 用白话理解各层

| 层 | 负责什么 | 当前实现 |
|---|---|---|
| 日志资源 | 提供一份稳定的历史内容 | resource 3；最近最多16条 RAM 日志，引用冻结 |
| Transfer | 大份内容分块、窗口、重传、结束握手 | 官方 V2 Read；数据块最多32字节，窗口最多64字节 |
| RPC | 找到服务/方法，区分调用与双向流 | channel 2；官方 Server/Client；Transfer.Read |
| CAN 适配 | 把完整 RPC 包装进8字节帧 | 0x600 请求、0x601 回复；项目 START/DATA 分片与 CRC16 |
| HMI | 进度、取消、成功/失败、保存文件 | 只在可靠完成后用 QSaveFile 原子保存 |

CAN、RPC、Transfer 不是互相替代的技术。Transfer 不直接驱动 CAN，也不负责经典 CAN 的8字节分片。

```text
HMI按钮 → 官方Client.Read(3, Writer)
               ↓ 官方TransferThread + RPC Client
         UI线程限速发送CAN分片 0x600
               ↓
       STM32 MonitorTask接收/重组
               ↓ 静态请求队列
       ProtocolTask检查只读白名单 → RPC Server
               ↓
       官方TransferService → 独立TransferThread
               ↓
       HistoryHandler → 可Seek的冻结日志Reader
               ↓ RPC ChannelOutput / 静态响应队列
       MonitorTask限速发送CAN分片 0x601
               ↓
       HMI RPC Client → 官方TransferThread → Writer
               ↓
       数据完成 + 结束确认 → 原子保存.log文件
```

实时日志仍走原来的 0x680 / 0x681 / 0x682，不改成 RPC 轮询。

## 原实现与现在的区别

| 项目 | 之前 | 现在 |
|---|---|---|
| 历史 RPC | 自定义 ReadLogChunk unary | 官方 Transfer.Read 双向流 |
| MCU传输状态机 | 项目 PwLogReadSession | 上游 Context / ServerContext / TransferThread |
| HMI传输协议 | 项目编码和逐块拉取 | 上游 RPC Client + Transfer Client |
| 重传读取 | 应用按offset重新取片 | 官方重传流程调用 SeekableReader |
| 大小/并发 | 最近16条，一次一份 | 同样有限额，不因引擎升级而无限扩大 |
| UART固件升级 | 受限的项目会话实现 | 本次未迁移，仍保留原行为 |
| 跨复位续传 | 不支持 | 仍不支持 RAM 历史的跨复位续传 |

旧的 `pw_log_transfer_readonly.h`、`log_transfer_wire.h` 和 `tests/can_rpc_host/rpc_test.cpp` 保留为源码对照，已注明历史用途，当前构建不使用它们。旧 ReadLogChunk 方法在新的 CAN 白名单中被拒绝。

**兼容性：新 HMI 与新 STM32 固件必须配套。** 普通四种查询保留，但旧 HMI 的历史导出协议不能与新固件混用。

## 日志 Reader 与 Handler 怎么工作

开始读取时，`PrepareRead()` 调用 `PW_Log_HistorySnapshot`，给最近最多16条 sealed 日志增加引用，按旧到新的顺序冻结。每条文本最多191字节，所以最多3056字节。

`HistoryReader` 将这些独立记录视为一个连续的只读字节流：

- `Read()` 从当前位置跨记录复制本次请求的字节，并推进位置。
- `Seek()` 在快照范围内调整位置，使官方引擎能重读丢失块。
- `Tell()`、可读上限和 `ResourceSize()` 告诉引擎当前位置与总大小。
- `FinalizeRead()` 在完成、取消、失败等清理路径释放快照引用。
- 非零起始偏移的新会话被拒绝：重启后不能重建上一份 RAM 快照。

导出期间，新日志覆盖历史表或清空历史，不会改写已冻结的 sealed 记录。完成、取消、空闲超时、链路重置和绝对期限清理都需要释放引用。主机测试在清空历史后仍逐字节核对导出结果，并在 ResetLink 之前检查引用是否已经归还，避免用链路重置掩盖泄漏。

日志池仍为64槽。冻结历史可能使新日志更早遇到池满；池满允许丢弃并计数，不覆盖被引用内容，不等待电机控制任务。

这是“快照不整份复制”，**不是端到端零拷贝**。Reader 切片、protobuf/RPC 编码、静态队列和 CAN 帧装载仍有数据复制。也不能把 FreeRTOS 队列或新互斥锁说成无锁队列。

## 官方 V2 流程与三个编号

```text
Start(resource=3, desired_session_id)
 → StartAck(session_id)
 → StartAckConfirmation(窗口参数)
 → Data(offset, data, remaining_bytes)
 ↔ ParametersContinue / ParametersRetransmit
 → Completion(status)
 → CompletionAck
```

窗口表示接收方允许发送到哪个 offset。服务端可以在窗口内连续发送；遇到缺块，客户端通过官方参数重传消息要求回到指定位置，Reader.Seek 后读出相同内容。

三个编号必须区分：

| 编号 | 生命周期 |
|---|---|
| RPC call_id | 关联一次 RPC 双向流；该流可以承载多个日志传输 |
| Transfer session_id | 关联一次日志传输会话 |
| CAN transaction | 关联一个完整 RPC 包的分片；每个新包都换号 |

CAN 适配保留重复完整包防护，不能让所有流消息共用同一个 transaction。现在普通 unary 使用 0x0001–0x7FFF，Transfer 流使用 0x8000–0xFFFF，并逐包递增。各方向独立计数；编号不提供身份认证。

## 两个容易踩坑的结束细节

### 官方完成回调不等于结束确认已经收到

当前上游引擎在开始结束握手时就可能调用完成回调。HMI 因此先记录结果，不立刻显示 Done。成功导出还要收到匹配 RPC 调用和会话的 CompletionAck，并排空本地发送队列，之后才保存文件、允许再次导出。

取消也通过官方 Handle.Cancel 发起，不自行拼另一套传输协议。收到服务端主动结束时，客户端发送的 CompletionAck 要排空发送队列；链路/流错误则显示失败。未完成的部分文件不按成功结果保存。

### 结束确认丢失的版本适配

项目锁定的上游版本在发送服务端 CompletionAck 后立即释放传输上下文；再次收到客户端 Completion 时，已没有原上下文替它重发 ACK。离线丢包测试确实暴露了这个边界。

CAN ChannelOutput 因此保留**最后一个已成功入队的官方 CompletionAck 包**，最多128字节、有效60秒。只对匹配 call_id、session_id、链路 epoch 的重复 Completion 重放，并分配新的 CAN 包号。链路重置或 RPC 流重新打开会清掉缓存。缓存不保存日志数据、不重复释放引用、不修改上游状态机。

这是一层小型幂等适配，不是重新实现 Transfer Manager。上游 `pw_transfer` / `pw_rpc` 引擎源码未修改。

### 异常 Chunk 先检查，再交给引擎

锁定的版本中，只有 session_id、没有 type 的 Chunk，或 Completion 没有 status 的 Chunk，可能通过上游 Parse；后续访问可选字段时会失败。带合法 RPC 外壳与 CRC 的随机输入测试发现了这个问题，不能仅依赖 CAN CRC 来防护。

两端现在用共享的 `transfer_chunk_validation.h` 先检查字段类型、重复字段、V2会话/类型/完成状态的必填关系，以及块、偏移、窗口的上限。非法包直接丢弃，合法包才进入官方引擎。这里只是入口校验，不处理窗口推进和重传。回归测试分别注入缺type、缺status的请求和回复，并确认显式status=0仍合法。

## 只读边界与资源配置

CAN Server 保留 `foc.ReadOnly` 的 Ping、GetStatus、GetParams、GetDiagnostics 四个 unary 方法。状态/参数是 RAM 观察，参数仍按既有18项顺序返回，不修改配方。

注册官方 TransferService 后，入口仍只允许 channel 2 上的 **Transfer.Read**，仅 resource 3、V2、零起始偏移、合法客户端流类型与限定窗口。不接受上传数据、Write、GetResourceStatus、资源2、旧 foc.Transfer.Exchange、旧 ReadLogChunk 或运动方法。

即使绕到 Handler，ReadOnlyHandler.PrepareWrite 也返回 PermissionDenied。不能把“生成的官方类里有 Write 方法”误解为“CAN 写入口已经开放”。

| 配置 | 数值/行为 |
|---|---|
| CAN | 经典 CAN，500 kbit/s；请求0x600，回复0x601 |
| 完整RPC包 | 最大128字节；START + 最多32帧DATA |
| 分片布局 | START: A1/事务号/长度/CRC16/版本；DATA: A2/事务号/片序号/4字节payload |
| CRC | 整包CRC16-CCITT，初值FFFF，多项式1021；不是密码学认证 |
| 重组期限 | 帧间空闲500ms；整包5s；重复START不延长期限 |
| 请求/响应队列 | 各4项静态队列，溢出计数且不等待 |
| HMI发帧 | 每帧至少75ms，由UI线程操作原CAN socket |
| MCU发帧 | 每100ms最多1帧，由MonitorTask操作HAL |
| 单个回复发送期限 | 4s，能覆盖最大128字节包的33帧限速发送 |
| 日志数据块/窗口 | 最多32字节/64字节 |
| Transfer缓冲 | chunk96字节，encode128字节 |
| MCU并发 | Thread<0,1>：0个客户端、1个服务端上下文；只注册一个日志资源 |
| HMI并发 | Thread<1,0>：1个客户端、0个服务端上下文 |
| 客户端超时/重试 | chunk与初始回复各8s；每阶段最多3次，整个会话最多12次重试 |
| 服务端空闲期限 | 30s，服务端不主动重试；重传主要由客户端驱动 |
| 绝对期限 | MCU与HMI均限制单次导出10分钟；MCU ProtocolTask推动毫秒时钟并回收 |
| 结束确认等待 | HMI最多60s，不收到确认不宣告成功 |
| 总线恢复/溢出 | epoch隔离旧响应；移除Handler终止旧会话，关闭/重开RPC通道后重新注册 |

实时日志与 RPC 仍共享总线，导出时可能延迟或丢弃。保留实时日志功能不等于保证一条不丢；实机要检查遥测序号、FIFO 和日志丢弃计数。读数也不能替代采样新鲜度、实机标定、实体急停和独立功率反馈验收。

CAN 控制仍被拒绝；旧 UART 控制逻辑保留。只读 API 不是物理断电，也不是安全认证。

## 线程、构建和实现位置

ProtocolTask 接收完整 RPC 请求；官方 TransferThread 处理流、Reader 与超时；MonitorTask 独占原 CAN HAL。新 CAN RPC profile 开启上游 RPC 全局 mutex，避免两个任务并发使用 RPC 对象。没有将传输、格式化或锁操作放进20kHz FOC ISR。

MCU Transfer 任务为 priority 1、静态1536个栈字，即6144字节。链接成功不是栈余量或实时性能的实机验收。HMI 后台线程只运行官方引擎和 Writer，所有 SocketCAN 发帧仍留在UI线程。

| 文件 | 用途 |
|---|---|
| official_log_transfer.h | 冻结引用、可Seek Reader、只读 Handler、绝对期限 |
| pw_rpc_can_readonly.inc | A/B共享官方Server/TransferService、线程、白名单、ACK重放 |
| pw_can_rpc.c/.h | 静态队列、epoch隔离、HAL所有者之间交接 |
| can_rpc_transport.c/.h、transfer_can_wire.h | 分片/CRC/重组与流包编号范围 |
| transfer_chunk_validation.h | 两端共享的受限V2字段检查，防止异常Chunk进入引擎 |
| pigweed_transfer.cmake | 上游引擎源码及FreeRTOS/STL后端接入 |
| pigweed_transfer_host.cmake | HMI使用的上游RPC/Transfer静态库 |
| generated/pw_transfer/*.h | 从锁定的官方transfer.proto生成的raw RPC与pwpb接口 |
| tools/generate_transfer_rpc.py | 可重复生成接口，不连接硬件 |
| lubancat_hmi/src/log_download.cpp | 官方Client.Read、Writer、进度、取消、完成确认与界面交接 |
| tests/can_rpc_host/official_transfer_test.cpp | 实际HMI客户端与实际A/B服务端的离线端到端测试 |

上游版本：`d6640a206bf18e78c3b965a03c71aabea67cf5b2`。生成脚本使用本地上游 codegen；本次在隔离的 `tmp/pw_transfer_codegen` 环境中安装 grpcio-tools / protobuf 并运行，重复生成的头文件 SHA256 一致。普通构建使用已保存的生成头，不要求每次安装 Python 依赖。

HMI 库和消费者统一使用 C++20，避免 pw::span / std::span ABI 混用；CMake最低3.12。已验证 Windows Qt6，**未验证鲁班猫上的 Linux Qt5 编译和运行**。

在 A 或 B 工程目录：
```powershell
cmake --preset CanRpcReadOnly
cmake --build --preset CanRpcReadOnly
```

默认 CAN_RPC_READ_ONLY 仍为OFF；既有 UartZeroCopy、UartZeroCopy2M、Safety 构建没有引入官方CAN引擎。固定224KiB槽及链接边界未改。

| 构建 | Flash | 链接RAM |
|---|---:|---:|
| A CanRpcReadOnly | 185484 B | 88632 B |
| B CanRpcReadOnly | 184588 B | 88608 B |
| A 原115200 / 2M profile | 158036 B | 78752 B |
| B 原115200 / 2M profile | 157132 B | 78736 B |

## 本次离线验证与实机待验

本次27项主机测试通过：CAN RPC 3项、HMI 12项、UART/共享日志8项、安全1项、参数/存储2项、控制协议1项。CAN端到端直接链接实际A/B服务和HMI官方客户端，RTOS、HAL、日志来源使用mock，不冒充实机。

覆盖最大3056字节逐字节导出、空日志、同一客户端连续导出、丢StartAck/数据块/CompletionAck、取消、链路重置、上游服务端超时事件、绝对期限及tick回绕、清空历史仍保持快照、资源/偏移/窗口/写入口拒绝、缺type/status的请求与回复。协议层有10万组随机输入；官方入口另有2万组随机RPC包和2万组包在合法RPC外壳内的随机Chunk。Flash及UART写入口调用计数保持0。

A/B新profile及原三个profile各完成构建；Windows HMI构建通过；作用域检查确认关闭RPC后main、既有RPC、CAN及运动/FOC/保护/IAP源码保持原逻辑；A/B共享接口一致。未改变已经运行的固件。

剩余验收：在新的现场隔离、刷写与复位许可下，配套更新非活动槽与Linux HMI；检查真正SocketCAN往返、真实历史内容、取消/断线/复位、触屏保存、任务栈余量、20kHz FOC实时性以及总线/日志丢弃计数。不能凭主机测试声称工业可靠性已验收。

改造前备份：`refactor_backups/20261005_official_transfer_read`；更早的CAN unary版本仍在 `refactor_backups/20261004_can_rpc_readonly`。没有Git提交或实机部署。
