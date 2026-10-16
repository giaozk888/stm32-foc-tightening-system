---
title: 旧 UART 打印与 Pigweed 历史日志零拷贝——实现和验收边界
date: 2026-10-04
tags: [STM32G474, FreeRTOS, UART, DMA, Pigweed, 零拷贝, 面试项目]
status: 本地实现和软件验证完成，未刷写，实机待验收
---

# 旧 UART 打印与 Pigweed 历史日志零拷贝

## 先说结论

这次完成了两个改造：

1. 普通打印不再先生成一份完整字符串，再复制进 UART 队列。常量直接引用；运行时格式化直接写进最终 DMA 缓冲。
2. Pigweed 日志只生成一份最终文本。待发送、历史、dump、UART、CAN 日志缓存和 Router 日志缓存保存句柄，共享这份只读文本。

准确边界是“去掉这些缓存之间的 CPU 整条日志复制”，不是“全系统不复制”。旧兼容接口、Router 业务包构建、CAN 分片和格式化/编码仍有必要的数据写入。

本次只修改本地源代码、运行主机测试、生成 A/B ELF/BIN/HEX。没有刷写、复位、开串口/CAN 发送命令或电机动作；板上正在运行的固件未被替换。六个配置都保持 `CAN_CONTROL_REJECT_ONLY=ON`，没有新增运动权限。

## 1. 为什么旧接口不能直接改成指针队列

原来的接口允许这样调用：

```c
char message[64];
snprintf(message, sizeof(message), "value=%u\r\n", value);
UART_Async_Write((const uint8_t *)message, strlen(message));
/* 函数可能马上返回，message 的栈空间可能被下一次调用重用。 */
```

如果只是把 `message` 的地址放进队列，DMA 还没发完，原数据就可能消失或被改写。因此 `Write/WriteReliable/WriteString` 继续保留“一次复制”的兼容语义。

新代码有两种合法用法：

- 原生租约：先申请最终缓冲，在其中生成数据，再提交，完成后由发送任务归还。
- 受管理的只读引用：数据位于共享日志池，发送队列接管一份引用，DMA 完成或确认停止后才释放。

字符串常量可以直接引用，但仅限真正具有静态、不可变生命周期的存储。`const char *` 并不自动代表数据永远有效。

## 2. 普通打印迁移了多少

| 工程 | 常量调用 | 格式化调用 | 运行时实现 |
|---|---:|---:|---|
| A APP | 102 | 41 | `UART_SendLiteral` / `UART_SendFormatted` |
| B APP | 96 | 40 | 同上 |

这是源代码调用点数量，不是实机发送帧数。

`UART_SendLiteral` 使用 `UART_Async_WriteStatic`。`UART_SendFormatted` 使用 `UART_Async_VPrintf`，直接在最终缓冲中格式化；调用者原有数组只用于异步后端尚未启用时的阻塞启动回退。

普通日志保持不等待的 best-effort 行为；池满会失败/丢弃，不无限阻塞控制任务。原生格式化超出申请容量时取消提交，不发送截断字符串。启动阻塞路径仍按原来的 `vsnprintf` 界限处理。

协议回复中仍需保留临时调用者数据的兼容发送没有改成悬空指针。上一阶段已迁移的原生 PING、带标签回复、Router UART 帧生成继续使用原生租约。

## 3. 一份日志怎么同时给多个模块用

实现位于 `firmware_common/pw_log_store.c/.h`，A/B 后端共用 `pw_log_backend_impl.inc`。

```text
申请日志槽 → 在槽内格式化/编码 → Seal：内容从此只读
                                   │
           ┌────────────┬──────────┼───────────┬──────────┐
           ↓            ↓          ↓           ↓          ↓
         历史引用      待发引用    UART 引用    CAN 引用   Router 引用
           │            │          │           │          │
       覆盖/清空释放  任务用完释放  DMA结束释放  发完/过期释放 路由用完释放
           └────────────┴──────────┴───────────┴──────────┘
                         最后一份引用释放 → 槽可复用
```

日志池有 64 个槽，每个文本容量 192 字节，包含末尾 NUL；最长发送文本 191 字节，包含 CRLF。每个槽还保存序号、时间、级别、长度和引用控制字。ARM 链接映射中整个共享槽池为 13312 字节。

句柄 `PwLogRef` 是一个 32 位数字，包含槽号和代次。引用计数大于零时，槽不能重新分配。代次用于发现普通的陈旧句柄；会回绕，不能把它当永久唯一 ID 或安全认证机制。

### 最重要的使用规则

1. `Acquire` 后只有一个写者；失败路径必须 `Cancel`。
2. `Seal` 后绝不能再改文本或元数据。
3. `View` 只是查看，不会获得所有权；整个查看期间必须已经持有引用。
4. 异步消费者先 `Retain`，成功入队后队列接管它；入队失败立即 `Release`。
5. `UART_Async_SubmitReference` 成功时接管调用者的一份引用，失败时仍由调用者持有。
6. 每份引用只释放一次，最后一份释放后不得再看旧指针。

