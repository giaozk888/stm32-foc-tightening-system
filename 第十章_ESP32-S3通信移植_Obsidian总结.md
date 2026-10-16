---
title: 第十章｜ESP32-S3 与 STM32G474 通信移植总结
tags:
  - STM32G474
  - ESP32-S3
  - FreeRTOS
  - UART
  - Router
  - A-B升级
  - Obsidian
date: 2026-09-26
status: 双板 UART/Router 发现与正式 B 槽 PING/PONG 闭环已验证；Wi-Fi 和拧紧联动未实现
---

# 第十章：ESP32-S3 通信移植与 A 槽升级

> [!summary] 本章结论
> ESP32-S3 N16R8 已能作为节点 2 经独立 3.3 V UART 接入 STM32G474 的 Router。A 槽先验证发现链路并完成正常启动；随后新增正式 APP 的 `ESP PING` 闭环，经 IAP 写入非活动 B 并自动确认。当前板上 `CONFIRMED=B`，COM5 到 ESP 再回 COM5 的同号 PING/PONG 实测 12/12 成功。**本章完成的是通信基础设施，不是 Wi-Fi 网关或远程电机控制。**A 保留为上一版可回退镜像。

## 1. 目标、架构与接线

目标是在不迁移 FOC、保护和拧紧控制权的前提下，为项目加入 ESP32-S3 通信节点。STM32 仍是电机控制主机（Router 节点 1）；ESP32 是通信扩展节点（节点 2）。当前 ESP32 只发 `HELLO`、解析 Router 帧，并在自身代码中具备 PING/PONG 应答骨架；正式 STM32 APP 对 ESP 入站**仅放行发现帧**，禁止从 ESP 侧注入 `START`、参数修改或 IAP 命令。

```text
PC / COM5 ── STM32 LPUART1(PA2/PA3) ── Protocol / Router(节点1)
                                              │
                                      ESP Link / USART1
                                      PA9 TX ──→ GPIO18 RX
                                      PA10 RX ←── GPIO17 TX
                                      GND   ──── GND
                                              │
                                      ESP32-S3(节点2)

STM32 内：FOC/保护/拧紧仍留在 STM32；ESP 目前不获得电机命令权限。
```

两板各自 USB 供电，只共地并交叉连接 3.3 V UART，不互接 3V3/5V/VIN。STM32 的 PC10/PC11 已用于 RS485 继电器，PC4/PC5 用于 VBUS/VTEMP，PA2/PA3 是 COM5；故本章选用 USART1 的 PA9/PA10，而不是看似可用的 Arduino D0/D1。接线依据和开发板排针核对见 [[esp32_s3_gateway/README]]。

## 2. 开发过程：逐步做了什么

