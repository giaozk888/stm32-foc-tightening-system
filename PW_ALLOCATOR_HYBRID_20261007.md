---
title: 固定池和 pw_allocator 怎么在项目里配合
date: 2026-10-07
tags: [嵌入式, 内存管理, pw_allocator, UART, Router]
status: 代码与离线验证完成，未刷板
---

# 现在怎么分配内存

一句话：小而频繁的数据仍走固定池；中等长度、非实时的发送缓冲，以及日志导出期间的索引，交给真正的 `pw_allocator`。

本次修改 STM32 A、B 两份应用。不修改 bootloader、Flash 分区、热点、云端配置，不打开串口，不刷板、不复位、不发送运动指令。ESP32 不接入这套 FreeRTOS 分配器；它共用的 R1 编码函数只是抽取到公共文件，格式没有改变。

| 对象 | 现在放在哪里 | 为什么 |
| --- | --- | --- |
| UART 请求容量不超过 256 B 的缓冲、所有 TX 队列描述符 | 原 8 KB 固定池，256 B × 32 块 | 保留小消息、原子发布与有界队列 |
| UART 请求容量为 257～2048 B 的非实时缓冲 | 优先 `pw_allocator`，失败回退固定池 | 按请求长度分配，直接交给 DMA |
| 超过 2048 B 的 UART 请求 | 原固定池，沿用原容量限制 | 不让大消息挤占共享 RTOS 堆 |
| Router 发往 UART 的 R1 文本帧 | 按 `payload.length + 96` 获取 UART 缓冲 | 小帧走固定池，较大帧走动态缓冲；保持 R1/CRLF 格式 |
| 实时日志正文、历史日志记录和镜像队列 | 原固定日志池及引用队列 | 高频日志不用逐条 malloc，Clear 不误释放其他消费者的记录 |
| `LOG DUMP`、CAN/Router 官方 Transfer.Read 的历史索引 | `pw_allocator`，分配 `记录数 × sizeof(PwLogRef)` | 会话结束、取消、错误或超时后释放；只复制索引，不复制整份日志正文 |
| ADC 双缓冲、SPI DMA、FOC 数据和 Router 收发队列 | 保持现状 | 实时和固定尺寸对象不迁移；Router 队列仍复制有界 `RouterPacket_t` |

日志快照最多 16 条，因此动态索引最多 64 B。冻结索引前仍有一个短暂的栈上引用数组；这不是把整个日志系统改成动态分配。

# pw_allocator 实际用了哪块内存

调用关系是 `PW_Buffer_Allocate → GetFreeRtosAllocator().Allocate(Layout(size, 8)) → pvPortMalloc → heap_4`。

仍共享原来的 **40 KB FreeRTOS 堆**，不是新建了一个额外的 40 KB 池，也没有接管全部 SRAM、普通 `new`、`malloc` 或所有 STL 容器。

新增适配层约束如下：单次最多 2048 B；所有存活动态有效载荷合计最多 4096 B；最多 16 个对象；8 字节对齐。分配时检查剩余堆至少 4096 B，计入 heap_4 对齐和块头开销；若实际扣除后越过这个底线，就立即释放并报告失败。

这个底线是本适配层在分配当时的检查。其他直接调用 `pvPortMalloc` 的模块仍可能随后消耗堆，它不是整个系统永远有 4 KB 空闲的保证。

# 为什么 DMA 不会用到已经释放的内存

正常发送过程是：

1. 生产者取得一个固定池描述符，以及必要时分配的动态缓冲。
2. 直接在最终缓冲中格式化回复或 Router 帧。
3. Commit 把动态缓冲封为只读引用，再用原 MPSC 队列发布描述符。生产者此后不得读写、取消或释放它。
4. UART 发送任务把同一个地址交给 `HAL_UART_Transmit_DMA`。
5. DMA 完成，或者 HAL abort 成功且确认 DMA 已关闭后，TX 任务释放引用。最后一个引用释放时才调用 `pw_allocator.Deallocate`。

释放不在 DMA 中断中执行。中断只通知任务。

如果超时后 DMA 无法确认停止，就同时保留描述符和动态缓冲，关闭异步发送并拒绝重新初始化。这时内存会占着不释放，这是故障保护，不是正常的回收流程。

`WriteReliable` 等旧接口仍需把调用者的临时数据复制一次。换分配器不会让这个接口自动成为零拷贝。原生 lease 格式化路径没有新增 UART 入队载荷复制；日志 Transfer 的读取/序列化依然需要编码拷贝，不能称为整条网络链路零拷贝。

# 无锁和实时性怎么解释

