# ESP32-S3 N16R8 companion：Stage 10.1

> 2026-10-01 增量：已增加 Wi-Fi、HTTP(S) 观测上传和只读 Modbus TCP 源码。
> 下文是 UART 握手阶段的历史记录；新链路及部署/验收边界见
> [`network_server/README.md`](../network_server/README.md)。新网络功能尚未实机部署验收。

这是 STM32G474 项目的 **ESP32 侧 UART/Router 握手骨架**，不是把 FOC、电机保护或 Modbus 移到 ESP32。本阶段不启用 Wi-Fi。ESP32 节点号暂定为 `2`，STM32 为 `1`。

## 已实现

- ESP-IDF 工程目标 `esp32s3`，UART1 8N1，默认 115200；TX/RX GPIO 可在 `idf.py menuconfig` 改。
- 接收并校验与 STM32 Router 相同的 ASCII 帧：`@R1 SRC DST TYPE SEQ TTL LEN PAYLOAD`，长度上限 224 字节。
- 每 5 秒发一次 `@R1 2 65535 3 ... 8 5 HELLO`。
- 收到发给节点 2 的 `TYPE=1`、载荷 `<REQ_ID> PING` 后回复 `<REQ_ID> OK ESP32 PONG`。
- 串口超长行丢弃；当前没有把 Wi-Fi 或电机控制暴露出去。

## 排针已确认，两板联机尚未验证

`N16R8` 仅说明模组 Flash/PSRAM 容量，不能单独确定整块开发板的排针。用户提供的《ESP32-S3 系列芯片技术规格书》v2.2 的表 2-4 确认芯片 GPIO17=U1TXD、GPIO18=U1RXD；GPIO19/20 默认承担 USB 功能，GPIO0/3/45/46 属于启动配置管脚，GPIO26–32 与 flash/PSRAM 相关。2026-09-26 用户的开发板正面照片可见排针丝印 **17** 和 **18**，故当前代码默认 GPIO17(TX)、GPIO18(RX) 有实物接点。接线仍应以板上丝印而非图片方向计数确认；不要向 ESP32 GPIO 输入 5 V 或 12 V。

STM32 的 PC10/PC11 已用于 USART3 RS485 继电器，PA2/PA3 LPUART1 已用于 COM5。Stage 10.2 已在 **B 槽源码**增加独立 USART1/PA9/PA10 的 ESP32 Router 发现链路，但未烧录；A 槽源码不变。现阶段只把来自 ESP32 节点 2 的合法 HELLO/ANNOUNCE 帧送入 Router，禁止从 ESP32 输入电机、参数或 IAP 命令。ESP32 工程的 PING 回复逻辑尚未经过 STM32 联机验证；STM32 端目前没有将该回复交给上位机的处理流程，不能宣称 PING 闭环已完成。

### NUCLEO-G474RE 连接器预审（UM2505 Rev 7）

- 手册 §7.6.5 表 10/11：板上默认把 USART1 的 **PC4/PC5** 接到 Arduino D1/D0，而 LPUART1 的 **PA2/PA3** 接到 ST-LINK 虚拟串口。实际工程 PA2/PA3 正被 COM5 使用，PC4/PC5 正被 VBUS/VTEMP ADC 使用；**不要**把 Arduino D0/D1 当成空闲 ESP32 串口，也不要改动相关焊桥。
- 手册 §8.4 表 16：PA9 在 ST morpho **CN10-21**、PA10 在 **CN10-33**，CN10-20 为 GND。用户的 CubeMX 截图另外确认 STM32G474 上 PA9=USART1_TX、PA10=USART1_RX，因此 B 槽源码按此配置；ESP32 开发板正面照片已确认 17、18 两个排针丝印。
- 两块板应各自用可靠的 USB/电源供电，共地后只交叉连接 **3.3 V UART** 的 TX→RX、RX←TX；不要用 NUCLEO 3V3 给带 Wi-Fi 峰值电流的 ESP32 板供电，也不要接 5 V/12 V 到 GPIO。用户曾完成两板接线；随后为 ESP32 单板测试要求暂断板间线，当前是否接回未确认。未进行两板联机或电机上电测试。

