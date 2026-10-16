# 真实网络 Transfer 与 FreeRTOS／FOC 隔离并发验收

日期：2026-10-06（北京时间）。实物为 NUCLEO-G474RE／STM32G474、ESP32-S3、鲁班猫；不是参考简历中的 H7。

## 结论先看这里

已完成真实链路上的日志、编码器快照下载，并在同一 STM32 上同时运行原有 FOC 数学计算、SPI DMA 编码器采样、FreeRTOS 任务及 ADC 双缓冲统计。

**通过的是电气隔离下的数字采样／软件并发，不是电机带载闭环验收。** 功率级未启用，没有运动、参数写入或网络固件写入指令。

| 实测项 | 结果 | 能说明什么 |
| --- | --- | --- |
| USB VCP 直连官方 Transfer | 历史日志 1155 字节下载成功 | 实际 MCU 端点和官方原生 Client 可以互通 |
| 限流并发：两客户端各最多一个在途 RPC | 80/80 RPC；4 次 Transfer：1153、40、1160、40 字节 | 与约 20 kHz 的采样／FOC 计算可以同时工作 |
| 8 请求突发复测 | 80/80 RPC；4 次 Transfer：1167、40、1188、40 字节 | 本次短时突发负载通过，不能据此承诺持续突发可靠性 |
| ADC 双缓冲 | 两次通过测试均无新增丢块、丢样或 reject | 正式 FreeRTOS 统计任务实际消费数据，不只是最小 SRAM bench |
| SPI DMA 编码器 | 两次下载的快照新鲜度均小于 1 ms，状态正常、文件 CRC 校验通过 | 真实编码器样本可经 Router＋Transfer 导出 |
| A/B 试运行 | 连续 5 秒健康检查后由原 bootloader 自动确认 A，GEN=309 | 没有手工强制确认或直接改 Flash 启动元数据 |

必须保留的反例：首次 8 请求突发测试只完成了前三轮 24 次 RPC，第 4 轮超时；4 次 Transfer 仍完成。故不能写成“全部压力测试零失败”。复测没有修改链路固件，首次超时原因仍未确定。

## 数据实际走哪条路

```text
PC 官方 C++ Transfer Client（Python 管连接和 Router 转发）
  → TCP 192.168.137.10:21000
  → 鲁班猫 Router 节点 3
  → 热点 Wi-Fi
  → ESP32 Router 节点 2
  → USART1 PA9／PA10，115200 baud
  → STM32 Router 节点 1
  → 官方 pw_rpc / pw_transfer Service / TransferThread
```

下载客户端为节点 4，只读 RPC 客户端为节点 5、6。资源 3 是真实历史日志的冻结快照，资源 4 是真实编码器 `ENC1` 快照。不是 Python 模拟下载，也不是合成角度。

中间 Router 只转发受长度、CRC、TTL 和白名单约束的 type 9 分片，不为每个资源重写传输状态机。当前实机只验收资源 3／4；任意资源接入、1024 字节整包边界和故障注入的更大文件仍以主机测试为证据，不能概括成“任意文件均已上板”。

## “运行 FOC”为什么电机没有动

新增 `RouterTransferIsolated` 配置是独立、默认关闭的验收夹具：

- 实际 ADC1／ADC2 注入转换触发中断，调用原有 Clarke／Park、PI、限幅、逆 Park 和 SVPWM 数学代码，不伪造完成计数。
- 原有 MotorControlTask 仍是 1 kHz 编码器消费／确认任务，读取真实 SPI DMA 样本。
- 三相计算出的占空比被测试配置丢弃；TIM1 CH4 只在内部提供 ADC 触发参考。
- `SD=0`、`MOE=0`、`AOE=0`、`CCER=0`；所有物理 PWM 通道禁止输出，`foc_enable=0`。
- 本地控制台 `BENCH RUN` 固定最多 60 秒，超时、故障或硬关断条件失效即停止。网络 RPC 没有这个入口。

隔离状态下电流检测输入接近零，最初固件仍走正常零点校准的 1000～2200 检查，因而启动失败。专用配置改为读取 16 组真实 ADC 数据，建立**仅用于计算负载测试的原始数字基线**；并明确打印“模拟电流校准未合格”。

正常配置的电流零点校准门槛与 PWM-on 校准流程没有放宽；检测拓扑仍为 `UNCONFIRMED`。这里没有验证电流增益、真实转矩、功率开关尖峰或 95% 带载工况。