底层槽状态/引用计数使用 C11 32 位原子操作。ARM 反汇编确认有 `LDREX/STREX/DMB`，六个 ELF 没有 `__atomic/__sync` 帮助函数。FreeRTOS 队列、历史修改的短临界区和可选等待仍存在，不能宣称整个日志系统“全部无锁”或“wait-free”。ISR 中拒绝格式化日志，ISR 丢弃计数使用原子操作，不调用任务临界区 API。

## 4. 历史、dump 和 clear

待发送队列有 24 个四字节句柄；历史有 16 个句柄。历史覆盖时只释放旧历史的那份引用，不会影响 UART 或其他消费者正在使用的同一条日志。

`PW_Log_Dump` 在短临界区内保留最多 16 个历史引用，形成固定快照；随后在临界区外提交到 UART。每条最多等待 100 ms，不复制历史文本。期间其他任务清空或覆盖历史，快照内容仍然有效；没有成功提交的快照引用也会释放。

`PW_Log_Clear` 释放历史引用并重置诊断计数，不重置共享池，不清除仍在待发、镜像或 DMA 中的所有者。它不是“强制释放所有日志内存”的操作。

如果 DMA 超时，只有确认 HAL abort 成功且 DMA 已停下才释放引用。无法确认停下时，发送后端进入 fail-closed，保留在途/排队资源并拒绝重新初始化，避免 DMA 读取被复用的内存。这不是电机急停功能，也没有改变现有功率级控制。

## 5. CAN、Router 和 tokenized 日志

| 路径 | 本次去掉的复制 | 仍然存在的工作 |
|---|---|---|
| Pigweed 普通文本 | 临时 body、完整日志入队、历史保存、UART 再入队复制 | 最终缓冲中的格式化与截断 |
| Pigweed tokenized | 临时 Base64 字符串及整条日志在各缓存间的复制 | 上游 token/参数生成；同步编码到最终文本 |
| UART 实时日志及 dump | 共享文本到 TX payload 的复制 | 描述符/引用元数据发布、DMA 搬运到外设 |
| CAN 日志缓存 | 192 字节日志的重复缓存 | CRC、5 字节分片、8 字节帧组装/HAL 传输 |
| Router 日志缓存 | 重复缓存/临时去 CRLF 字符串 | `RouterPacket_t` 业务表示仍需复制、传输帧编码 |
| 远端 Router 日志打印 | 三次分开发送/兼容入队复制 | 将远端业务包文本写入一个最终 UART 帧 |
| 任意旧 `Write*` 调用 | 未去掉，保留生命周期兼容 | 一次调用者 payload 复制 |

CAN 日志队列深度仍为 8，保持最多两帧/100 ms 的预算及 10 秒过期丢弃规则；FIFO 忙时不阻塞，保留当前引用。发完、过期或无法查看记录时释放。帧 ID、CRC 和分片协议未变。

Router 日志队列深度仍为 8，只保存句柄和去掉 CRLF 后的长度。新增同步 `Router_SendSpan`，允许在不写临时去尾数组的情况下传递这段文本。随后 Router 仍构建自己的业务包；不存在“Router 从日志到网络全程零拷贝”的承诺。路由失败、级别过滤、订阅过期或没人接收后也必须释放队列引用。

`[PW]` / `[PWT]` 前缀、token Base64 形式、日志级别与序号字段保持兼容。瞬态 token 输入在回调返回前完成编码，不保存上游临时指针；测试实际链接仓库内 Pigweed 的 Base64 实现，而非自写模拟编码器。普通日志取消旧的 128 字节 body 中间数组后，正文可使用最终 192 字节槽内剩余空间；依然预留 CRLF/NUL，并不保证截断点恰好是 UTF-8 字符边界。

## 6. 代价与诊断

共享缓存需要管理引用，并且慢消费者会占住旧日志。UART 引用描述符暂时复用现有 32 块 TX 池，每个引用消耗一个 256 字节块的名额；块内不复制日志，但这个名额不能同时给普通大帧用。这是当前实现的明确容量代价。

日志池满时拒绝新记录，不覆盖仍有人读取的旧记录。共享并不保证不丢日志。

- `PW_Log_GetDiagnostics` 新增 `pool_used`、`dropped_pool`，其他队列/丢弃计数保留。
- `UART_Async_GetDiagnostics` 新增 `shared_frames`，包含受管理引用和静态字符串引用。
- `copied_bytes` 只统计兼容 UART 发送复制，不统计 Router 业务复制、CAN 分片或编码写入；不能拿它当全系统复制量。
- 后端 `sent` / dump 返回数量仍是成功提交给 UART 的条数，不是 DMA 已完成，更不是远端收到并确认。

这次未扩展 `LOG STATUS` 的线上字段；新字段通过 C 诊断接口读取，需要调试/诊断构建或后续明确扩展协议。不同计数的读取不是全系统一致快照。

## 7. 已执行的软件验证

2026-10-04 在本机完成：

