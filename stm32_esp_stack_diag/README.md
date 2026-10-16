# Stage 10.4：正式 ESP transport + Router 的 SRAM 隔离测试

此工程直接编入 `foc2_app_a/Core/Src/esp_link.c` 和 `router.c`，加 FreeRTOS、HAL 与只发日志的诊断外壳；并非复制一套“模拟实现”。运行时只用 PC6=低、LPUART1 COM5、USART1 PA9/PA10；**不**初始化 TIM1/PWM、ADC、SPI 或 FOC，且所有可装载段都在 SRAM。驱动输入必须断电并实测 0 V；结束后 halt，不复位正式 APP。这个验证不能代替完整 A 槽固件上板验收。

```powershell
cmake -S 'D:\new project\stm32_esp_stack_diag' -B 'D:\new project\stm32_esp_stack_diag\build' -G Ninja -DCMAKE_TOOLCHAIN_FILE='D:\new project\stm32_esp_link_diag\toolchain.cmake' -DCMAKE_BUILD_TYPE=Release
cmake --build 'D:\new project\stm32_esp_stack_diag\build'
```

预期 COM5 每 2 秒打印 `REAL-STACK ... ESP_NODE=1 DISC_RX=...`，发现数持续增长；这说明真正的 ESP IRQ→RX 队列→白名单→Router 发现流程打通。此测试明确不会接收 ESP 来源的电机、参数和 IAP 命令。镜像只允许调试器向 SRAM `load`，**不可写入 A/B Flash**。

## 2026-09-26 实测结果

用户重新实测确认 PD6010B 输入端和 CTRL_SD 均为 0 V、三根 UART/GND 接线牢固。ARM ELF 校验仅有一个 LOAD 段，从 `0x20000000` 开始，RAM 总占用 **44,080 B**，初始 SP=`0x2001FFC0`，入口=`0x200004D9`。经 ST-LINK/OpenOCD/GDB 仅装入 SRAM；未向 A/B Flash 或启动元数据写入。

COM5 连续观测：

```text
REAL-STACK SD=0 PWM=OFF ESP_NODE=1 DISC_RX=3 DISC_TX=6 PARSE_ERR=0
REAL-STACK SD=0 PWM=OFF ESP_NODE=1 DISC_RX=4 DISC_TX=8 PARSE_ERR=0
REAL-STACK SD=0 PWM=OFF ESP_NODE=1 DISC_RX=5 DISC_TX=10 PARSE_ERR=0
```

`ESP_NODE=1` 表示 Router 已经从 `ROUTER_PORT_ESP32` 学到节点 2；`DISC_RX` 增加且 `PARSE_ERR=0`，证明 ESP32 HELLO 经正式 USART1 中断、FreeRTOS RX 队列、discovery 白名单和 Router 解析。`DISC_TX` 增加证明 Router 把发现包交给正式发送端口队列；ESP32 端是否收到这些**具体** Router 帧，此次没有独立抓包，不能仅凭 `DISC_TX` 推断。此前简单 SRAM 诊断的 PING/PONG 已独立证实物理双向接线可用。

结束后已执行 `halt`；目标确认为 `halted`，GPIOC MODER=`0xFFFFDFFF`（PC6 输出），ODR=`0x00000000`（PC6 低）。驱动输入继续保持关闭。尚未运行完整 A 固件，也未验证其启动时序、电机保护或 A/B 升级确认。

## Stage 10.7：B1/PC13 实物极性诊断（待上板）

为核对 Stage 10.6 安全启动入口，SRAM 诊断程序额外将 PC13 配成下拉输入，并以 20 ms 间隔采样；COM5 每 2 秒附带输出 `PC13=<当前电平> RISE=<累计上升沿> FALL=<累计下降沿>`。按住 B1 超过 2 秒再松开，应该观察到空闲 `PC13=0`、按下 `PC13=1`，且 RISE/FALL 各增加 1。如果不是这样，不能用 A 槽的 B1 安全入口，需要先修改极性或核对板上焊桥。

改动后已离线构建通过。ELF 唯一 LOAD 段仍在 SRAM，入口 `0x20000579`，RAM 使用 **44,280 B**；没有 TIM1/PWM、ADC、SPI、FOC 初始化，也未对 A/B Flash 或启动元数据执行写入。

2026-09-26 用户重新实测 PD6010B 输入端与 CTRL_SD 均为 0 V 后，通过 `reset halt` 停在 bootloader 内，再仅向 SRAM 装载诊断 ELF，没有运行旧的完整 APP。COM5 观察到空闲 `PC13=0 RISE=0 FALL=0`、按住 B1 时 `PC13=1 RISE=1 FALL=0`、松开后 `PC13=0 RISE=1 FALL=1`；同时 `ESP_NODE=1`、`DISC_RX=5→18`、`PARSE_ERR=0`。因此本板 B1 确实接 PC13，按下为高，Stage 10.6 的按键条件与实物吻合。测试后已再次 halt：GPIOC ODR=`0x00000000`（PC6 低）、TIM1 BDTR=`0x00000000`（MOE 低）；完整 A 槽安全模式及 IAP 仍未上板验证。
