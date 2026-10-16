---
title: UART DMA 零拷贝改造——实现、边界与验证
date: 2026-10-03
tags: [STM32, UART, DMA, 零拷贝, 无锁队列, 面试项目]
status: 本地代码与测试完成，未刷写，实机待验收
---

# UART DMA 零拷贝改造

> [!important] 2026-10-07 协议回复更新
> STATUS、自检、参数列表、Modbus 回复、固件状态、IAP ACK 和故障快照的原始 UART 运行期路径已改为在最终 TX 缓冲中生成。旧 `Write/WriteReliable` 仍为安全复制兼容接口，外部模块传来的现成字符串不能直接借给异步 DMA。当前实现和本地验收见 [协议回复原位发送](<D:/new project/firmware_common/UART_PROTOCOL_NATIVE_TX_20261007.md>)；本次未刷板。

> [!important] 2026-10-04 后续更新
> 本文保留 10 月 3 日第一阶段记录及当时的构建数字。普通打印、Pigweed 历史/待发/dump 和 CAN/Router 日志缓存已完成后续共享引用改造；当前实现、复制边界与新验证结果见 [旧发送与共享日志零拷贝](<D:/new project/firmware_common/PIGWEED_SHARED_LOG_ZERO_COPY.md>)。下面“仍有日志历史/待发复制”的表述描述的是第一阶段，不代表当前本地源代码。

## 先说结论

按项目图片中“UART＋DMA＋无锁队列，多生产者单消费者”的方向，改造了 STM32G474 A/B APP 的 **LPUART1 主日志/命令串口**。

现在有真正的原生零拷贝发送接口：先申请最终发送缓冲，直接在里面生成数据，再把所有权交给发送任务。DMA 就读这块内存，发送完成之前不能再用它。

接收端去掉了 DMA 缓冲到软件环形缓存、再到临时接收数组的两次搬运，直接从 DMA 缓冲逐字节喂给同步解析器，并处理覆盖、残帧和串口错误。

这不等于整个项目从传感器到云端都零拷贝。旧接口、命令行组装、Router 业务包、Pigweed 日志历史和待发送记录仍有复制，见下面的边界表。USART1 的 ESP32 链路、CAN、USB-TTL 外部设备和云端代码没有因此自动变成零拷贝。

本次只改本地代码、运行主机测试、编译固件。没有刷写、复位、连接串口发送命令，也没有电机动作；板上现有固件没有被替换。

## 1. 前后到底差在哪

### 发送

旧路径：

```text
任务自己的数组 → memcpy 到 TX 环形缓存 → DMA 读取 → 串口
                     ↑ 用互斥锁保护多个发送者
```

新原生路径：

```text
多个任务申请缓冲 → 直接在最终缓冲生成数据 → 原子发布描述符
                                                 ↓
DMA 完成后归还缓冲 ← DMA 读取同一地址 ← 一个 TX 服务任务
```

少掉的是“把已经生成好的整包，再搬到发送缓存”这一步。格式化、编码仍需要 CPU；DMA 也仍然会把内存中的数据搬到 UART 外设。“零拷贝”指这里没有额外的 CPU 整包缓存复制，不是所有数据都不移动。

### 接收

```text
旧：UART → DMA 数组 → 软件 ring → rx_buf[64] → 行解析器 → Router 业务包
新：UART → 1024 字节 DMA 数组 → 同步逐字节解析器 → Router 业务包
```

解析器仍将字符组装成命令行，Router 仍保存/解码业务包。准确说法是“去掉接收传输层的中间缓存复制”，不是“接收到业务层完全不复制”。

## 2. 哪些调用已经使用，哪些没有