| 阶段 | 工作与验证 | 当时的边界 |
| --- | --- | --- |
| 10.1 ESP 单板 | 建立 ESP-IDF `esp32s3` 工程，UART1 115200 8N1、GPIO17 TX/GPIO18 RX、Router 帧解析与周期 `HELLO`；备份原厂 16 MB Flash 后烧录。COM9 启动日志确认 `app_main()` 运行。 | N16R8 表示 16 MB Flash/8 MB PSRAM，PSRAM 尚未启用；单板启动不能证明外部连线。 |
| 10.1 软件回环 | 用 ESP UART1 内部 loopback 发/收并解析 27 B HELLO。修正同步后，首次启动及连续 10 次软件复位均 `PASS`。 | 只证明 UART 驱动和帧处理，不证明 GPIO17/18 引脚电平。 |
| 10.2 双板隔离诊断 | 临时 SRAM 程序保持 STM32 PC6 低、不写 A/B Flash，实测 `ESP_HELLO` 与 `ESP_PONG` 增长、`TX_FAIL=0`。 | 这是诊断程序上的双板往返，不代表正式 APP 已放行 PONG。 |
| 10.3 移植到 A | 将 ESP discovery-only transport 与 Router 端口集成进非活动 A 槽；B 槽源码也曾离线构建，但板上已确认 B 未覆盖。 | 初版 A 只剩 28 B Flash 余量，不能继续堆功能。 |
| 10.4 正式源码 SRAM 测试 | 独立 `stm32_esp_stack_diag` 直接编入正式 A 的 `esp_link.c`、`router.c` 与 FreeRTOS；真实双板下 `ESP_NODE=1`、`DISC_RX=3→5`、`DISC_TX=6→10`、`PARSE_ERR=0`。 | 仍不是完整 A APP 正常启动。 |
| 10.5 Flash 瘦身 | 只给 Router、ESP、Modbus、Pigweed 日志桥、启动单测等非 FOC 源文件单文件加 `-Os`；A/B 各节省约 17,180 B。 | 不改 20 kHz FOC ISR、TIM1/PWM/ADC 核心时序；离线编译不是上板验收。详见 [[STAGE10_5_FLASH_SIZE_OPTIMIZATION]]。 |
| 10.6 安全通信入口 | A 槽增加启动时按住 B1/PC13 的 `SAFE COMM` 分支：只运行 Router/ESP discovery，保持 PC6/CTRL_SD 低和 TIM1 MOE=0。SRAM 程序实测本板 B1 空闲低、按下高。 | 安全分支不运行 FOC、拧紧或 BootHealthTask，也不会自动确认待试运行 A。详见 [[STAGE10_6_ESP_SAFE_COMM_BOOT]]。 |
| 10.8 A 安全试运行 | 从已确认 B 通过 COM5 IAP 写入旧版 A（CRC `50101757`），按住 B1 安全启动；`DISC_RX` 增长、`PARSE_ERR=0`、`SD_ODR=0`、`MOE=0`，用户实测 CTRL_SD 为 0 V。 | 只证明通信安全路径；A 当时仍 `PENDING`，未确认。详见 [[STAGE10_8_A_SAFE_TRIAL]]。 |
| 10.9 A 正常启动修复 | 第一次正常试运行因 FreeRTOS 堆不足，`BootHealthTask CREATE FAILED`，旧 A 未确认；堆从 32 KiB 提至 40 KiB，修复版 A 重新 IAP。 | 详见 [[STAGE10_9_A_NORMAL_TRIAL_HEAP]]。 |
| 最终验收 | 新 A（CRC `CB7C85FB`）正常启动、5 秒健康检查通过、自动确认并重启。之后约 35 秒空闲监测无故障，再次复位仍为 A；Router 发现计数继续增长。 | 未执行完整拧紧，也未覆盖 B 槽。 |
| 10.10 正式闭环 | A/B 源码加入受限 `ESP PING`，B 槽经 IAP 升级、健康检查自动确认；正式 APP 真实双板 PING/PONG 12/12 成功。 | A 板上镜像仍为上一版；Wi-Fi、断线负面测试及拧紧联动未验收。详见 [[STAGE10_10_ESP_PING_CLOSED_LOOP]]。 |

## 3. 关键测试结果与当前板上状态

- ESP32 USB 侧：COM9 烧录与启动成功；UART1 内部回环 `PASS`，Router 帧可解析。
- 双板隔离诊断：补好 PA9→GPIO18 脱落导线后，SRAM 程序显示 HELLO/PONG 均增长，证明物理 TX/RX 往返。
- 正式 A 安全分支：`ESP_NODE=1`、发现接收计数增长、`PARSE_ERR=0`；功率级保持关闭。
- 正式 A 正常分支：编码器启动 `OK=20/20`，电流零点校准和 UART DMA 正常，各任务成功创建；健康检查 `PASS 5s` 后自动确认。
- Stage 10.9 复位后曾为 `CURRENT=A CONFIRMED=A GEN=241`；这是当时的 A 槽验收记录，**不是当前状态**。
- 最新 COM5 Router 查询：节点表有 `NODE ID=2 PORT=ESP32`，路由表有 `ROUTE DST=2 PORT=ESP32`；约 6 秒内 `DRX=48→50`、`DTX=96→100`，`PARSE=0`、队列满计数为 0。
- 修复版 A BIN **213088 B**，CRC32=`CB7C85FB`，224 KiB 槽剩 **16288 B**。静态 RAM 报告 **73536 B**，其中 FreeRTOS `configTOTAL_HEAP_SIZE=40 KiB`；这不是“实时剩余堆”读数。
- Stage 10.10 后板上当前状态为 `CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0 GEN=244`。B 新镜像 **212872 B**、CRC32=`395DD27E`、静态 RAM **73528 B**；正常空闲约 20 kHz、`FLT=0`。A 板上仍是 Stage 10.9 的已验证旧版，未被本次 IAP 改写。
- 正式 `ESP PING`：一次单独请求、连续 10 次请求和边界值 65535 均收到同号 `OK ESP32 PONG`，共 12/12；65536、70000 被拒绝。测试后 Router `PARSE=0`、队列满计数为 0。断线/超时负面路径尚未实测。

