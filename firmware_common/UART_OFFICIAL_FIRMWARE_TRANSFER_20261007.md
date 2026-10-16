# APP 升级接入完整官方 pw_transfer

更新日期：2026-10-07。代码已改，离线测试及 A/B 编译通过；本次没有连接串口、刷板、复位或发送运动指令。板上固件仍是之前的版本，不能把下面的结果当作实机验收。

## 一句话理解

以前电脑自己拼升级数据包、自己控制发送进度。现在让 Pigweed 官方客户端和服务端负责握手、窗口、超时重传和传输完成确认。项目自己只负责：“允许写哪个槽，如何写 Flash，什么时候准许启动新程序”。

```text
电脑 Python 脚本做安全检查 → FW BEGIN 准备非活动槽
    → 官方 C++ Client::Write → UART → 官方 TransferService / Thread
    → FlashWriter 整理成 32 字节 → ProtocolTask 调用原有 Flash 写入函数
    → 全镜像长度、向量表、CRC32 检查 → 关闭传输引擎
    → 可选 FW END → 原 Bootloader 的试运行、确认与回退
```

`pw_transfer` 是“送文件”的；A/B Bootloader 是“决定能不能启动这个文件”的。换传输层不等于重写 Bootloader，也不会自动获得安全启动或固件签名。

## 这次具体改了什么

- 使用仓库固定版本的真正 `pw::transfer::Client`、`TransferService`、`Thread` 和 `WriteOnlyHandler`，不修改 Pigweed 上游源码。
- 电脑脚本只搬运串口报文并执行安全检查；没有手写 Transfer 握手、窗口、重传状态机。
- 资源 2 表示已经通过 `FW BEGIN` 准备好的非活动 APP 槽；只支持 Version 2、从偏移 0 开始。不支持跨复位的断点续传。
- 完整 RPC 包最多 96 字节，接收窗口 64 字节。数据块不一定是 32 字节；写入适配器负责合并，最后不足 32 字节的尾块沿用原 Flash 函数处理。
- 专用传输任务优先级 1，静态栈 1536 个 Cortex-M4 字，即 6144 字节。
- 握手/重传由传输任务处理；Flash 操作通过一个有界作业邮箱交回 `ProtocolTask`，避免两个任务同时修改 `fw_update`。
- 重传若需要回看已提交数据，先对比 Flash 或尚未提交的尾部缓存，不能盲目重复编程 Flash。
- 新入口拥有升级会话时，旧 `FW DATA`、`FW END`、旧 RPC/Transfer 写入被挡住。先 `CLOSE` 并确认 `BUSY=0`，才允许沿用原提交流程。
- 旧 `FW BEGIN/DATA/END` 和 unary `foc.Transfer.Exchange` 保留作备用。旧“官方服务名＋自写 Chunk 状态机”的 Write 包装已经移除；旧 `XFER STATUS` 的 `STREAM=0` 不代表新引擎不可用，要查 `XFER ENGINE STATUS`。

## 为什么还保留 FW BEGIN 和 FW END

`FW BEGIN` 原本负责检查当前槽已确认、目标槽不是当前槽、没有待试运行固件，以及擦除目标槽。新传输 Handler 不重新实现这套逻辑，也不能自己擦除当前槽。

`FinalizeWrite` 会检查完整镜像。即使电脑显示“发送结束”，长度、向量表、CRC32 不对也会返回错误。成功之后默认仍然只是“固件暂存在非活动槽”。

只有明确允许复位时，脚本才发原有 `FW END`。它再检查一次，并请求 Bootloader 试运行。新程序是否健康、是否确认、失败怎么回退，仍由原 A/B 流程负责。

## 边界与安全限制

新入口只接受已有路由层标记的本地 UART 请求；Router、CAN、ESP32 的只读下载入口没有注册这个写入 Handler。这里的“本地”是接口边界，不是密码认证。UART 必须处于可信、受控环境。

板端写入每次都要求目标地址是非活动槽、升级会话有效、FOC 关闭、MOE 关闭、SD 为低。电脑在擦除前还要求 `LATCHED=1`。本次没有改槽地址、分区大小、KVS、Bootloader、元数据或启动选项。

CRC32 能检查镜像损坏，不能证明固件发布者身份；固件签名和安全启动没有因此实现。Flash 擦写也可能影响中断时序，不能把这版写成“电机运行中无感升级”。

UART 最后发包使用现有缓冲池 lease，直接在发送块里生成 HEX；RPC 编码、Flash 对齐缓存和作业邮箱仍有拷贝。不能宣传成端到端零拷贝，也没有实测证明比旧 IAP 更快。

## 命令和工具

板端新入口：

```text
<请求号> XFER ENGINE STATUS
<请求号> XFER ENGINE <完整 RPC 包的 HEX>
<请求号> XFER ENGINE CLOSE
0 EVT FWTRANSFER RPC <HEX>       ← 板端异步回复，不使用全局请求号/Router 回复路径
```

`PHASE`：0 空闲、1 RPC 已打开、2 接收中、3 完成且镜像验证通过、4 失败。`RESULT=0` 表示成功。状态查询和 CLOSE 不擦 Flash，不复位。

电脑入口为 `tools/firmware_transfer_iap.py`，PowerShell 包装为 `tools/transfer_iap_stream.ps1`。原来的文件名保留，但内部现在调用真实官方客户端，不再手写 Transfer 包。

