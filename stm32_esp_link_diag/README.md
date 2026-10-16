# STM32 ↔ ESP32 串口通信专用诊断镜像（未烧录）

此工程是**独立的临时诊断镜像**，不是正式 `foc2_app_b`。可链接到 B 槽 Flash，也可链接到 SRAM 供调试器临时运行。只初始化 PC6、COM5（LPUART1 PA2/PA3）和 ESP 链路（USART1 PA9/PA10），115200 8N1。软件将 PC6 驱动使能保持低电平；不初始化 TIM1/PWM、ADC、SPI、FreeRTOS 或 FOC。每 5 秒向 ESP32 发送 Router HELLO 和无控制动作的 `42 PING`，在 COM5 报告收到的 ESP32 HELLO/PONG 数量。若收到 PONG，即验证了 STM32→ESP32→STM32 的应用层往返。实际 PC6 电平仍需万用表核查。

## 离线编译

默认构建为不写 Flash 的 SRAM 版：

```powershell
cmake -S 'D:\new project\stm32_esp_link_diag' -B 'D:\new project\stm32_esp_link_diag\build_ram' -G Ninja -DCMAKE_TOOLCHAIN_FILE='D:\new project\stm32_esp_link_diag\toolchain.cmake' -DCMAKE_BUILD_TYPE=Release -DDIAG_RUN_FROM_RAM=ON
cmake --build 'D:\new project\stm32_esp_link_diag\build_ram'
```

其 ELF 中所有可装载段都位于 `0x20000000` 起的 SRAM，调试器下载后可执行，不写 A/B Flash。复位或断电即消失，仍需确保调试器只对 RAM 执行 `load`，不要执行 `flash write`。CMake 也保留 `DIAG_RUN_FROM_RAM=OFF` 的 B 槽离线构建选项，但不用于本次测试。

SRAM 版离线编译通过：`.isr_vector=0x20000000`，初始 SP `0x2001FFC0`，当前 PING 版占用 RAM 13,208 B。因测试会暂停当前 STM32 固件，运行前需确认 PD6010B 驱动电源断开并实测输入 0 V、PC6/CTRL_SD 保持低电平、ESP/STM32 共地及 UART 交叉连接。

2026-09-26 离线编译通过：BIN 为 **10,652 B**，FLASH 10,652/229,376 B，RAM 2,304/131,008 B；向量表位于 `0x08040000`，初始 SP 为 `0x2001FFC0`，复位入口为 `0x08040651`。BIN SHA256：`26483E47E5DA368B8284147A284CBFDF1F2945A2649163DBE2B568C68993B7C8`。这些只是静态/编译检查，不等于 MCU 实测。精简 C 运行库的 `_close/_read/_write/_lseek` 未实现警告来自 nosys 占位；本程序不用文件 I/O。

链接地址来自现有 B 槽 linker script：`0x08040000`、224 KiB。构建结果**不能直接作为已验证的正式升级包**。刷入 B 槽会覆盖当前 B 镜像；是否启动 B 还取决于 bootloader 的 A/B 元数据和有效性检查，不能仅靠刷写 BIN 保证。必须先确认当前槽位、备份/恢复方案、驱动电源和硬件状态，并单独决定是否进行。当前只允许离线编译，不执行烧录/复位。

接线目标：STM32 PA9 TX→ESP GPIO18 RX，STM32 PA10 RX←ESP GPIO17 TX，GND↔GND；两板各自供电。未通过实际两板联机测试前，`ESP_HELLO=0` 不足以判断是线、针脚、供电还是固件启动问题。

## 2026-09-26 首轮实测

用户确认 PD6010B 输入端与 CTRL_SD 对地均为 0 V。通过 ST-LINK/OpenOCD/GDB 只将 RAM ELF 装入 `0x20000000`，未写 A/B Flash。COM5 观察到 `ESP_HELLO` 持续增长（例如 9→10、39→40），`RX_OTHER=0`，证实 ESP GPIO17→STM32 PA10 的链路可用。加入只发送无控制动作 `42 PING` 的版本后，COM5 显示 `TX_OK=6→10`、`TX_FAIL=0`、`ESP_HELLO=2→4`、`ESP_PONG=0`；COM9 可打开但这次未读到接收日志。因此 **STM32→ESP 的物理/协议方向尚未通过**，不能宣称双向握手完成。STM32 的 USART1 软件发送成功不等于 ESP GPIO18 收到，下一步优先复核 PA9→GPIO18 导线、GPIO18 丝印和两板 GND，并用逻辑分析仪或电压/波形证实 ESP RX 端信号；随后再考虑 ESP 接收日志。

