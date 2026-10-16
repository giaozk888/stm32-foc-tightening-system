# Router Transfer、编码器样本 CRC 与开发环境：离线及隔离验收

日期：2026-10-06。板卡工程是 STM32G474 A/B，不是参考图片中的 H7。

> 本文以下记录初始离线／SRAM 阶段。后续已部署专用隔离配置和真实网络桥接，补充完成
> 官方 Transfer＋FreeRTOS／FOC 软件并发实测。最新结果及首次突发超时的限制见
> [真实网络与并发验收](ROUTER_TRANSFER_FREERTOS_FOC_ACCEPTANCE_20261006.md)。

## 完成情况

| 项目 | 结果 | 尚未验证 |
| --- | --- | --- |
| Docker | Dockerfile、默认拒绝构建上下文、非 root 编译入口和操作说明已配置 | 本机未找到 Docker 引擎，镜像未构建/运行；Linux 工具链输出未核对 |
| clang-format | 明确范围内 10 个新增源文件已格式化，21.1.3 检查通过 | 容器 18 与本机 21 的格式输出一致性 |
| 通用 Transfer 转发 | 新 R1 type9，不解析中间包的资源号；单二进制包最多1024字节，固定空间和超时 | 实际 UART/USB/Wi-Fi 链路、负载与线程栈最高水位 |
| 官方 Transfer 端点 | 使用真正的官方 Client/Service/Thread，当前只读资源3日志、4编码器快照 | 未部署 STM32、ESP32、鲁班猫新增版本 |
| AS5047P | 保留传感器奇偶校验/EF；快照文件及 Router 包使用软件 CRC32 | 真实传感器数据 CRC 导出、新鲜度和异常状态上板核对 |
| ADC 双缓冲 | 主机回归、新联合配置编译及后续隔离 SRAM 实测通过 | 完整 FreeRTOS/FOC/Transfer 并发负载、模拟电流噪声未验证 |

初始离线阶段没有执行硬件接入、SSH、刷写、复位或 PWM 动作。
后续用户确认当前电气隔离与稳定供电并授权后，执行了限时 SRAM PWM+ADC 双缓冲测试；
没有写 Flash、复位或发送运动指令，详见下文补验。
只读不表示启动全过程永远没有 PWM；工程保留原有启动流程，必须保持功率级电气隔离。

## 实际执行的验证

`tools/test_router_transfer.ps1` 全部通过：

- 旧 Router 网络 CTest 2/2；只读 RPC CTest 2/2；新 Transfer CTest 3/3。
- Python 32/32，包括真实 TCP、官方原生 Client 和 A/B 实际服务端代码的桥接。
- 1024字节转发、3056字节/空日志、StartAck/数据/CompletionAck 丢失恢复。
- 跨 TCP 连续重启客户端：同节点、复用 RPC call/session 后换日志/编码器资源。
- Write/GetResourceStatus 拒绝、分片冲突/长度/CRC/容量/代次/回绕超时校验。
- feature OFF 保持原预处理通信代码；main 仅新增三个 opt-in 接入块；A/B 通信源同步。

回归中发现并修复两个真正的重连问题：R1 序号复用被旧去重缓存拦截，以及旧最终 ACK
可能错误确认新会话。类型9改为包 ID/偏移/CRC 去重，并在新请求前退役已完成上下文。
退出测试进程时的 ABORTED/Unavailable 日志来自有意关闭旧通道；测试结果以字节比对和
完成确认断言为准。输入日志与编码器角度是**合成测试数据**，不能作为实机采样证据。

`tools/test_as5047p_dma.ps1`：6/6 CTest，DMA FSM 19场景/332检查及范围检查通过。
`tests/foc_adc_window_host.ps1`：1,507,144 窗口规划、双缓冲状态/所有权/丢弃/回绕、
实际双主机线程 5,120,000 对原始样本及 RTOS worker mock 回归通过。主机线程统计只说明
该输入条件下的数据一致性，不能当作板端实时吞吐量或 WCET。

## 本机编译产物

Flash 槽224 KiB，链接 RAM 区131008字节。以下都是 build-only，没有写入硬件。