- `tests/uart_zero_copy_host` 八组测试连续十轮通过，无失败。
- 共享池压力：四生产者、单消费者，每轮 60000 条，共 600000 条；检查每个生产者的 FIFO、文本/元数据、精确 payload 指针和最后所有者释放。消费者模拟 DMA 持有期间，生产者持续覆盖各自历史引用。
- A/B 真实 UART 和 Pigweed 适配器，配合模拟 HAL/FreeRTOS：历史/dump/clear、池满、待发满、镜像满、CAN 忙/过期、路由失败/过滤/过期、ISR 拒绝、token 临时输入、真实 Base64 容量失败、远端日志帧。
- DMA 完成、确认 abort、不能确认 abort：检查引用回收或故障固定，不出现提前复用。
- A/B 真实 Router：非 NUL span、去 CRLF、边界长度、旧 Text API、ASCII 帧及失败路径兼容。
- `check_scope.ps1` 通过：保留全部格式参数和非打印主程序代码，沿用前一阶段的 UART 范围检查；A/B 共享适配器一致。
- 现有 HMI 解 token 的四项 Python 测试通过；现有安全联锁和网络契约主机回归各一组通过。

这里的并发压力是纯软件池/队列测试；适配器故障测试使用确定性模拟和交错点，并非真实 DMA、多任务抢占时序或电机负载下的硬件实测。

### 六个 Release 编译配置

| 配置 | Flash 使用 | 链接 RAM 使用 | 结果 |
|---|---:|---:|---|
| A / UartZeroCopy / 115200 | 158004 B | 78752 B | 通过 |
| B / UartZeroCopy / 115200 | 157100 B | 78736 B | 通过 |
| A / UartZeroCopySafety | 40932 B | 54304 B | 通过 |
| B / UartZeroCopySafety | 40836 B | 54304 B | 通过 |
| A / UartZeroCopy2M | 158004 B | 78752 B | 通过，非 2M 实机验收 |
| B / UartZeroCopy2M | 157100 B | 78736 B | 通过，非 2M 实机验收 |

224 KiB 槽大小不变。普通 A/B 链接 RAM 相比上一阶段增加 2504 字节；安全配置增加 384 字节，日志池在该配置被链接器裁掉。链接 RAM 数字包含静态段和链接脚本预留，不是运行时堆/栈峰值。

普通固件仍有原有未使用变量/函数警告；项目自有主机测试使用 `-Wall -Wextra -Werror -pedantic`。编译器 `.su` 中日志任务自身帧为 40 字节、dump 为 96 字节；这不是包含 libc/被调用函数在内的完整任务栈实测。

### 重跑，不连接设备

在项目根目录 PowerShell 执行（工具路径按本机实际环境）：

```powershell
$env:PATH = 'D:\Qt\Tools\mingw1310_64\bin;D:\software\ninja;' + $env:PATH
& 'C:\Program Files\CMake\bin\cmake.exe' -S tests/uart_zero_copy_host -B tests/uart_zero_copy_host/build -G Ninja '-DCMAKE_C_COMPILER=D:/Qt/Tools/mingw1310_64/bin/gcc.exe' '-DCMAKE_CXX_COMPILER=D:/Qt/Tools/mingw1310_64/bin/g++.exe' '-DCMAKE_MAKE_PROGRAM=D:/software/ninja/ninja.exe'
& 'C:\Program Files\CMake\bin\cmake.exe' --build tests/uart_zero_copy_host/build
& 'C:\Program Files\CMake\bin\ctest.exe' --test-dir tests/uart_zero_copy_host/build --output-on-failure --repeat until-fail:10
& 'tests/uart_zero_copy_host/check_scope.ps1'
```

## 8. 仍需实机验收

后续刷写前重新确认机械隔离、现场许可及选用的槽/安全配置，不能复用之前的供电/动作授权。本次实现不替代实体急停或独立功率反馈验收。

先在 115200 下验证启动诊断、PING、普通日志、Pigweed 实时/dump/CAN/Router 内容与丢弃计数，再测最长通信服务延迟、实际堆/栈峰值、FOC ISR 负载和背压。2M 需要发送接收双方匹配、误码/吞吐/长时间压力的单独验收，当前不能写“2M 零丢包”。

原文件备份：[20261004_shared_log_zero_copy](<D:/new project/refactor_backups/20261004_shared_log_zero_copy>)。恢复先核对具体差异，不直接整目录覆盖其他修改。

## 9. 面试可用的表述

> 我把主串口改成固定池和 MPSC 发布队列，新发送直接在 DMA 最终缓冲中生成帧。随后把旧普通打印迁移为常量引用或原位格式化，并把 Pigweed 的历史、待发和各镜像缓存改成共享只读日志句柄。每个消费者独立持有引用，历史清空、dump 和 DMA 发送互不破坏生命周期，最后一个消费者结束才允许复用。无法确认 DMA 停止时固定住资源。保留需要复制的旧兼容接口，也明确区分 Router 业务包和 CAN 分片的必要复制。软件并发/故障测试和六个固件配置已通过，尚未刷写，实机 2M 压力验收仍待做。
