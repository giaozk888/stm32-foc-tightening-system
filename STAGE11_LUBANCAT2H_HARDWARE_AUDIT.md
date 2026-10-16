# 第十一章：LubanCat-2H 上位机硬件/系统只读审计

日期：2026-09-27。通过用户授权的临时 SSH 密钥对 `root@192.168.137.10` 进行了**只读**检查；未启用 CAN、未安装软件、未改设备树。临时公钥在检查后移除。

## 已核实

| 项目 | 板上实测 |
| --- | --- |
| 板型/系统 | LubanCat-2H，RK3568，Ubuntu 20.04.6，Linux 4.19.232，运行设备树 `rk3568-lubancat-2h.dtb` |
| CAN | `can0` 已枚举，驱动 `rockchip_canfd`，当前 `DOWN` / `STOPPED`，RX/TX 计数均 0；设备节点 `/sys/devices/platform/fe580000.can` |
| CAN 设备树 | `can@fe580000` 为 `okay`，`pinctrl-0=<0x222>` 对应 `can1m0-pins`；SoC 复用组为 GPIO1_A0/A1。用户提供的 EBF410331 V1R0 原理图第 18、31 页将这组引脚引至 J32，详见下文 |
| 显示 | `/sys/class/drm/card0-DSI-1/status=connected`，模式 `1024x600`；`/dev/fb0` 为 1024×600、32 bpp；另有 `/dev/dri/card0` |
| 触摸 | `Goodix Capacitive TouchScreen` 注册为 `/dev/input/event2`，路径含 `i2c-5/5-005d`；这里的 I²C 是触摸控制器，不是 CAN 通信链路 |
| 开发环境 | 有 gcc、g++、cmake、make、git、pkg-config、Python 3、`candump`、`cansend`、`evtest`；未查到系统预装的 LVGL 包、头文件或 `/opt`/`/usr/local` LVGL 源码 |

## 通信架构结论

用户照片中的 SIT1042AQT/3 模块是**CAN 收发器**，接逻辑侧 `TXD/RXD` 和总线侧 CANH/CANL，不提供 I²C 的 SDA/SCL。LubanCat-2H 已有原生 CAN 控制器，因此无须再走 I²C-CAN 控制器路径。预期链路是：

```text
STM32G474 FDCAN ─ CAN 收发器 ─ CANH/CANL ─ SIT1042 收发器 ─ RK3568 原生 CAN ─ Linux can0 ─ LVGL 上位机
```

### J32 原理图核对（用户提供的 `3531130937LubanCat2H_EBF410331V1R0_SCH_20240228.pdf`）

原理图第 31 页把 J32 命名为 **I2C PORT**；第 18 页显示相同的两根 SoC 管脚可复用为 CAN1_M0。板上当前运行的设备树已经选用了 `can1m0-pins`，因此此时 J32 的 2/3 脚应作为 **CAN 控制器的逻辑信号**，不是在 J32 上运行 I²C-CAN 转换。

| J32 针脚 | 原理图网络 | 当前 CAN1_M0 功能 | 与外置收发器的逻辑侧 |
| --- | --- | --- | --- |
| 1 | `VCC_I2C`，经 R285 0Ω 来自 `VCC_3V3` | 3.3 V 电源，**不是模块所需 5 V** | 仅在核实 SIT1042 模块 VIO 规格后考虑接 VIO；先实测 |
| 2 | `I2C3_SDA_M0`，经 R283 510Ω | GPIO1_A0 = `CAN1_RX_M0` | 接收发器 `RXD` |
| 3 | `I2C3_SCL_M0`，经 R281 510Ω | GPIO1_A1 = `CAN1_TX_M0` | 接收发器 `TXD` |
| 4 | GND | 共地 | 接收发器 GND |

原理图第 18 页还画出两根线上各有 4.7kΩ 上拉（R110/R111）到 3.3 V。这些板载电阻和 J32 前的 510Ω 串联电阻应在首轮低速/示波实测时纳入考虑；不能只凭软件出现 `can0` 就认定电气链路已通过。J32 不是 CANH/CANL 总线端子，**不得将其 2/3 脚直接接总线 H/L**。