| 路径 | 当前实现 | 能否说传输层零拷贝 |
|---|---|---|
| `UART_Async_Acquire → 原位生成 → Commit` | DMA 使用原生产者缓冲地址 | 可以，原生发送路径 |
| `UART_Async_Printf/VPrintf` | 在最终 DMA 缓冲里直接格式化 | 可以，不先生成临时整包再入队 |
| 运行期 `Router_Uart1Tx` | 直接在租约缓冲编码，提前留 CRLF，不再 memmove/复制入队 | 可以，线缆帧生成到 DMA 之间 |
| 原始串口 `Protocol_SendTaggedLine/SendError`、PING 应答 | 运行期使用原生格式化接口 | 可以，最终应答生成到 DMA 之间 |
| `UART_Async_Write/WriteReliable/WriteString` | 保留兼容，调用者数据复制一次到池 | 不可以，仍是一次复制 |
| 普通 `UART_SendString`、当前 Pigweed 日志发送任务 | 仍调用兼容接口；日志历史/队列还有自己的复制 | 不可以宣称整条日志链路零拷贝 |
| `RouterTask → UART_RxDma_Drain` | 直接读 DMA 字节并验证未被覆盖，交给解析器 | 去掉了传输中间缓存；解析/业务存储仍有复制 |
| `UART_RxDma_Read` | 保留复制兼容接口，RouterTask 不再使用 | 不可以 |
| 启动早期阻塞串口/直接 DMA 自检 | 保留原启动诊断路径 | 不纳入运行期原生队列承诺 |

不要只把 `UART_Async_Write(stack_buf, len)` 换成一个指针队列就说零拷贝：调用者函数返回后栈数组可能已经失效。新接口必须先拿到受管理的缓冲，再直接生成。

## 3. 发送缓冲怎么管理

### 固定池，不动态申请 payload

`uart_tx_pool.c` 使用 8192 字节静态、4 字节对齐的发送空间，分成 32 个 256 字节单元。一次申请可占多个连续单元，最大 8192 字节。每个包是一段连续内存，可以直接交给 DMA。

占用情况由一个 32 位原子位图记录。多个任务通过 CAS 抢占连续空闲单元；CAS 相当于“只有占用状态仍和我刚才看到的一样，才一次性完成预留”。失败就重新观察，不拿生产者互斥锁。

代价也要说清：小包最少占 256 字节，多个空洞可能造成碎片。即使总空闲字节够，也可能没有足够长的连续段。不会为了整理碎片而移动正在发送的数据；申请者必须处理失败。

### 所有权生命周期

```text
FREE → WRITING → QUEUED → IN_FLIGHT → FREE
          └── Cancel ───────────────→ FREE
```

- `Acquire`：调用者独占数据，可写入，但消费者还看不到这个包。
- `Commit`：完成原子发布；成功后调用者不能再读写缓冲，也不能再 Cancel。
- `Begin`：唯一消费者取得消息，DMA 发送期间一直占有。
- `Finish`：DMA 完成，或者已确认 DMA 停止，才允许归还。
- `Cancel`：只用于尚未提交的缓冲，失败路径必须由原所有者调用。

租约带代数和状态，拒绝重复提交、重复归还、旧租约操作新一代缓冲。它不是安全认证机制；代数有限且会回绕，API 的前提是一个租约只有一个所有者，不能把复制的句柄交给两个任务同时操作。任务异常退出后也不能擅自回收它仍可能写入的缓冲。

### MPSC 无锁发布队列

MPSC 就是多个生产者、一个消费者。生产者完成 payload 后，通过 CAS 把描述符放到就绪链表。消费者用原子 exchange 一次摘下整个批次，再反转该批次，按成功发布顺序处理。

为什么没有“慢生产者卡住整个队列”？因为申请不等于发布。任务 A 写到一半被抢占时，任务 B 已经提交的包仍能被消费者拿走。实际顺序按 Commit 的成功发布先后，不按 Acquire 先后。

生产者只发布自己的 `next`，不解引用当前 head；消费者是整批摘取，不是读取 next 后 CAS-pop。因此这里索引复用的 ABA 不会造成那种 CAS-pop 悬空链表问题。缓冲何时可复用还受位图与租约状态约束。