| 配置 | A Flash / RAM 字节 | B Flash / RAM 字节 |
| --- | --- | --- |
| RouterTransferReadOnly | 195368 / 99248 | 194464 / 99232 |
| RouterTransferSamplingReadOnly | 198752 / 103640 | 197856 / 103624 |
| EncoderDmaReadOnly（Transfer关闭） | 190300 / 88960 | 189396 / 88936 |

ESP32 应用1027600字节，当前1 MiB分区余20976字节（约2%），没有改分区或 NVS。
静态栈预算、链接 RAM 和 `.su` 报告不能替代运行时栈水位验证。

SHA256（`foc2.bin`，不是整个槽或 ELF）：

```text
A RouterTransferReadOnly
035108E44FF487CF20E97BEBC35AD0A4A1CC0A951144C5A8A2949C9358A682F6
B RouterTransferReadOnly
40E4973987AFC704DF1ADA46E89CD351FEC417E8973FC18374A06E783FB1B13C
A RouterTransferSamplingReadOnly
A7CA841D5C9E9A61DFB5380FA55A8E37223F853B87577094614296419EAA47D3
B RouterTransferSamplingReadOnly
C6E921310EDA2C29E716A4319B2C103E23D96C4BEA19D0988867AB552D212599
A EncoderDmaReadOnly
A7092048B8BF1D62C07773201EC0B8DF7D0069CB177538A3E43A7A7845A7B144
B EncoderDmaReadOnly
E48B31D72CDE4BA9B9B0C9BE3BE17A9CF045085D98DF45F23224A1BDEAC4211C
ESP32 build_router_transfer/stm32_esp32_gateway.bin
C478C3E74670FE90F9D02C9313416150719424BDDE4B098BA6192AAD2535220D
```

Transfer 关闭的 A/B 二进制 SHA256 与此前记录相同。不会自动启用新功能。
原修改前文件保存在 `refactor_backups/20261006_router_transfer_before/`。

## 上板验收边界

需先确认**现在**功率级/电机已电气隔离、MCU供电稳定，并授权本次隔离测试。
优先做可恢复的 SRAM 限时逻辑 PWM+ADC 双缓冲采集，检查块切换、drop/reject、数据一致性
与停止/恢复状态；必要时再按 A/B 试运行流程部署联合固件。RAM 最小测试不能替代正式
FreeRTOS worker、Transfer 并发和完整 FOC 的运行时验证。逻辑分析仪只能测数字时序，
不能证明模拟电流输入尖峰、功率级性能或95%负载下稳定运行。

新增 Transfer 网络实机部署还需对应 STM32/ESP32/鲁班猫版本一致；本次没有接管旧通道。
保持可信局域网只读边界，不开放公网任意 RPC，不写固件资源，不发运动指令。

详细操作：[开发环境](DEVELOPMENT_ENVIRONMENT.md)、[Transfer 协议与使用](router_network/TRANSFER_ROUTING.md)。

## 后续重新验证及双缓冲上板（2026-10-06）

用户确认“已电气隔离、供电稳定，允许本次隔离测试”后，先执行板端配置预检，再执行
`tools/foc_adc_ram_test.py --permit-isolated-test --case-ms 200`。7组共28,007对ADC数据、
109个完整诊断块；所有组配对/中断计数一致，无配对/截止报警/规划失败，无丢块或丢样本。
包括95%参考占空比和2kHz动态更新。最小 bench ISR观测最大3.318微秒，不代表完整FOC WCET。
SRAM与CPU上下文比对恢复成功，最终SD=0、MOE=0、CCER=0、CEN=0、CFSR=0。
没有写 Flash、没有复位，板上仍运行原有固件；新增联合固件和网络Transfer未部署。

离线回归本次重跑通过：网络2/2、RPC2/2、Transfer3/3 CTest，Python32/32，
编码器6/6及19场景332检查，双缓冲主机线程5,120,000对样本、RAM bench安全/解码5/5。
A/B三种配置及ESP32再次编译通过，上述二进制SHA256全部保持一致。
Docker命令仍未找到，因此只验证配置/入口，不能报告容器运行通过。

详细实测及限制：[双缓冲隔离验收](ADC_DOUBLE_BUFFER_ISOLATED_ACCEPTANCE_20261006.md)。