**尚未完成的硬件核对：**J32 实物针脚方向及电压；SIT1042 模块 5V/VIO 的准确供电要求、是否已经有板载终端电阻；STM32 侧收发器与实际接线（候选 FDCAN 引脚见下文）；两个总线端点的 120Ω 终端配置。用户照片上模块有独立 `5V` 和 `VIO` 引脚，不能把 J32 的 3.3 V 直接当作 5 V 供电。未核对前不要上电联线。`can0 DOWN` 仅表示接口未配置/启用，不证明总线故障。

### STM32G474 / NUCLEO-G474RE 引脚审计（2026-09-27）

依据当前 `foc2_app_b` 源码、STM32CubeMX 的 `STM32G474R(B-C-E)Tx.xml` 管脚库，以及 ST 的 UM2505 NUCLEO-G474RE 手册连接器表：

| 功能 | MCU 引脚 | NUCLEO 排针 | 当前结论 |
| --- | --- | --- | --- |
| FDCAN1_RX | PB8/BOOT0 | **CN10-3** | 应用源码尚未占用；接 STM32 侧收发器的 `RXD` |
| FDCAN1_TX | PB9 | **CN10-5** | 应用源码尚未占用；接 STM32 侧收发器的 `TXD` |
| 备选 TX | PA12 | CN10-12 | 源码尚未占用；仅在 PB9 板级布线不适用时评估 |

**不要用 PA11**：它已是 `TIM1_CH4` 电机 PWM。**不要从 CN7-36 或 Arduino A4 取 PB9**：UM2505 把它标为 `PC1/PB9` 的共享/跳线选择节点，而 PC1 正用于 `TIM1_CH2` 电机 PWM；优先用 CN10-5 的 PB9 专用引出点。PB8 同时有 BOOT0 复用功能，接线前还须确认实物引脚、启动选项和外置收发器 `RXD` 的空闲电平/上电行为；不能把 5 V 逻辑直接接进 MCU。手册表格及默认焊桥状态不等于已经验证当前实物板的焊桥状态。

用户已确认另有一块与鲁班猫侧相同的 SIT1042AQT/3 收发器模块，供 STM32 端使用；用户还确认 `VIO` 为 3.3 V。尚未核实两块模块实物排针丝印、是否有待机控制脚及各自 5 V 供电来源。逻辑连接候选为 STM32 `PB9 → TXD`、`PB8 ← RXD`、`GND ↔ GND`；此表是**待实物确认的接线计划**，尚未上电实测。两模块总线侧应 `CANH ↔ CANH`、`CANL ↔ CANL`，并只在总线两端各保留一只 120Ω 终端。

目前工程尚未启用 `HAL_FDCAN_MODULE_ENABLED`，没有 FDCAN 初始化或 CAN 帧协议实现；上表只是**可用引脚审计，不表示 CAN 已接通或可通信**。两端都不能把控制器的 `TX/RX` 直接接到 `CANH/CANL`。

## 下一阶段

1. 对照 J32 实物丝印复核针脚方向；实测 1/4 脚电压，查 SIT1042 模块 5V/VIO 规格和终端电阻；再核对 STM32G474 的 FDCAN 引脚与另一端收发器。
2. 硬件接好后，先用经典 CAN、约定一致的位速率做双方收发/断线/错误帧测试；在通信层加序号、心跳、超时和 CRC/版本字段，再承载状态数据。
3. LVGL 首版在 1024×600 DSI/Goodix 环境显示只读运行状态、故障、固件槽、趋势和日志。Linux 端建议把 SocketCAN 接收线程与 LVGL UI 更新解耦。尚未安装 LVGL，也未运行 UI。

原先 Windows `upper_computer` 是 COM5 诊断工具，不是最终 LubanCat 屏幕上位机；其状态解析和显示字段可作为协议/界面参考，不能直接把 ASCII 串口帧当成 CAN 帧发送。

## FDCAN 首次发报文测试固件（2026-09-27，本地已编译，尚未烧录）