| NUCLEO-G474RE | ESP32-S3 开发板 | 作用 |
| --- | --- | --- |
| CN10-21 / PA9 / USART1_TX | 丝印 18 / GPIO18 / UART1_RX | STM32 发往 ESP32 |
| CN10-33 / PA10 / USART1_RX | 丝印 17 / GPIO17 / UART1_TX | ESP32 发往 STM32 |
| CN10-20 / GND | 任一丝印 GND | 信号共地 |

以上是**核对后的接线方案，不是已验证的联机结果**。两板的 3V3、5V、VIN 均不互连，也不经过 RS485 转换模块。断电时接线并复核交叉方向；一板断电而另一板 UART TX 持续驱动时，须注意经 GPIO 反向供电的风险。

特别注意：现有 STM32 完整 APP 的启动流程需要 PD6010B 供电后的编码器/电流零点等校准，且之后会启用驱动桥。**PD6010B 输入为 0 V 时，不能假设现有 APP 能启动到 EspLinkTask；不能为验证 HELLO 而直接退出 ANALOG SAFE 或复位启桥。**先独立编译/USB 测 ESP32，再设计保持 `CTRL_SD=0`、跳过功率级初始化的 STM32 通信专用测试模式；完成安全审查后才进行两板联机测试。

## 有 ESP-IDF 环境后的命令

在 ESP-IDF PowerShell/终端内：

```powershell
cd 'D:\new project\esp32_s3_gateway'
idf.py set-target esp32s3
idf.py menuconfig
idf.py build
```

确认开发板端口和供电之后，才执行 `idf.py -p COMx flash monitor`；`COMx` 需替换为 ESP32 自己的端口，**不是** STM32 的 COM5。先只用 ESP32 USB 供电验证启动日志，暂不接 STM32 或 PD6010B。

2026-09-26 已通过 Espressif Installation Manager 安装 ESP-IDF v6.1（源码位于 `D:\Espressif\v6.1\esp-idf`，工具位于 `C:\Espressif\tools`）。`idf.py set-target esp32s3` 和 `idf.py build` 均成功，当前应用镜像位于 `build/stm32_esp32_gateway.bin`，大小 `0x31dd0` 字节。下载模式重新枚举为 COM9（VID:PID=303A:1001），`flash-id` 确认 ESP32-S3、16 MB Flash、8 MB 嵌入式 PSRAM；工程已配置 `CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y` 并重编译，PSRAM 尚未启用。原厂 16 MB Flash 已完整读出到 `esp32_s3_factory_backup_20260926.bin`（16,777,216 字节，SHA256 `D73B6DD5A15E469A30629798664FB6E9E5C0EE30EF2679D75858D97A72B6FB15`）。随后已向 COM9 写入 bootloader、partition table 和应用，三处写后哈希校验均通过。BOOT 松开后单按 RST，`idf.py monitor` 看到 `SPI_FAST_FLASH_BOOT`、加载 `stm32_esp32_gateway`、进入 `app_main()`，并打印 `ESP32-S3 node 2, UART1 115200 baud, TX GPIO17 RX GPIO18`；**ESP32 单板启动已验证**。

为不使用逻辑分析仪进行软件测试，ESP32 启动时增加一次 `uart_set_loop_back(UART_NUM_1, true)` 芯片内部回环：发送 Router `HELLO` 帧，读回完整帧并调用 `router_frame_parse()` 校验，之后关闭回环。初版测试偶发读到前导 `0x00`，导致虽然收满 27 字节仍比较失败；测试程序现先等待 UART 稳定、清空输入，并按 `@`/换行同步再校验。修正后实测首次启动及连续 10 次软件复位均输出 `UART1 INTERNAL LOOPBACK PASS (27 bytes, skipped=0, Router frame parsed)`。这只证明 **UART1 内部 TX→RX、驱动调用与帧格式/解析** 在这些启动中正常；不证明 GPIO17/18 外部电平、接线质量或 STM32 联机。STM32 新 B 槽固件仍未烧录。