## 4. 问题、原因与解决方法

| 问题 | 查出的原因 | 处理与经验 |
| --- | --- | --- |
| ESP 灯亮但找不到串口 | 供电、USB 枚举、下载模式与应用模式不是一回事；COM 号也可能变化。 | 用 COM9 的 USB 枚举和启动日志确认板子与固件，不把“亮灯”当作串口正常的证据。 |
| ESP loopback 偶尔比较失败 | 起始位置可能混入前导 `0x00`，收满字节仍不等于对齐到 Router 帧。 | 等待 UART 稳定、清空 RX，并按 `@` 和换行重新同步；连续 10 次复位均通过。 |
| STM32 收到 HELLO，却没有 ESP PONG | STM32 PA9→ESP GPIO18 的导线脱落。 | 重新固定交叉接线后，SRAM 双板诊断的 HELLO/PONG 同时增长。软件计数不能替代接线检查。 |
| A 初版差 4 B 超出槽位，调整后只余 28 B | 224 KiB APP 槽已接近容量上限。 | 先缩短日志使其可链接，再对非 FOC 文件定向 `-Os`，释放约 17 KiB；保留 FOC 时序相关编译策略。 |
| 驱动电源 0 V 时完整 APP 启动不到 ESP 任务 | 原 APP 在启动 ESP 之前做编码器、电流采样和功率级初始化，零点校准依赖驱动板有效供电。 | 先做 SRAM 隔离诊断，再在 A 槽加入 B1 一次性安全通信入口；不靠关闭 12 V 后盲目复位来测试完整 APP。 |
| 安全试运行成功，却没有自动确认 A | `SAFE COMM` 刻意不运行 BootHealthTask，也不检查电机健康。 | 保持 A 为待试运行；后续再走正常启动与 5 秒健康检查，通信通过不等于电机 APP 健康。 |
| A 正常启动报 `BootHealthTask CREATE FAILED` | FreeRTOS `heap_4` 当时仅余 **240 B**，不足以创建该任务。 | A 槽的 `configTOTAL_HEAP_SIZE` 从 32 KiB 增至 40 KiB；重新构建并通过 COM5 IAP 升级。第二次正常启动、自动确认和复位回归均通过。 |
| 一次回退 B 后 COM5 无响应 | 当时 PD6010B 的 12 V 刚关闭，B 在启动错误处理路径，非 Flash/CRC 损坏。 | 恢复既定 12 V、0.5 A 条件后受控复位，B 的校准和串口正常，再从 B 升级 A。 |
| ESP 代码能回复 PING，但 COM5 曾看不到正式 APP 的 PONG | 原 `esp_link.c` 入站白名单只允许 `HELLO/ANNOUNCE` 发现帧。 | Stage 10.10 增加精确 PONG 白名单、单请求关联和超时；任何 ESP 包仍不得进入通用电机命令解析。正式 B APP 实测 12/12 成功。 |

## 5. 复现命令与观察方法

在工程根目录离线构建和检查：

```powershell
cmake --build 'D:\new project\foc2_app_a\build\Debug' -j 4
ctest --test-dir 'D:\new project\tests\as5047p_host\out' --output-on-failure
python 'D:\new project\tests\tim1_pwm_adc_timing.py'
```

ESP32 工程在已配置 ESP-IDF 的终端中构建；`COM9` 是本次实测端口，重新枚举后应按设备管理器实际端口替换：

```powershell
cd 'D:\new project\esp32_s3_gateway'
idf.py build
idf.py -p COM9 monitor
```