“无锁”的范围是内存池分配和描述符发布核心。FreeRTOS 信号量用于唤醒 TX 任务，可选的申请超时会等待；RTOS 内部也有临界区。不能说整套串口 API 完全没有临界区，或者每个生产者都 wait-free。CAS 在竞争中可能重试。

## 4. 如何用原生接口

以下是代码用法示例，不是本次向板子发送过的消息。

```c
UART_AsyncTxLease_t lease = {0};
if (!UART_Async_Acquire(128U, 10U, &lease)) {
    /* 背压：交由业务决定稍后重试或记录丢弃。 */
    return;
}
int n = snprintf((char *)lease.data, 128U, "STATUS %lu\r\n", value);
if ((n <= 0) || (n >= 128) ||
    !UART_Async_Commit(&lease, (size_t)n)) {
    (void)UART_Async_Cancel(&lease);
}
/* Commit 成功后，不允许再访问 lease 原来的 data。 */
```

更简便的任务上下文格式化接口：

```c
size_t accepted = UART_Async_Printf(128U, 10U,
                                   "STATUS %lu\r\n", value);
/* accepted == 0 表示没有发布，不等于已经送达对端。 */
```

容量包含 `snprintf` 的字符串终止符，实际发出的长度不包含它。截断的输出不会提交，不会把半条协议应答发出去。不能在 ISR 里做这些格式化/等待操作；ISR 只做完成通知或 RX 边界计数。

`WriteReliable` 的名字只表示“整包入队、允许有限等待”，不意味着接收端已经收到，更不意味着具备应用层 ACK。DMA 完成与对端确认是两件事。

## 5. 错误与覆盖怎么处理

### TX

DMA 启动失败会短暂重试，连续 1000 ms 仍失败则走终止处理；启动成功后等待完成的上限也是 1000 ms。每次处理只释放当前包，不拆包释放。

发生超时时，必须 `HAL_UART_AbortTransmit` 成功且 DMA 的 EN 位已经清零，才可归还缓冲并记为丢弃。否则缓冲保持占用，后端不再接受发送，也禁止重新初始化把这个缓冲池清空。运行期的 UART 包装函数不会退回阻塞发送来与故障 DMA 争抢 UART。

### RX

DMA 连续写 1024 字节循环数组，HT/TC 回调累计半缓冲边界。读取 NDTR 时核对边界计数，允许推断一个尚未服务的边界事件；主循环以绝对读写进度判断还有多少字节未消费。

读每个字节前后都检查生产者进度。即使字节读出后刚好被 DMA 追上，验证也会丢弃这个不可信窗口，不向解析器交付旧字节。

未消费数据达到整个数组容量、UART 错误，或者 HT/TC 两个粘滞标志同时积压，都会打断当前帧。解析器丢掉半条命令，直到下一个 CR/LF 才恢复；过长行也同样处理。不会把 `START` 的截断尾巴误拼成另一条有效命令。

UART 错误中断只记录并请求恢复。实际 AbortReceive/Receive_DMA 在任务上下文执行，失败就继续保持不就绪、下一次 Poll 再试。丢失未知多少圈时只记录歧义/间隙，不伪造精确丢字节数。

粘滞标志不能无限计数：IRQ 必须在半缓冲时间内得到服务，任务吞吐也必须跟得上。这里没有硬件流控和无限缓存，因此不能承诺任意负载下零丢包。直接解析的回调必须同步、有限且不阻塞；完整命令交给 Router 的非阻塞业务队列。

## 6. 2M 波特率现在是什么状态

默认仍是 **115200**，没有悄悄改变实机串口。

新增 CMake 配置 `UART_LOG_BAUD=2000000`，只控制 LPUART1。高波特率配置下 Router 轮询周期从 5 ms 改为 1 ms。A/B 的 2M 配置可以编译，但 **2M 电气链路与满负载吞吐尚未实机验收**。