先编译电脑客户端，以下只在本机生成测试程序，不接板：

```powershell
$env:PATH = 'D:\Qt\Tools\mingw1310_64\bin;D:\software\ninja;' + $env:PATH
& 'C:\Program Files\CMake\bin\cmake.exe' -S tests/uart_firmware_transfer_host -B tests/uart_firmware_transfer_host/build -G Ninja -D CMAKE_BUILD_TYPE=Release -D CMAKE_C_COMPILER=gcc -D CMAKE_CXX_COMPILER=g++ -D CMAKE_MAKE_PROGRAM=D:/software/ninja/ninja.exe
& 'C:\Program Files\CMake\bin\cmake.exe' --build tests/uart_firmware_transfer_host/build -j 6
& 'C:\Program Files\CMake\bin\ctest.exe' --test-dir tests/uart_firmware_transfer_host/build --output-on-failure -j 3
python tools/firmware_transfer_iap.py --help
```

以后现场已隔离并允许操作后，才可使用以下调用形式。本次没有执行：

```powershell
# COM号和镜像必须对应现场，不能照抄示例；镜像必须链接到当前非活动槽。
.\tools\transfer_iap_stream.ps1 -Port <现场COM口> -Image <非活动槽镜像.bin> -AllowUpgrade
# 默认仅暂存；另外加 -AllowReset 才会执行 FW END 和试运行复位。
```

脚本需要 `pyserial` 和已编译的 `firmware_transfer_client.exe`。`-StageOnly` 可以显式表达“只暂存”，不能与 `-AllowReset` 同时使用。没有 `-AllowUpgrade` 时，脚本会在打开 UART 之前退出。

旧板端第一次安装新引擎仍需要原 IAP 或经现场批准的刷写流程。`SafetyLocked` 与 CAN 探针构建明确关闭新模块，所以不是所有固件都有 `READY=1`。

失败后脚本只关闭新传输引擎，不自动执行 `FW ABORT`，因为项目原来的 `FW ABORT` 会复位。应先看 `FW STATUS` 再决定受控退出。丢失提交 ACK 时不能盲目重发 `FW END`，要独立检查实际启动状态。

## 本次验证结果

| 验证内容 | 结果 |
|---|---|
| 官方客户端＋实际项目 Handler 的主机测试 | 12/12 通过 |
| Python 安全、提交及 UART 解复用测试 | 8/8 通过 |
| 旧 CAN RPC 与只读 Transfer | 3/3 通过 |
| Router Transfer | 3/3 通过 |
| UART/DMA、缓冲池、日志所有权 | 8/8 通过 |
| 安全保护及参数存储 | 1/1＋2/2 通过 |
| 格式检查、PowerShell 语法 | 通过 |

新主机测试包含：普通镜像、65 字节尾块、224 KB 满槽、丢数据包、丢回复、畸形包/重复 RPC 打开/错误调用号、校验失败注入、Flash 写入失败注入、中途关闭、非本地来源拒绝、未准备会话拒绝，以及两个真实官方引擎与完整 Python 脚本的 stdin/stdout 联调。Flash 是 RAM 模拟，断电安全和真实 Flash 擦写尚未实测。

最终 A/B 编译结果，Flash 分区都是 229376 字节，RAM 链接预算 131008 字节：

| 构建 | Flash 链接占用 | RAM 链接占用 |
|---|---:|---:|
| A RouterTransferIsolated | 199672 B | 111432 B |
| B RouterTransferIsolated | 198776 B | 111416 B |
| A Release | 179412 B | 86392 B |
| B Release | 178516 B | 86368 B |
| A SafetyLocked | 40972 B | 54304 B |
| B SafetyLocked | 40876 B | 54304 B |

构建仍有旧 `main.c` 的 unused 警告。能链接不等于运行时栈已经足够；隔离版 RAM 链接剩余约 19 KB，后续要上板检查 `UartFwTransfer`、Protocol 和 Router 的栈余量、堆余量、看门狗及 UART 丢包情况。

## 后续实机验收

需要重新确认功率级/电机电气隔离、供电稳定，并允许写非活动槽及必要复位。建议依次做只读状态、固件暂存/全包校验、受控 FW END、试运行健康确认、旧接口回归。掉包/超时测试可先做，断电测试必须另行设计恢复方案，不能用本次 RAM 测试替代。

## 代码在哪里

- `firmware_common/uart_firmware_transfer.cc`：官方服务、线程、FlashWriter、单作业邮箱。
- `firmware_common/uart_firmware_transfer_port.inc`：复用 A/B 原 Flash 函数，检查硬件安全状态，生成 UART 回复。
- `firmware_common/uart_firmware_transfer_wire.h`：包大小、字段形状和服务身份检查；不实现传输状态机。
- `tools/native/firmware_transfer_client.cc`：官方电脑端 Client::Write。
- `tools/firmware_transfer_iap.py`：UART 解复用、安全前检查、暂存/可选提交。
- `tests/uart_firmware_transfer_host` 与 `tests/test_firmware_transfer_iap.py`：离线验证。

面试可以说：“我把 A/B 升级的固件上传接到了官方 pw_transfer，引入专用传输任务负责窗口与重传。Flash 写入仍由 ProtocolTask 单独拥有，避免并发修改升级状态；收到全镜像并校验通过后，仍通过 Bootloader 完成试运行和回退。目前新上传路径已通过离线故障注入和 A/B 编译，实机验收待完成。”