## 量化结果

| 指标 | 限流并发 | 8 请求突发复测 |
| --- | --- | --- |
| 从启动到受控停止 | 14.155 s | 12.015 s |
| ADC 配对数／FOC 计算数 | 283167／283167 | 240357／240357 |
| 平均运行频率 | 约 20004.7 Hz | 约 20004.7 Hz |
| 双缓冲完整消费块增量 | 1099 | 931 |
| 配对 miss／deadline late／规划失败增量 | 0／0／0 | 0／0／0 |
| 双缓冲 drop-block／drop-sample／reject 增量 | 0／0／0 | 0／0／0 |
| Router RX／本地队列满、解析错误、无路由增量 | 均 0 | 均 0 |
| ADC ISR 历史观测最大耗时 | 2469 cycles，约 14.524 μs | 相同 |
| 统计任务历史观测最大经过时间 | 189088 cycles，约 1.112 ms | 247344 cycles，约 1.455 ms |
| RPC 往返耗时范围 | 60.072～270.513 ms | 77.022～402.222 ms |

按 170 MHz 换算。中断耗时是实际观测值，不是形式化 WCET 证明；统计任务经过时间包含被高优先级中断／任务抢占的时间，不等于独占 CPU 耗时。

双缓冲是 **ISR 填写两块原始诊断样本缓冲，FreeRTOS 后台任务消费**，不是声称已经用了 ADC 硬件 DMA 双缓冲模式。每块 256 对样本，约每 12.8 ms 产生一块，后台任务按所有权状态处理完整块。测试前已有 **3 个启动阶段丢块、768 对被丢弃的诊断样本**，测试后计数不增长；“零新增”不能写成“从开机到现在从未丢块”。没有证据把诊断块丢弃解释为 FOC 漏算：`MISS=0`，测试中的 ADC／FOC 计数相等。

运行后栈历史最小剩余量（字节）：MotorControl 2756、Router 2056、Protocol 924、Transfer 3612、ADC 统计 1852。最小历史堆余量 4048 字节。它们只覆盖已执行路径，不替代所有错误分支的栈预算审计。

限流测试的编码器快照 `age_us=856／898`，突发复测为 `861／877`；状态均为 0。SPI DMA 历史最大事务耗时 37 μs，最终读取计数 36381，FAIL／TIMEOUT／IO／SCHED／STALE 均为 0。

AS5047P 的芯片 SPI 帧仍检查奇偶校验／EF，**没有硬件 CRC**。软件 CRC32 位于 Router 分片整包和编码器快照文件，只检查传输数据，不证明磁铁状态、模拟精度或控制稳定性。

## 刷写、回退与保护区

用户明确授权电气隔离测试及非活动 A 槽 SWD 修复后：

1. 原 B 固件保留。先通过受控复位使失败试运行回退到 B，再确认 B 向量地址及输出关闭。
2. 只更新非活动 A 的 APP；CubeProgrammer 下载器曾超时，A 读回不匹配，故没有提交这个半写入映像。该调试下载器失败期间也记录过 HardFault，不把全过程描述为“没有任何异常”。
3. 改用 OpenOCD 的 halted Flash loader，A 写入／读回通过。随后通过现有 CRC 保护的 SRAM `START_TRIAL` 请求交给未修改的 bootloader 校验映像。
4. A 连续 5 秒检查真实 ADC、FOC 计算、编码器、UART 与输出硬关闭条件，通过后正常请求确认、复位；最终 `CURRENT=A CONFIRMED=A PENDING=- ATTEMPTS=0 GEN=309`。
5. 没有网络 Flash Write、手工强制确认或直接写入启动元数据。bootloader 正常更新自身 A/B 元数据是升级流程的一部分。

完整 512 KiB Flash 读回与测试前基线比对通过：bootloader／预留启动区 32768 字节、原 B 槽 229376 字节、KVS／预留数据区 26624 字节、参数页 2048 字节均未变化。

当前 A APP：195476 字节，CRC32 `547D67EE`，SHA256：

```text
963589881051138CE1D8FAE0E25B7A3C4999306F11812FE92EFD2F35BCB94FCC
```

B 的隔离测试版本只编译，未写入。当前 A 是**隔离验证固件，不是可以启用电机的生产版本**。