按 8N1 每字节约 10 bit 算：2M 的理论字节率约 200000 B/s；512 字节半缓冲时间约 2.56 ms，整缓冲约 5.12 ms。1 ms 轮询只是配置，不是调度时延上界。还要检查 UART 时钟误差、USB-TTL 支持、连线质量、FOC 中断负载、串口/解析吞吐和业务队列压力。

只有完成实际链路的长时间压力、错误统计和 FOC 时序测试，才能把简历中的“2M 波特率已验证”写成完成项。

## 7. 已完成的本地验证

测试文件在 [tests/uart_zero_copy_host](<D:/new project/tests/uart_zero_copy_host/CMakeLists.txt>)，完全不打开硬件设备。

- 队列：4 个并发生产者，每轮 60000 条不同长度消息，检查数据、各生产者 FIFO、归还和复用；最终版本连续 10 轮通过，共 600000 条。
- 所有权：全池申请、碎片不足、越界、旧租约、重复提交/归还、慢生产者尚未提交但快生产者能先发送。
- A/B 真实 UART 适配源代码＋HAL/RTOS 仿真：验证生产者地址与传入 `HAL_UART_Transmit_DMA` 的地址相同；兼容接口确实复制；格式化截断取消；ISR 拒绝；超时与永久 BUSY 有界处理。
- 故障注入：DMA 终止失败保持缓冲占用；RX 慢消费者、积压 HT/TC、读字节后立即被覆盖、UART 错误、恢复失败重试、残帧与超长行重同步。
- ARM 目标：队列对象反汇编中使用 `LDREX/STREX/DMB`，没有外部 `__atomic_*`/`__sync_*` 或 libatomic 锁实现。
- 范围检查：[check_scope.ps1](<D:/new project/tests/uart_zero_copy_host/check_scope.ps1>) 对照本次备份，排除明确列出的 UART 集成函数后，其余 main.c 文本不变；大协议处理器仅改变 PING 应答实现。FOC、ADC、拧紧参数、运动状态机、安全联锁、IAP 地址没有修改。

本地测试证明软件路径与仿真故障处理，不代替示波器、实际 DMA 并发和电机负载下的硬件验收。

### 构建结果

所有固件均为 Release，槽大小保持 224 KiB，CAN 控制帧仍为 `CAN_CONTROL_REJECT_ONLY=ON`。常规配置沿用 CAN 日志＋ESP 网络观测；安全锁定配置保持无运动、无 ESP 观测/日志流。

| 配置 | Flash 使用 | 静态链接 RAM 使用 | 结果 |
|---|---:|---:|---|
| A / `build/UartZeroCopy` / 115200 | 156828 B | 76248 B | 编译通过 |
| B / `build/UartZeroCopy` / 115200 | 155916 B | 76232 B | 编译通过 |
| A / `build/UartZeroCopySafety` | 40568 B | 53920 B | 编译通过 |
| B / `build/UartZeroCopySafety` | 40472 B | 53920 B | 编译通过 |
| A / `build/UartZeroCopy2M` | 156828 B | 76248 B | 配置编译通过，非实机 2M 验收 |
| B / `build/UartZeroCopy2M` | 155916 B | 76232 B | 配置编译通过，非实机 2M 验收 |

链接输出的 RAM 数字不是“运行时栈/堆还剩多少”的实测报告。普通构建仍有原有未使用变量/函数警告；新增主机测试使用 `-Wall -Wextra -Werror -pedantic` 并通过。

### 重跑主机验证

在项目根目录的 PowerShell 中执行，工具路径按本机环境填写：