### Stage 10.2 B 槽离线结果

`cmake --build 'D:\new project\foc2_app_b\build\Debug' -j 4` 已通过，链接后的 `foc2.bin` 为 229004 字节，224 KiB APP 槽剩余约 372 字节。为保持 A/B 分区及 FOC 时序不变，仅新增的 `esp_link.c` 单文件以 `-Os` 编译；其余仍按原有 Debug 选项编译。余量极小，后续不宜继续给 STM32 侧添加大功能，Wi-Fi/UI 应留在 ESP32。此结果只是离线编译，**未烧录、未复位、未接线、未测试**。

注意：这次离线编译已更新 `foc2_app_b/build/Debug/foc2.bin`，它现在是**未经板上验证的 Stage 10.2 B 槽镜像**，不能当作此前的已验证版本直接升级。A 槽源码及当前硬件固件没有因这次编译改变。

### 2026-09-26 双板 UART 诊断结果

为避免现有 STM32 APP 启动功率级，另建 `stm32_esp_link_diag`，通过 ST-LINK 临时加载到 STM32 SRAM（不写 A/B Flash），只启用 PC6=低、COM5 和 USART1 PA9/PA10。最初 STM32 能收到 ESP32 HELLO，但 ESP32 不回 STM32 PING；用户发现 PA9→ESP GPIO18 导线脱落并接回。复测 COM5 上 `ESP_HELLO=3→4`、`ESP_PONG=3→4`、`TX_FAIL=0`、`RX_OTHER=0`。这是实际双板 Router HELLO/PING/PONG 往返验证；**并非**正式 B 槽 Stage 10.2 固件上板验证。测试后 STM32 已 halt，PC6 输出锁存为低，驱动输入保持断电；复位、正式 B 槽验证需另行安排。详细过程见 `stm32_esp_link_diag/README.md`。

### 正式 B 槽升级门槛（只读核对）

2026-09-26 通过 ST-LINK 只读备份了板上 A 槽、B 槽及两份 V3 启动元数据，文件在 `stm32_esp_link_diag/backup_*_before_stage10_20260926.bin`。两份元数据 CRC 均有效；较新的 generation 234 表示 **confirmed=B、pending=none、attempts=0**。A 槽镜像 `225116 B` 的 CRC32 为 `F3F00847`，B 槽镜像 `226488 B` 的 CRC32 为 `14E28827`，均与元数据吻合。旧 generation 233 是先前试运行 B 的历史记录，不是当前状态。

新 Stage 10.2 B 源码离线构建仍通过，新镜像为 `229004 B`，距 224 KiB 槽尾仅余 **372 B**，CRC32=`1BEC667B`，与板上已确认 B 的 CRC 不同。**不能用 ST-LINK 直接覆盖当前 B**：这会破坏已确认镜像与元数据的 CRC 对应关系，也失去当前已确认版本。正式升级需要为非活动槽构建对应链接地址的镜像，并走已验证的 IAP 试运行/回滚/确认流程；同时现有完整 APP 在初始化 ESP 链路前会启 PWM、拉高 CTRL_SD 并做电流校准，驱动输入 0 V 时不能拿它做无功率级的 Router 验证。以上检查没有写 MCU Flash，也没有重启正式 APP。

### Stage 10.3：准备非活动 A 槽镜像（仅离线）

由于板上确认槽是 B，已将 B 槽的 discovery-only `esp_link.c/.h` 原样移植到 A 槽源码，并给 A 的 Router 增加 ESP32 端口、在 StartupTask 的 Router 初始化之后注册 ESP 链路。A/B 两份 `esp_link.c/.h` 经文本比较一致；没有把 ESP 来源的电机命令、参数修改或 IAP 请求开放到 Router。`cmake --build 'D:\new project\foc2_app_a\build\Debug' -j 4` 离线通过，A 镜像向量表指向 `0x08008000` 区间，大小 `229348 B`，CRC32=`0DEC0A31`，SHA256=`A7D2636D0A4CC3779CA58C37BFC45FD667BA7A838AB44AA62DCEEE40FCE88066`。