固定池描述符的分配、MPSC 发布仍使用原子操作。动态缓冲的登记、引用计数和释放使用带优先级继承的静态 FreeRTOS mutex，所以**整个混合发送路径不是完全无锁**。

动态 API 只允许调度器正常运行、任务优先级为 0～2、非 ISR、非临界区且中断未屏蔽的上下文。FOC 和 Tightening 的高优先级路径不能调用它；中等 UART 请求若来自不允许的上下文，会尝试原固定池路径。

heap_4 分配/释放会短暂暂停任务调度。即便业务代码只在非实时任务调用，也可能影响高优先级任务被调度的时刻。**本次没有验证实机 20 kHz 截止时间或长期堆碎片**，不能据此声称“动态分配不会影响实时性”。

# 临时缓冲怎么用

普通非实时任务可以用下面的模式。必须覆盖所有错误出口，不能覆盖、复制一个尚未归还的 lease，也不能把它的地址交给异步消费者后直接 Cancel。

```c
PW_BufferLease scratch = {0};
if (!PW_Buffer_Allocate(bytes, PW_BUFFER_TEMP, &scratch)) {
    return 0;  // 由调用方处理背压或内存不足
}
/* 在当前任务中使用 scratch.data[0 .. bytes-1] */
(void)PW_Buffer_Cancel(&scratch);
```

如果需要异步共享，使用 Seal/Retain/Release，并明确哪个消费者持有引用。当前业务接入点是 UART/Router 输出与日志快照；`TEMP` 是供其他变长临时缓冲使用的受限 API，未做全工程逐对象迁移，也不负责替任意 C++ 对象运行析构函数。

# 怎么看运行状态

刷入新固件后，原 `ALLOC STATUS` 增加：`HYBRID`（是否启用）、`LIVE`（动态载荷字节）、`OBJECTS`、`PEAK`、`FAIL`、`CTX`（不允许的调用上下文），以及 `UART/LOGINDEX/TEMP` 分类字节数。

UART 的诊断结构增加 `managed_frames` 和 `managed_fallbacks`。内存不足时 UART 优先回退固定池；日志快照无法分配索引时撤销全部刚取得的日志引用，DUMP 返回 0，Transfer.Read 返回 ResourceExhausted，不泄漏日志记录。

注意状态是在生成回复之前取得的快照。回复自身随后也可能分配动态 UART 缓冲，不能拿单条状态中的 LIVE 值当成回复发送期间的全部内存。

正常配置默认 `PW_ALLOCATOR_HYBRID=ON`；`SafetyLocked` 和 `CanProbe` 强制关闭。显式关闭该选项可恢复纯固定池发送与固定日志索引，不改变线协议。

# 本次验收

离线测试使用仓库中的真实 Pigweed FreeRtosAllocator 和官方 Transfer 实现。宿主机 HAL、RTOS、底层堆为可控模拟；它们不是实机测试。

| 测试组 | 结果 |
| --- | --- |
| allocator 上下文、对齐、配额、块头预留、OOM、旧句柄、引用生命周期、并发 | 1/1；含 12000 次并发临时分配和 4000 帧混合 MPSC 引用发送 |
| UART 固定/混合后端、日志、Router 编码、取消/截断/超时/abort 故障 | 12/12 |
| CAN 官方 RPC/Transfer 历史下载、重传、取消、会话回收 | 3/3 |
| Router 官方 Transfer 历史下载、丢包重试、编码器资源、只读隔离 | 3/3 |
| 原 UART 官方固件 Transfer.Write 回归 | 12/12 |
| 原安全门禁和参数兼容回归 | 3/3 |

合计 34/34。正常回收后动态分配归零；无法停止的 DMA 故障用例则验证缓冲仍被保留。格式化检查通过，共 33 个允许列表文件。Docker 的 `--host-tests` 已纳入 allocator 和 UART 混合测试，本次未运行 Docker 容器。

A/B 编译通过，未改变 224 KiB 槽或 131008 B 可链接 RAM 边界：

| 配置 | A RAM / Flash（B） | B RAM / Flash（B） |
| --- | --- | --- |
| RouterTransferIsolated | 111792 / 201592 | 111776 / 200696 |
| Release | 86832 / 181292 | 86808 / 180396 |
| SafetyLocked | 54304 / 41100 | 54304 / 41004 |

RAM 链接占用已经包含原 40 KB 堆；动态载荷是在这块堆内部消耗，不能把它再算成额外可用 SRAM。编译仍有原 main 中未使用函数/变量警告，未作为本次内存修改扩大清理范围。

实机待验收：20 kHz 并发下的最大调度延迟、UART 吞吐和积压、长期空闲堆与碎片、不同 Transfer 会话并发时的配额行为。需要新的现场安全确认后才能刷写与运行。