```powershell
$env:PATH = 'D:\Qt\Tools\mingw1310_64\bin;D:\software\ninja;' + $env:PATH
& 'C:\Program Files\CMake\bin\cmake.exe' -S tests/uart_zero_copy_host -B tests/uart_zero_copy_host/build -G Ninja '-DCMAKE_C_COMPILER=D:/Qt/Tools/mingw1310_64/bin/gcc.exe' '-DCMAKE_CXX_COMPILER=D:/Qt/Tools/mingw1310_64/bin/g++.exe' '-DCMAKE_MAKE_PROGRAM=D:/software/ninja/ninja.exe'
& 'C:\Program Files\CMake\bin\cmake.exe' --build tests/uart_zero_copy_host/build
& 'C:\Program Files\CMake\bin\ctest.exe' --test-dir tests/uart_zero_copy_host/build --output-on-failure --repeat until-fail:10
& 'tests/uart_zero_copy_host/check_scope.ps1'
```

### 重新构建普通 A 槽，不刷写

```powershell
$env:PATH = 'D:\software\arm\bin;D:\software\ninja;' + $env:PATH
& 'C:\Program Files\CMake\bin\cmake.exe' -S foc2_app_a -B foc2_app_a/build/UartZeroCopy -G Ninja '-DCMAKE_TOOLCHAIN_FILE=D:/new project/foc2_app_a/cmake/gcc-arm-none-eabi.cmake' '-DCMAKE_MAKE_PROGRAM=D:/software/ninja/ninja.exe' '-DCMAKE_BUILD_TYPE=Release' '-DCAN_CONTROL_REJECT_ONLY=ON' '-DCAN_LOG_STREAM=ON' '-DESP_NETWORK_OBSERVER=ON' '-DUART_LOG_BAUD=115200'
& 'C:\Program Files\CMake\bin\cmake.exe' --build foc2_app_a/build/UartZeroCopy
```

生成 ELF/BIN/HEX 不等于刷写。B 槽使用 B 工程自己的工具链与链接地址，不能把 A 槽产物当成 B 槽镜像。

## 8. 后续实机验收，不能跳过

1. 先确认机械端隔离、现场允许刷写/复位，并明确选用哪个安全配置；不发送 START/JOG 等运动命令。
2. 115200 下验证启动、PING 和路由诊断，比较日志完整性、RX error/gap/ambiguous 与 TX drop/error 统计。
3. 通过诊断/调试构建读取 `UART_Async_GetDiagnostics`，区分 `native_frames`、`copy_frames`、`copied_bytes`；Release 的未使用诊断函数可能被链接器裁掉，不能据此说统计代码没实现。
4. 测量高优先级 FOC ISR、通信任务、堆与栈余量；用明确大小/周期的只读测试流验证背压和错误恢复。
5. 另行匹配双方 2M 设置，验证误码、吞吐、最长服务延迟和长时间压力。没有验收数据，不能声称 2M 零丢包。

本次原文件备份：[20261003_uart_zero_copy](<D:/new project/refactor_backups/20261003_uart_zero_copy>)。不要在有未保存修改时直接用整目录覆盖；恢复应先核对具体差异。

## 9. 面试怎么说才准确

> 我把 STM32 的主串口发送改成了固定缓冲池和 MPSC 无锁发布队列。业务先申请最终 DMA 缓冲，在里面直接生成帧，提交后把所有权交给单个发送任务，DMA 完成后才归还，所以原生发送路径没有额外的整包缓存复制。接收则去掉软件环形缓存和临时数组，直接从循环 DMA 喂解析器，覆盖或串口错误时丢弃残帧再同步。兼容接口和业务日志历史仍有复制，我会明确区分。软件并发和故障注入测试已通过，2M 目前是可编译配置，实机压力验收还没完成。

能追问清楚的点：为什么不能直接入队栈指针；DMA 完成前谁拥有数据；生产者被抢占会不会挡住别人；连续块池的碎片；release/acquire 发布关系；为何 volatile 不能替代 CAS；缓存溢出后为何必须丢弃残帧；DMA 完成和接收端 ACK 的区别。