以下是 Stage 10.9 从 B 升级 A 的**历史命令**；Stage 10.10 则从 A 把 `foc2_app_b/build/Debug/foc2.bin` 写入 B。当前已确认 B，**不要照抄旧命令重复升级**。IAP 工具的目标是非活动槽，必须先查 `FW STATUS`：

```powershell
python -u 'D:\new project\foc2_app_a\iap_update.py' COM5 'D:\new project\foc2_app_a\build\Debug\foc2.bin'
```

在 COM5 串口终端使用 **115200、8N1**；行首数字是请求 ID，可以换成未使用的值：

```text
3010 FW STATUS
3011 ROUTER STATUS
3012 ROUTER NODES
3013 ROUTER ROUTES
3014 ESP PING
```

当前正常期望：`CONFIRMED=B PENDING=-`；节点 2 与通向 ESP32 的路由存在；间隔约 5–10 秒再查 `ROUTER STATUS`，`DRX` 应增长、`PARSE=0`。`3014 ESP PING` 应先得到 `OK ESP PING SENT`，随后得到同号 `OK ESP32 PONG`；单独的 `ROUTER SEND 2 ... PING` 成功发送仍不能替代闭环验收。

## 6. 本章知识点与后续边界

1. **分层验证。** ESP 单板 USB 启动、UART 内部回环、真实双板 SRAM 诊断、正式 APP 安全路径、正式 APP 正常路径，是五层不同证据；上一层通过不自动证明下一层。
2. **引脚复用与供电域。** PA9/PA10 避开已有 RS485、COM5 和 ADC 资源；两板只连 3.3 V UART 与地，各自供电。N16R8 是模组存储规格，不代替开发板排针核对。
3. **Router 的发现与业务权限分离。** 发现节点 2、建立路由不意味着 ESP 可发电机命令。当前白名单是刻意的边界；未来开放 RPC 时要做权限、超时、去重及故障处理。
4. **A/B 升级的三种状态。** 写入完成 ≠ 试运行健康 ≠ 已确认。`PENDING` 和剩余尝试次数由 bootloader 管理；确认后重启仍应查 `CONFIRMED`。不要直接覆盖已确认槽并破坏镜像 CRC 与元数据对应关系。
5. **FreeRTOS 堆与静态 RAM 不同。** `configTOTAL_HEAP_SIZE` 决定 `heap_4` 可供任务栈/队列分配的池大小；链接报告的 73536 B 是静态占用，不能当作运行时空闲堆。任务创建失败需看实际剩余堆和失败位置。
6. **安全启动是诊断分支，不是完整验收。** 按住 B1 的 `SAFE COMM` 明确保持桥臂关闭，但它不验证 FOC/拧紧，也不会自动确认固件。

> [!todo] 未完成，不要写成已验证
> - ESP 断线、迟到/错误 PONG 和 2 秒超时的物理负面测试；目前只有正常往返实测。
> - Wi-Fi、Socket/UI、远程日志或上位机控制；当前 ESP 工程未启用 Wi-Fi。
> - 经 ESP 的受控拧紧业务与故障/断链策略；当前禁止 ESP 发电机命令。
> - 带工件的电机/拧紧验证及长时间耐久测试。
> - 评估 B 稳定性和异常路径后，是否把 Stage 10.10 新功能同步到 A；目前 A 是上一版回退镜像。

## 7. 关联记录

- [[esp32_s3_gateway/README]]：ESP 工程、引脚、单板与早期双板测试。
- [[stm32_esp_link_diag/README]]：SRAM 双板 HELLO/PING/PONG 诊断。
- [[stm32_esp_stack_diag/README]]：正式 Router/ESP 源码的 SRAM 安全实测。
- [[STAGE10_5_FLASH_SIZE_OPTIMIZATION]]：Flash 定向优化与当时的 A/B 构建数字。
- [[STAGE10_6_ESP_SAFE_COMM_BOOT]]：B1 安全通信入口。
- [[STAGE10_8_A_SAFE_TRIAL]]：旧 A 的安全试运行，不等于确认。
- [[STAGE10_9_A_NORMAL_TRIAL_HEAP]]：堆不足、修复版 A 升级与最终确认。
- [[STAGE10_10_ESP_PING_CLOSED_LOOP]]：正式 B APP 的受限 PING/PONG 闭环与上板实测。