首次链接超出 224 KiB **4 B**，通过缩短一条新增的 ESP 启动日志后重新链接通过；现在 A 槽只剩 **28 B**，空间风险极高，不能继续无计划增加功能。A/B 现有源码还存在与槽位无关的差异，未盲目整文件覆盖。**新 A 镜像尚未烧录、尚未运行、不是已验证版本；板上 A/B 和启动元数据均未更改。** 若将来升级，需先解决完整 APP 在驱动断电时无法进入 ESP 链路的启动依赖，并按非活动槽 IAP 的备份、试运行、回滚与确认流程操作，不能直接用 ST-LINK 覆盖已确认 B。

### Stage 10.4：正式 ESP/Router 源码的 SRAM 隔离实测

新增 `stm32_esp_stack_diag`：直接编入 A 槽的 `esp_link.c`、`router.c` 与 FreeRTOS，使用 SRAM 链接、保持 PC6 低，完全跳过 PWM/ADC/SPI/FOC。用户重新实测驱动输入和 CTRL_SD 为 0 V 后才临时装入运行。COM5 显示 `ESP_NODE=1`、`DISC_RX=3→5`、`DISC_TX=6→10`、`PARSE_ERR=0`，验证正式 UART 中断、队列、白名单及 Router 发现流程在真实双板接线下可用。随后 `halt`，PC6 仍为输出低。**未写 Flash，未运行完整 A/B APP**；完整启动链和功率级安全仍需单独验收。细节见 `stm32_esp_stack_diag/README.md`。

### Stage 10.5：Flash 空间优化

前文 A 槽只剩 28 B、B 槽只剩 372 B 是**优化前历史值**。仅对非 FOC 的 Router、Modbus、Pigweed 日志桥和启动单元测试源码单文件启用 `-Os`，重新离线构建后 A=`212168 B`（剩 `17208 B`）、B=`211824 B`（剩 `17552 B`），两槽各节省 `17180 B`；RAM 各减少 16 B。两个新镜像均未烧录，板上 CRC 元数据不变。构建、回归测试与限制详见 `STAGE10_5_FLASH_SIZE_OPTIMIZATION.md`。

### Stage 10.6：A 槽完整 APP 通信安全启动入口

优化后只给非活动 A 槽增加一次性 B1 USER/PC13 启动选择：按键被检测到时，仅运行 Router + ESP discovery，不启动 PWM/FOC、不拉高 CTRL_SD、不运行 BootHealthTask。A 槽离线构建与主机回归通过，BIN=`213088 B`，剩余 `16288 B`。随后独立 SRAM 诊断实测 B1 为 PC13 空闲低、按下高、松开回低，ESP discovery 仍正常；**完整 A 槽尚未烧录或运行**，板上已确认 B 及启动元数据不变。详细操作、安全边界和验收条件见 `STAGE10_6_ESP_SAFE_COMM_BOOT.md` 和 `stm32_esp_stack_diag/README.md`。

### Stage 10.10：正式 APP PING/PONG（最新状态，覆盖上文历史“未验证”）

此前 A 槽安全通信与正常启动分别完成验收；随后 A/B 源码增加 `ESP PING` 受限往返。当前板上通过 COM5 IAP 写入并自动确认新 **B**，元数据 `CURRENT=B CONFIRMED=B PENDING=- GEN=244`。正式 B APP 对节点 2 的真实双板 PING/PONG 共 12/12 成功，且命令只由 COM5 发起；ESP 入站只有发现帧和精确 PONG 能通过白名单，不能进入电机通用命令解析。板上 A 保持上一版作为回退。Wi-Fi 与电机远程控制仍未实现。完整测试见 `STAGE10_10_ESP_PING_CLOSED_LOOP.md`。