- 鲁班猫侧已由用户上电执行 `ip link set can0 up type can bitrate 500000`；截图显示 `UP`、500 kbit/s、`ERROR-ACTIVE`、错误计数 0、收发计数 0。此时 STM32 无发报文固件，零计数正常。
- 新增 `foc2_app_b` 的 `CanProbe` 构建预设，使用同版本 STM32Cube G4 V1.6.3 HAL FDCAN 驱动。它是**B 槽专用**镜像（链接地址 `0x08040000`），不可直接写入 A 槽。
- 探针镜像在启动后将 PC6/`CTRL_SD` 拉低，只初始化 FDCAN，不启动 TIM1 PWM、注入 ADC、FreeRTOS 或电机任务；以经典 CAN 500 kbit/s、标准 ID `0x701` 每秒发送一帧 8 字节：`43 41 4E 31`（ASCII `CAN1`）加 32 位大端递增序号。硬件拒收所有传入帧，不解析控制命令；自动重传关闭。
- 时钟来自 170 MHz PCLK1，名义位时序为预分频 17、Sync=1、Tseg1=16、Tseg2=3、SJW=2，合计 20 TQ/bit，采样点 85%。STM32 `PB8=RX`、`PB9=TX`，AF9。
- `cmake --preset CanProbe` 与 `cmake --build --preset CanProbe -j 6` 成功；测试 `foc2.bin` 105680 B，低于 224 KiB 槽限。正常 `Debug` 固件也重新构建成功，212872 B，和此前大小一致。用符号表检查测试 ELF 含 `CAN_LinkProbe_RunForever`、`HAL_FDCAN_Init/Start`，未链接 `StartupTask` 或 `PowerStage_Enable`。
- **尚未上板**：必须先确认当前活动槽与 IAP 目标，确保不会覆盖唯一可回退镜像；驱动功率输入保持 0 V，观察 `CTRL_SD=0 V`。鲁班猫执行 `candump can0,701:7FF` 预期看到 ID `701` 和递增序号。`HAL_FDCAN_AddMessageToTxFifoQ` 返回成功只表示入队，最终以 `candump` 实收及 CAN 错误计数判断链路成功。

### 槽位修正与 COM5 日志

用户随后贴出的启动日志明确写明 `APP SLOT: B @ 0x08040000`，且 `BOOT HEALTH: current slot is already confirmed`。因此**不得把 B 槽 CanProbe 镜像写入当前 B 槽**。日志中的 `0 ERR 103 BAD_REQUEST_ID` 说明发送 `FW STATUS` 时少了正整数请求 ID，正确格式如 `2000 FW STATUS`。

用户再执行 `2000 FW STATUS`，实测返回 `CURRENT=B TARGET=A ACTIVE=0 RX=0 SIZE=0 CONFIRMED=B PENDING=- ATTEMPTS=0`，因此 A 是当前非活动写入目标，B 为已确认的回退槽。相同日志的 `EN=1 FLT=0 MODE=IDLE` 表示截图时桥仍启用，不能据此推断当前已经断电；IAP 前应先用已确认 B 的 `ANALOG SAFE` 锁存关桥，再由用户关闭 PD6010B 功率输入并实测 0 V。A 探针试启动不含 BootHealthTask，不会自动确认；此轮只做通信测试，保留 B 作为回退。

用户授权直接上传后，通过 COM5 发 `2001 ANALOG SAFE`，实测回复 `LATCHED=1 SD=0 MOE=0 FOC=0`。随后以更新器的 `--stage-only` 模式向非活动 A 槽传输测试镜像，成功上传 **106056/106056 B**；最后 `FW STATUS` 为 `CURRENT=B TARGET=A ACTIVE=1 RX=106056 SIZE=106056 EXPECT=0x734D86F6 CONFIRMED=B PENDING=-`。镜像本地 CRC32 亦为 `0x734D86F6`。**尚未发送 `FW END`、尚未复位、A 尚未试启动、CAN 链路尚未实收验证。**下一步应先由用户关闭 PD6010B 功率输入并实测 0 V，再 `FW END` 触发 CRC 校验及 A 试启动。