ESP32 只写 APP `0x10000`，1027600 字节；bootloader、分区表和 PHY 区一致。SSID、热点密码、上传 URL、API token 和 allow-HTTP 配置值一致，没有输出密钥。NVS 原始字节因运行期 Wi-Fi 数据更新而不同，不能声称整个 NVS 分区逐字节未变。应用分区只余 20976 字节，后续扩功能前需要预算 Flash。

## 最终安全状态

最后一次网络测试退出后，串口和只读 SWD 都确认：

```text
CURRENT=A，CONFIRMED=A，PENDING=-
BENCH ACTIVE=0，SD=0，MOE=0，CCER=0，CEN=0，FLT=0
VTOR=0x08008000，CFSR=0
SPI CS=HIGH，DMA4/5 disabled，SPI DMA requests off，TIM2 compare IRQs off
```

没有修改校园网认证、热点配置、云端服务或私有凭据。鲁班猫桥接由用户在已有 SSH 窗口启动，不是新部署的自启动服务。

## 代码和重现入口

相关实现：

- `firmware_common/isolated_concurrency.inc`：限时夹具、硬关断、计数／栈诊断。
- A/B `Core/Src/main.c`：17 个独立 opt-in 保护块；OFF 分支与原源码逐文本一致。
- `firmware_common/pw_router_transfer.cc`：真正的官方 TransferThread；新增实际 worker 栈水位查询。
- `tools/router_transfer_concurrency_live.py`：本地限时启动、真实下载／RPC、指标增量检查及无论成败都执行 STOP。
- `router_network/rpc_live_acceptance.py`：显式 `paced`／`burst` 两种负载、逐调用诊断；失败时取消兄弟请求再关闭连接。
- `tools/isolated_slot_recovery.py`：本次专用非活动 A 修复流程。**不是可随时重跑的普通升级脚本**；当前 A 已确认，不能拿它直接覆盖 A。

离线回归：网络 CTest 2/2、官方 RPC CTest 2/2、官方 Transfer CTest 3/3；新增限流／失败清理用例后，Python 全套重跑 **35/35**。明确范围 10 个源文件的 clang-format 检查、A/B 同步及 OFF 分支范围检查通过。Docker 镜像仍未实际运行。

只读下载示例（输出只能使用新文件名）：

```powershell
$env:PATH = 'D:\Qt\Tools\mingw1310_64\bin;' + $env:PATH
python -m router_network.transfer_client --tcp 192.168.137.10:21000 --resource 3 --output 'D:\new project\tmp\history-new.bin'
```

上述下载不启动 FOC 计算。要重新运行 BENCH 必须重新确认现场电气隔离、供电和测试权限，不能凭本文视为永久授权。

## 原始证据与未完成项

在 `D:\new project\safety_backups\`：

- `20261006-router-transfer-inactive-recovery-3/recovery.json`：5 秒健康确认的启动记录。
- `20261006-router-transfer-concurrent-run-1/`：首次 RPC 超时的失败结果、串口记录和 4 个下载文件。该初版 harness 没有在失败结果中保留全部指标，后补诊断位于 `20261006-router-transfer-post-failure-diag/`；不补造缺失记录。
- `20261006-router-transfer-concurrent-paced-run-2/result.json`：限流测试结果、逐调用耗时、前后计数与实际文件哈希。
- 同目录 `stm32-final-private.bin.verification.json`：全 Flash 比对及元数据校验。
- `20261006-router-transfer-concurrent-burst-run-3/result.json`：突发复测结果；同目录 `final-registers.json`：最终寄存器状态。
- `20261006-router-transfer-concurrency-live/esp32-verification.json`：ESP32 APP／配置值保护检查。

`*-private.bin` 可能包含凭据／私人数据，不要上传、公开或提交 Git。

尚未完成：首次 RPC 超时的逐跳根因定位、启动阶段诊断块丢弃优化、长时间／多设备持续突发压力、真实模拟电流和功率开关噪声、带载闭环控制、生产版本退出夹具后的回归。CRC／节点 ID／TTL 不是鉴权；当前 Router 只用于可信局域网，没有新增 SocketCAN 端口，也不能称为端到端零拷贝。

可用于项目介绍的准确说法：**“在功率级电气隔离条件下，通过 Router＋官方 pw_transfer 完成真实网络日志／编码器下载，并与约 20 kHz FOC 数学计算及 FreeRTOS ADC 双缓冲统计并发验证；受控负载期间无新增采样配对错误或诊断块丢弃。”** 不写“带载稳定运行”“全部压力测试零失败”。