测试结束通过 OpenOCD `halt` 停止 RAM 诊断程序；读到 GPIOC MODER=`0xFFFFDFFF`（PC6 为输出模式）、ODR=`0x00000000`（PC6 输出锁存为低），目标状态为 `halted`。**这不是恢复正常 APP；驱动电源继续保持关闭。** 只有在完成安全检查后，才允许复位回正常固件。OpenOCD 当前仍占用 ST-LINK，供后续排查使用。

## 2026-09-26 接线修复后复测

用户发现 STM32 PA9→ESP GPIO18 的导线脱落并接回，确认 PD6010B 输入和 CTRL_SD 仍为 0 V。重新只向 SRAM 加载同一通信诊断 ELF（LOAD 段起始 `0x20000000`，未写 A/B Flash）；COM5 实测：

```text
DIAG SD=0 PWM=OFF TX_OK=8 TX_FAIL=0 ESP_HELLO=3 ESP_PONG=3 RX_OTHER=0
ESP PONG RX OK
ESP HELLO RX OK
DIAG SD=0 PWM=OFF TX_OK=10 TX_FAIL=0 ESP_HELLO=4 ESP_PONG=4 RX_OTHER=0
ESP PONG RX OK
ESP HELLO RX OK
```

ESP32 只有收到 STM32 发出的 `42 PING` 才会回应 `42 OK ESP32 PONG`；因此 PONG 计数递增验证了 **STM32 PA9→ESP GPIO18、ESP GPIO17→STM32 PA10 的应用层双向往返**，不再只是单向 HELLO。测试后执行 OpenOCD `halt`，目标确认为 `halted`，PC6 MODER=`0xFFFFDFFF`（输出）、ODR=`0x00000000`（低）。保持 PD6010B 驱动电源关闭；尚未测试正式 B 槽 Router 固件、重启后的运行或电机功能。

## 正式 B 固件上板前的只读核对

同日又从板上读取并备份完整 A/B 槽与两个 V3 元数据页：

| 备份文件 | 长度 | SHA256 |
| --- | ---: | --- |
| `backup_a_before_stage10_20260926.bin` | 229376 B | `A69EA038B96C639E19E1AA2AA5A8DBE9112054A090578A1419606B519D291688` |
| `backup_b_before_stage10_20260926.bin` | 229376 B | `D2EC490872CF9133DA65AB820570B12618DE133601C2AEEE794D7AEC07B61C1B` |
| `backup_bootmeta_before_stage10_20260926.bin` | 4096 B | `3D583DF1573B3B99527B3E9BFE7C42B50DE5D2247E2D65A486F8CBF857ECA16E` |

最新有效元数据位于 `0x0807E800`，generation 234，confirmed=B、pending=none、attempts=0；A 镜像大小 225116 B/CRC32 `F3F00847`，B 镜像大小 226488 B/CRC32 `14E28827`，与实际读回一致。旧副本 generation 233 为先前 pending=B 的历史状态。新编译的 Stage 10.2 B 镜像是 229004 B/CRC32 `1BEC667B`，不是已确认的 B 镜像；**不可直接覆盖 B 槽**。完整 B 启动顺序是先 ADC/编码器、PWM、CTRL_SD 高、电流校准，再初始化 Router/ESP；因此保持驱动断电时不能靠重启它验证正式链路。下一步需要为非活动槽准备可回滚升级方案，并另行通过安全条件核查。当前 STM32 仍为调试器 halt 状态，驱动输入应保持 0 V。

## 上板后预期判据（尚未执行）

- STM32 COM5 首行出现 `COMM ONLY; PC6 SD=0; PWM/FOC OFF`；万用表复核 CTRL_SD≈0 V，驱动输入仍为 0 V。
- STM32 COM5 每 5 秒的 `ESP_HELLO` 计数递增，且出现 `ESP HELLO RX OK`：证明 ESP GPIO17→STM32 PA10 的接收方向。`TX_OK` 计数递增、`TX_FAIL=0` 仅说明 STM32 USART1 软件发送完成，不能单独证明 ESP GPIO18 收到了电平。
- ESP32 自身 USB 日志每 5 秒出现 `RX src=1 dst=2 type=3 payload=HELLO`：证明 STM32 PA9→ESP GPIO18 的接收方向。
- 或者 STM32 COM5 的 `ESP_PONG` 计数递增、出现 `ESP PONG RX OK`：ESP32 只有收到发给节点 2 的 `42 PING` 才会回 PONG，因此这是不依赖 ESP USB 日志的双向闭环判据。
- 上述只验证 UART 物理链路和发现帧，**不**验证正式 B 槽 Router 任务、电机控制或功率级安全。若计数不增，保持驱动电源关闭并检查交叉接线、两板 GND、GPIO 丝印、115200 8N1，再分析固件。