用户回复功率输入已关闭后，COM5 再读 `FW STATUS` 仍为 B 当前、A 目标、`RX=SIZE=106056`、B 已确认。升级会话期间 `ANALOG SAFE STATUS` 被固件以 `FW_UPDATE_ACTIVE` 拒绝（该命令未执行）；此前安全锁存成功且期间未复位。随后 `FW END` 返回 `TARGET=A SIZE=106056 CRC32=0x734D86F6 COMMIT=BOOTLOADER ATTEMPTS=2 RESETTING`。A 探针在 COM5 启动，报告 `CAN PROBE ONLY: bridge disabled, no motor tasks`、`PB8 RX / PB9 TX, 500k classic, ID 701`，连续输出 `SD=0`。

**首轮 CAN 发报失败，不能标记为链路验收通过。**A 端 `HAL_FDCAN_AddMessageToTxFifoQ` 起初返回 0（入队），但 `TEC` 从 0 递增至 248，`LEC=5` 对应 HAL 的 `FDCAN_PROTOCOL_ERROR_BIT0`；随后 `BO=1`（bus-off），`enqueue=2`（HAL_BUSY），总线已停止有效发送。60Ω 终端检查仅证明两端电阻并联，不能证明收发器已工作、线序/逻辑正确或另端已 ACK。下一步先读鲁班猫 `ip -details -statistics link show can0`，检查 RX/错误计数及模块供电/待机状态，再决定是否需要重新试启动探针；保持 PD6010B 功率输入关闭。

鲁班猫端截图进一步显示 `can0` 虽为 `UP` / `ERROR-ACTIVE` / 500 kbit/s，但累计 `error-warn=1589`、`error-pass=566`、`bus-off=2106`；`RX packets=4261`、`RX errors=0`、`TX packets=0`。这些计数不能单独证明收到 ID `0x701` 的有效数据帧，尤其 bus-off 次数异常高。结合 STM32 的 `BIT0` 错误，下一步应核对两端收发器实际供电、`STB`（若实物有）电平/配置、TXD/RXD 引脚方向和 CANH/L 线序；未查明前不复位 A 反复重试。A 已 bus-off，当前不会持续发送有效帧。

用户确认实物模块**没有 STB**，且两端 5 V、VIO 供电及 CANH/L 线序已复核。按用户要求再次尝试时，COM5 先读到 A 探针 `BO=1 TEC=248 enqueue=2 SD=0`。使用 STM32CubeProgrammer 的 SWD **Hot Plug**（未复位 MCU）读 FDCAN1 `CCCR@0x40006418=0x41`，仅清除 `INIT` 位写入 `0x40` 试图使 CAN 控制器退出 bus-off。再次读取仍为 `0x41`，COM5 仍报告 `BO=1 TEC=248`；重试失败，没有烧录、系统复位或启动电机。后续需在两端保持供电且电机功率为 0 V 时测量 CANH/CANL 与 RXD 的静态对地电压，判断是否总线被拉成显性/逻辑反馈异常；避免无依据再次复位或反复发包。

用户在 `can0 down` 后以 STM32 模块 GND 为参考测得：`TXD≈2.8 V`，`RXD≈3.3 V`，`CANH≈3.3 V`，`CANL≈3.3 V`。静态读数说明两根总线线间约 0 V（隐性），但不能用万用表捕获 500 kbit/s 时的显性差分；TXD 高电平略低于 VIO 也不能单凭万用表判为故障。下一项有区分度的测试是在模块逻辑侧同时捕获 TXD/RXD，观察发出显性位时 RXD 是否同步变低；避免直接把逻辑分析仪接到 CANH/L。需要在 PulseView 开始采集后，才可仅恢复 FDCAN 外设发出短暂测试帧。

已把相同的 motor-disabled CanProbe 构建加入 `foc2_app_a`，链接地址 `0x08008000`；`cmake --preset CanProbe` 与 `cmake --build --preset CanProbe -j 6` 成功，A 测试镜像 `foc2_app_a/build/CanProbe/foc2.bin` 为 106056 B。符号表显示存在 CAN 探针而不含 `StartupTask`、`PowerStage_Enable`。A 的正常 Debug 镜像也重新编译成功，214128 B。**A 探针尚未上传/烧录，也没有接收报文实测结果**；上板前仍需获取带请求 ID 的 `FW STATUS`，核实 A 为可覆盖的非活动槽，并实测驱动功率输入为 0 V。
