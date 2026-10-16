---
title: 协议回复改成 DMA 原位发送——2026-10-07
date: 2026-10-07
tags: [STM32G474, UART, DMA, 零拷贝, 所有权]
status: 本地修改和测试通过，未刷写，板上仍为原固件
---

# 这次改了什么

STATUS、自检、GET/SET、PARAMS 列表、Modbus 回复、Router 文本诊断、BOOT/FW 状态、IAP 应答和故障快照：在**原始 UART、RTOS 异步后端已启用**时，不再先生成完整栈字符串，再复制进发送池。

```text
旧：snprintf(临时数组) → WriteReliable → memcpy(发送池) → DMA
新：申请发送池 → 在池内格式化 → Commit → DMA → 完成后归还
```

这里的“零拷贝”只指去掉已生成应答到 TX 池的额外 CPU 整包复制。格式化仍会写数据，DMA 仍会传输数据；它不等于从业务层到云端全链路零拷贝。

## 如何保持安全

一般格式化应答使用 `Protocol_SendFormatted`，具体分派放在共享的 `protocol_tx_format.h`，A/B 行为一致。当前 main.c 各有 71 处这个格式化入口的实际调用，包含原来已原位发送的 PING/错误回复。

- 原始 UART 运行期：`UART_Async_VPrintf` 直接生成在租约缓冲中，最多等待 250 ms 申请空间。
- Router 回复：仍同步生成到有界 fallback 数组，由原有 `Protocol_SendString` 分行并交给 Router；保留目的节点和回复语义。它仍有业务包复制，不宣称全 Router 零拷贝。
- 启动早期：保留原阻塞路径，临时数组在发送返回前始终有效。
- 原位路径失败：返回失败，不偷偷改走阻塞 UART，也不借用栈指针。
- 格式化超出容量或为空：不发布残缺应答，释放未提交租约。Router/启动 fallback 也拒绝截断。

`FAULT SNAPSHOT/FILTER` 需要先检查长度，再决定发正常回复还是错误回复，因此使用共享的 `ProtocolTxBuffer`。运行期 `snprintf` 的目的地址就是租约地址；检查失败先 Cancel，再尝试错误回复。Commit 成功后，描述符归 TX 任务所有，清空本地 builder 不会释放 DMA 正在读取的内存。

PARAMS 新增 `TightenParams_EmitAllFormatted`：传出格式和参数，而不是已经生成的栈字符串。18 个参数加首尾两行的顺序、字段和 CRLF 保持不变；旧 `EmitAll` 仍可供老调用者使用。

IAP 的 `FW BEGIN` 仍检查 `ack_queued`。队列申请失败时返回 0，原有 `Fw_ResetContext()` 清理半会话的分支保留。成功入队不代表接收方已经 ACK。

## 哪些仍保留复制

`UART_Async_Write/WriteReliable/WriteString` 的兼容语义没有修改：它们仍将调用者缓冲复制一次。尤其 `PW_Rpc_ProtocolSend(const char *line)` 接收的是外部模块已经生成的字符串，当前没有可转移的生命周期契约，不能直接异步引用它。

部分 ADC/并发诊断等模块仍先生成业务文本，再交给 tagged formatter；虽然不再用兼容 memcpy 入队，也不能据此说其文本从最初生成开始就完全零拷贝。Router 业务包、接收解析组装和其他串口/CAN 路径仍有各自的复制边界。

本次没有修改 TX 池、MPSC 发布队列、DMA 完成/异常归还机制、FOC/ADC 控制算法、IAP 分区地址、参数存储或电机安全联锁。

## 本地验证

UART 主机测试的 8 个测试连续重复 10 轮通过；参数模块的 2 个测试通过。测试不打开任何硬件端口。

- 真实 A/B UART 适配器：native 生成后，fallback 数组未被写入；native 计数增长，copy/copy_bytes 不增长。
- 受检 builder：生产者地址与 HAL DMA 接收的地址相同；提交后缓冲仍占用，完成后才归还。
- 300 字符 STATUS 跨两个 256 字节单元正常输出。
- 全池占用：IAP ACK 申请等待 250 ms 后失败，不触发 fallback，不发布假 ACK。
- 截断、空输出、ISR 调用、取消、重复提交、DMA 超时/终止失败、RX 覆盖/恢复均通过相应测试。
- 实际 PARAMS emitter：20 行全部进入 native DMA 队列；参数模块另与旧输出逐行比较一致。
- 范围检查：`tools/check_uart_protocol_native.ps1` 对照修改前备份，A/B 非 TX 代码不变；协议处理器控制/状态语句和 IAP ACK 成败分支保留。检查打印表达式之外的控制代码，不替代硬件验收。
- 两个新增共享头通过 clang-format 检查。固件构建仍有原有未使用变量/函数警告，不声称固件无警告。

| Release 构建 | Flash | 静态 RAM | 结果 |
|---|---:|---:|---|
| A / RouterTransferIsolated | 195628 B | 103688 B | 通过 |
| B / RouterTransferIsolated | 194756 B | 103672 B | 通过 |
| A / SafetyLocked | 40972 B | 54304 B | 通过 |
| B / SafetyLocked | 40876 B | 54304 B | 通过 |

RAM 是链接数字，不是运行期任务栈余量。未进行刷写、复位、串口命令、CAN 收发或电机动作，板上固件未改变；真实 DMA/FreeRTOS/FOC 并发仍需另行隔离验收。

## 重跑检查

```powershell
$env:PATH = 'D:\Qt\Tools\mingw1310_64\bin;' + $env:PATH
cmake --build tests/uart_zero_copy_host/build -j 4
ctest --test-dir tests/uart_zero_copy_host/build --output-on-failure --repeat until-fail:10
cmake --build tests/tighten_params_host/build -j 4
ctest --test-dir tests/tighten_params_host/build --output-on-failure
./tools/check_uart_protocol_native.ps1
python tools/format_code.py
```

主要修改前代码备份位于 `refactor_backups/20261007_uart_protocol_native`，包含 A/B main.c 和参数 emitter/header；不应整目录覆盖其他修改。
