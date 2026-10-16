# 2026-09-28：只读状态帧上板前检查

## 结论

`0x180` 状态帧的正常 APP A/B 代码已构建通过，HMI 解码单元测试通过，
鲁班猫新界面运行中；**本次没有刷写 STM32 Flash**。后续 SRAM 诊断
`0x180` 已在实物 CAN 总线上被鲁班猫收到，但正式 APP 状态帧尚未实测。
当前 STM32 确认运行目标为 B 槽，但程序停在启动期的静态电流零点校准
失败处理，不能接收 `FW STATUS`，也不会运行发送状态帧的 `MonitorTask`。

## 只读证据

- ST-LINK HOTPLUG 检测到 NUCLEO-G474RE，目标电压约 3.29 V。
- 启动轨迹 SRAM `0x2001FFE0`：最后目标为 B，确认槽 B、待试槽空、
  尝试次数 0。当前 `VTOR=0x08040000`（B 槽）。
- 多次读取 PC 稳定落在 `0x08058D02/04`；对当前 B 槽 Flash 备份反汇编，
  此处是 `Error_Handler` 中的关中断死循环。栈中保存的调用返回地址
  `0x08056DD5` 对应 `ADC_CurrentZeroCalibrate()` 返回失败后的调用点，
  即 `STATIC CURRENT ZERO CAL FAILED`。这解释了 COM5 完全无响应。
- COM5 是 ST-LINK 虚拟串口；PowerShell SerialPort 与 pyserial 均能打开，
  发送 `FW STATUS` 后收到 0 字节。该 APP 的 UART RX DMA/命令处理在
  校准之后才启动，故当前不能使用 A/B UART IAP。
- `GPIOC ODR=0x00000000`，驱动使能 PC6 为低；`TIM1 BDTR=0x02002055`，
  MOE 位为 0。这里是 MCU 寄存器快照，不替代外部电气测量。
- Boot Metadata V3 最新副本：`CONFIRMED=B, PENDING=0, ATTEMPTS=0,
  GEN=252, B_SIZE=212872, B_CRC32=395DD27E`；读取的 B 槽前
  212872 字节 CRC32 同为 `395DD27E`。最新记录中的 A 镜像大小为 0，
  因此不能假定直接覆盖 B 槽还有可用 A 槽自动回滚。

## 已保存的只读备份

目录：`D:\new project\safety_backups\2026-09-28-can-status`

| 文件 | 大小 | SHA-256 |
| --- | ---: | --- |
| `app_a_before_can_status.bin` | 229376 B | `B9880F217071B9055D45FE33A9C7779B3C0091182F5E4BB659EDEE5589B51D96` |
| `app_b_before_can_status.bin` | 229376 B | `71786806D882EC960004407B665867CE2D4E1A1503C614F06A5225B451F37F9F` |
| `boot_metadata_before_can_status.bin` | 4096 B | `365FCBDA91483CFC2E14EB493BD2A896968740CE436C5079512B2B09852D55A9` |

## 下一步的安全门槛

先排查/恢复静态电流零点校准所需的 PD6010B 12 V 采样供电、
AMP_IU/AMP_IV 到 PA0/PA1 的模拟链路和 ADC 读取。当前软件规定两路
平均原始值必须在 1000–2200，且采样过程不能报错；本次仅能确认
`ADC_CurrentZeroCalibrate()` 失败，不能据此断言是哪一路或供电故障。
驱动使能与机械端必须保持安全隔离。待正常 APP 启动、COM5 可回应且
`MODE=IDLE`、无故障后，再通过标准 UART IAP 写入非活动槽并按 A/B
试运行和回滚流程验证。不要为了看到 `0x180` 而绕过校准、直接覆盖
已确认的 B 槽或修改元数据。若要在无 12 V 条件下先检查显示解码，
可单独使用安全的模拟帧或 SRAM 诊断；它们不等于正式 APP 验收。

## SRAM 状态帧探针补充测试

为隔离正常 APP 启动校准失败的影响，构建并在 SRAM `0x20000000` 运行
`CAN_STATUS_V1_PROBE`。此镜像不写 Flash、不启动 ADC/PWM/FOC，PC6
保持低，最多尝试 50 帧标准 CAN `0x180`、500 kbit/s；数据中的
`0xFFFE` 是诊断故障标记，不代表正常 APP 已启动。加载后通过 SRAM
读回逐字节比对验证。注意：OpenOCD 的 `verify_image` 会在目标 RAM
放入校验代码，可能覆盖 RAM 向量表；本次改用 `dump_image` 比对。

COM5 报告 `enqueue=0`（HAL_OK），但 `TXBTO=0`，发送错误计数 TEC
由 8 升到 128。鲁班猫 `candump -L can0,180:7FF` 在测试窗口内收到
0 帧。之后只读检查 STM32：FDCAN1 `CCCR=0x43`（INIT=1，已停），
`PSR` 曾为 `0x80`（bus-off 标志），稍后为 `0x767`（无 bus-off 标志、
错误被动/警告标志）；`ECR=0x80`（TEC=128）；`GPIOC ODR=0`（PC6=0），
`TIM1 BDTR=0x02002055`（MOE=0）。因此这次测试不能证明 HMI 解码
有错，也不能证明链路已通；当前首先要恢复并验证物理 CAN 链路的
应答。不要把 SRAM 探针帧当成正常 APP 的状态帧验收。

本次仍未刷写正常 APP 或修改启动元数据。用户确认接线未改，因此不能
把此次失败直接归因于接线变化。随后只读复查：鲁班猫 `can0` 仍为
500 kbit/s、DEFAULT 模式、UP，但状态为 ERROR-PASSIVE；RX=58、
bus-off 累计=35，两次间隔读取计数未继续增长。当前 pinctrl 将
GPIO1_A0/A1（pin 32/33）分配给 `fe580000.can` 的 `can1m0-pins`，
I2C1 在 GPIO0-11/12，未抢占 CAN1；运行中的 HMI 只接收原始帧。
STM32 RCC CCIPR 选择 PCLK1 为 FDCAN 内核时钟，NBTP 对应 500 kbit/s，
PB8/PB9 处于 AF9。`0x180` 和 `0x701` 的 ID 差异不会改变 CAN ACK 规则。
不能只凭这次失败判断故障部位。正常 APP 卡在校准，
在没有可用回退槽的情况下不覆盖已确认的 B 槽。

## 同接线复测：`0x701` 与 `0x180` 均收到

用户确认接线未改。检查发现鲁班猫 `can0` 仍是 500 kbit/s DEFAULT 模式，
GPIO1_A0/A1 仍归 CAN1，STM32 PB8/PB9 AF9、FDCAN PCLK1 和位时序也符合
500 kbit/s。第一次重启 SRAM 对照探针时，串口无输出，因此补充了外设
复位和 SysTick COUNTFLAG 轮询，并在 SRAM 中留下阶段标记，确认探针
真正跑完 10 次发送。探针 ELF 仅有 SRAM LOAD 段，每次都以读回镜像
SHA-256 一致确认；未写 Flash 或复位 MCU。

同步抓取的 `0x701` 对照帧：鲁班猫 `candump` 实收序号 1–9；STM32 COM5
报告 `enqueue=0`、`TXBTO` 非零、TEC/REC/BO/LEC 均为 0，最终提示
`CAN stopped; SD=0`。随后同样方式运行状态格式探针，鲁班猫实收
`180#010002FEFF1C0000` 等 10 帧（序号 28–38 中缺 34），约 100 ms
一帧；STM32 报告从 seq0 起 `TXBTO` 非零、绝大部分 TEC=0，seq40
时 TEC=2，最终也停止 CAN。该轻微错误及抓包序号缺口说明后续仍应
做长时间稳定性测试，但基本双向物理链路和 `0x180` 接收已获实证。

收尾只读检查：FDCAN `CCCR=0x43`（停止），GPIOC ODR=0（PC6 低），
TIM1 BDTR=`0x02002055`（MOE 清零）；鲁班猫 HMI 进程仍在运行。
`0xFFFE` 是 SRAM 探针的专用故障标记，**不是**正常 APP 的真实故障码。
本次只证明原始 `0x180` 帧抵达鲁班猫；尚未从实物屏幕确认 HMI 对它的
视觉显示，也未验证正常 APP 启动和持续状态发送。早先那次 bus-off
不能再归因于“用户改了接线”；其瞬态原因仍未确定。

## 2026-09-29：A 槽镜像已暂存，未试运行

正常 B APP 本次通过启动校准并回应串口命令：`FW CURRENT=B TARGET=A
ACTIVE=0 CONFIRMED=B PENDING=-`，`MODE=IDLE FLT=0`。但升级前读到
`ANALOG SAFE LATCHED=0 SD=1 MOE=1 FOC=1`，说明即使业务模式空闲，
功率级仍被使能。先执行 `ANALOG SAFE`，收到 `LATCHED=1 SD=0 MOE=0
FOC=0`，随后才启动 IAP 写入。

鲁班猫重启后 `can0` 为 DOWN、临时 HMI 服务不存在；已把 `can0` 恢复为
500 kbit/s，临时启动 `lubancat-hmi-status.service`，确认 HMI 进程和 MIPI
图层运行。没有设置开机自启，原摄像头服务仍禁用。旧 B APP 不含正式
`0x180`，故当前 `can0` RX=0，3 秒监听也未收到 `0x180`。

本地 A 镜像 `foc2_app_a/build/Debug/foc2.bin` 为 216760 B，CRC32
`B59872A4`，SHA-256
`3B7542F84BA102FCE6102B2DD9E92BAC6165E82AA71703B78570210EE39AC278`；
链接起址 `0x08008000`，大小小于 A 槽 229376 B。更新脚本新增
`-StageOnly` 和功率级锁存安全态检查。本次仅向非活动 A 槽执行
`FW BEGIN`/`FW DATA`，末次 `FW STATUS` 回应 `ACTIVE=1 RX=216760
SIZE=216760 EXPECT=0xB59872A4 CONFIRMED=B PENDING=-`。通过 HOTPLUG 从
`0x08008000` 回读相同 216760 B，SHA-256 与本地镜像完全相同；回读文件为
`safety_backups/2026-09-28-can-status/app_a_staged_can_status_readback.bin`。

**尚未发送 `FW END`，未重启、未将 A 设为待试槽、未确认新固件。** 写入后
HOTPLUG 寄存器读数 `GPIOC ODR=0x00000000`、`TIM1 BDTR=0x02002055`
（MOE=0），B 仍为确认槽。`FW END` 会重启进入 A 试运行；A 的启动流程
可能重新使能功率级，因此必须先确保电机供电或机械负载处于可安全试运行
状态。若在执行 `FW END` 前设备复位，当前 RAM 中的 IAP 会话会消失，
需要重新开始 IAP；不可把已写入 A 槽等同于已完成升级。

## 2026-09-29：A 槽试运行与正式状态帧验收

用户确认电机功率或机械负载已隔离后，复核 `FW STATUS` 仍为
`CURRENT=B TARGET=A ACTIVE=1 RX=216760 SIZE=216760
EXPECT=0xB59872A4 CONFIRMED=B PENDING=-`。HOTPLUG 确认 PC6 ODR=0、
TIM1 MOE=0；鲁班猫 `can0` 为 500 kbit/s ERROR-ACTIVE，HMI 服务在运行。
随后只发送一次 `FW END`，响应为 `TARGET=A SIZE=216760
CRC32=0xB59872A4 COMMIT=BOOTLOADER ATTEMPTS=2 RESETTING`。

A 槽试运行启动且 `MODE=IDLE FLT=0`，健康检查在约 5 秒后自动请求
确认并重启（无需人工 `FW CONFIRM`）。最终 `FW STATUS`：
`CURRENT=A TARGET=B ACTIVE=0 CONFIRMED=A PENDING=- ATTEMPTS=0 GEN=255`；
`STATUS` 仍为 `MODE=IDLE FLT=0`。新程序重启后会重新使能功率级，
所以验收后再次执行 `ANALOG SAFE`，回应 `LATCHED=1 SD=0 MOE=0 FOC=0`。
该锁存状态只持续到下次复位。

鲁班猫实收正常 APP 的标准 CAN `0x180`，约每 100 ms 一帧、序号连续。
安全态前载荷例 `01000D0000620000`，安全态后例
`01000400008D0300`；两者都为版本 1、IDLE、故障 0，标志位随实际
功率级/FOC 状态变化。5 秒监听期间 `can0` 错误、丢包、bus-off 均为 0；
RX 计数从 204 增长到 974，TX=0。HMI 进程保持 active，`/proc/net/can`
显示它注册了 `can0` 原始帧接收。独立离屏实况截图
`lubancat_hmi/status-live-2026-09-29.png` 显示“STM32 状态有效”、
连续 `0x180` 帧、RX 1655、TX 0，证实界面解码已连上真实 APP。
板上系统时间仍显示 2024-06-18，截图时间戳不可当作实际日期；后续
追溯记录需要先解决时钟同步。

本次完成的是只读状态链路，不包括扭矩/角度测量、控制命令、工单或配方
验收。HMI 仍以临时服务运行，未设置开机自启；下次鲁班猫重启需重新
配置 `can0` 并启动 HMI。STM32 下次复位也会退出 `ANALOG SAFE`，不可
把当前功率级关断状态视为永久联锁。

## 2026-09-29：60 秒收帧稳定性与手动校时

在 A 槽已确认、`ANALOG SAFE LATCHED=1 SD=0 MOE=0 FOC=0`、
HMI 运行且 `can0` 为 500 kbit/s 的状态下，只读抓取正常 APP 的
`0x180` 帧 60 秒：共 602 帧，首末序号 5235→5836，零缺帧、零重复。
相邻帧间隔最小 99.313 ms，中位数 99.759 ms，95 分位 99.860 ms，
最大 100.159 ms；所有帧的非序号字节均为 `01 00 04 00 00 .. .. 00`
（版本 1、IDLE、编码器有效、功率级关闭、故障 0）。测试后 `can0`
仍为 ERROR-ACTIVE，RX 6365、TX 0、RX 错误 0、丢包 0、bus-off 0，
HMI 服务 active。

时间诊断发现板上 `ntpd` 虽在运行，但持续报 NTP 域名 DNS 解析失败，
系统时钟与 RTC 均停在 2024-06-18。以当前平台 UTC 为依据，手动校正
系统时钟并执行 `hwclock -w`；板上随后显示 2026-09-29 11:08 CST，
RTC 与系统时间一致。校时后 HMI 继续显示“STM32 状态有效”，CAN 错误
计数仍为 0。新的实况截图为
`lubancat_hmi/status-live-clock-fixed-2026-09-29.png`，屏幕时间和接收帧
时间均已更新到 2026-09-29。**这只是手动校时，尚非长期自动同步**；
网络 DNS/NTP 恢复前，不能保证重启后或长期运行的时间精度。

## 2026-09-29：状态超时/恢复逻辑与 HMI 切换

下一步希望验证状态帧中断时 500 ms 超时及随后恢复。为避免让实体 STM32
失去 CAN ACK，没有关闭真实 `can0` 或拔线。尝试隔离的网络命名空间，
但板上内核配置为 `# CONFIG_CAN_VCAN is not set`，无法创建虚拟 CAN。
因此本次只验证软件逻辑，**不是实体断线试验**。

将 HMI 的状态跟踪逻辑抽为 `status_v1::Tracker`，由单调时钟提供毫秒时间；
500 ms 内状态有效，501 ms 时过期；有效窗口内重复/倒退序号不刷新，
超时后允许设备重启导致的序号回退，新帧可恢复为有效；16 位序号回绕
仍按前进处理。Windows 与鲁班猫 ARM 上的 `status_v1_test` 均通过。

部署前备份旧板上二进制及源码于
`safety_backups/2026-09-29-hmi-tracker/`。新版本在独立的
`/home/cat/lubancat_hmi/build_tracker` 构建，没有覆盖旧二进制；
离屏实况截图 `lubancat_hmi/tracker-preview-2026-09-29.png` 显示
“STM32 状态有效”和连续 `0x180`。随后停止旧临时服务，启动新临时
`lubancat-hmi-tracker.service`，确认进程、MIPI DRM 图层和 CAN 原始帧
接收注册均正常，`can0` 错误/丢包/bus-off 为 0，TX=0。仍未设开机自启。
STM32 最终复查 `CONFIRMED=A PENDING=-`、
`ANALOG SAFE LATCHED=1 SD=0 MOE=0 FOC=0`。

实体断线后的总线错误恢复、HMI 在实际断线时的画面、以及重启后的
自动启动/时间同步，仍须单独验收。当前不能据此宣称完整链路失联
测试已经完成。

## 2026-09-29：CAN 与 MIPI HMI 持久启动配置

先只读复查：`can0` 为 500 kbit/s、`restart-ms 100`、ERROR-ACTIVE，
接收计数持续增长，RX/TX 错误、丢包、bus-off 均为 0，TX=0；
`lubancat-hmi-tracker.service` 临时服务仍运行。旧 MIPI 摄像头两项服务
均 inactive/disabled，`lightdm` inactive。`can0` 的 systemd device unit
处于 active，板上 `/usr/bin/openvt`、触摸设备及 EGLFS KMS 配置文件存在。

新增 `systemd/lubancat-can0-setup.sh`、`lubancat-can0.service`、
`lubancat-hmi.service`，安装到板上 `/usr/local/libexec` 和
`/etc/systemd/system`。配置脚本在已 UP 且参数正确时直接返回；若已 UP
但参数不同则拒绝扰动真实 CAN 总线。`sh -n` 与 `systemd-analyze verify`
通过；验证命令只有系统原有 snapd 服务的 `RestartMode` 兼容性警告，
没有新增服务语法错误。两个新服务均已 `enable`。启动 CAN 服务未重配
运行中的接口；停止旧临时界面、启动持久界面后，HMI 进程保持 active，
DRM `video_port1` 有 1024×600 图层，RX 从 40980 增至 41674，
TX=0，CAN 错误、丢包、bus-off 均为 0。
随后新服务保持 active、`NRestarts=0`，独立离屏实况截图
`lubancat_hmi/startup-diagnostic-2026-09-29.png` 显示“STM32状态有效”、
连续 `0x180` 和 RX 42763 / TX 0。该截图验证业务解码，不替代实物
重启后的 MIPI 显示验收。

未重启鲁班猫或 STM32，故**开机自动恢复仍待重启实测**。当前 STM32
`ANALOG SAFE` 只在本次运行中有效，STM32 复位后会清除；协调重启前
须重新确认电机功率或机械负载的物理隔离。时间复查显示 RTC 与系统时间
同为 2026-09-29 CST，但 `ntpq -pn` 中所有池服务器 reach=0，
`timedatectl` 为 `NTPSynchronized=no`，DNS 查询未返回地址。
未更改现有网络/DNS/NTP 配置，不能宣称自动校时完成。

## 2026-09-29：电机测量与上位机交互第一阶段（尚未上板）

用户要求开始电机与上位机交互，并确认电机功率供电或机械负载仍已物理隔离。
当前 STM32 实际状态经 COM5 只读确认：`CURRENT=A TARGET=B ACTIVE=0
CONFIRMED=A PENDING=-`，`ANALOG SAFE LATCHED=1 SD=0 MOE=0 FOC=0`，
`STATUS MODE=IDLE FLT=0`。此次未发送任何电机运行命令。

为避免在扭矩标定、安全联锁和通信超时策略尚未验收时开放执行，先实现
**STM32 → 鲁班猫**只读测量交互：新增 `0x181` 相对机械角/q 轴电流、
`0x182` 机械转速/母线电压估算，各约 10 Hz；字段按有效性编码，
无效的 q 轴电流不显示为零或扭矩。HMI 仅在 `0x180` 状态和对应测量帧
均新鲜、序号前进且状态位允许时显示测量值；状态超时后恢复会清空测量
缓存，防止跨重启旧值瞬显。触屏启动、停止、配方下发仍禁用，STM32 的
FDCAN 接收过滤仍拒绝所有入站数据与远程帧。

本地 STM32 A/B 镜像构建通过，分别 217944 B / 216688 B，均小于
224 KiB 的槽容量；Windows HMI 构建、状态帧与测量帧单元测试通过，
离屏总览截图为 `lubancat_hmi/measurement-preview-2026-09-29.png`。
Windows 预览起初因 Qt DLL 路径不匹配报入口点错误；匹配 Qt 路径后又
发现界面刷新访问已移除卡片的空标签，已修复，最终预览退出码 0。

板上已建立独立源码目录并复制过初版 HMI 源码，但随后 ARM 编译调用
因工具审批额度耗尽被拒绝，**命令没有执行**；离线后续修订也尚未重传。
旧版 `lubancat-hmi.service` 和已确认的 STM32 APP A 没有切换或刷写，
所以真实设备此时只应继续显示/发送 `0x180`，不能宣称已收到 `0x181`、
`0x182`。下一步须在审批恢复后先重传最终源码、板上编译测试、离屏验收，
再备份 B 槽并经受保护的 IAP 流程试运行，之后实收测量帧并复核功率级
状态；任何 STM32 复位都会清除当前 `ANALOG SAFE` 锁存。

## 2026-09-29：只读电机测量链路上板验收

重传最终 HMI 源码至独立目录 `/home/cat/lubancat_hmi_measurement`，在鲁班猫
ARM 上完成 Release 构建；进入其构建目录运行 `ctest --output-on-failure`，
`status_v1_test` 和 `measurement_v1_test` 均通过。离屏预览为 1024×600。
保留旧 unit 与旧二进制，只增加
`/etc/systemd/system/lubancat-hmi.service.d/measurement.conf` 覆盖启动路径；
重启 HMI 服务后进程来自新目录，服务 active、`NRestarts=0`，CAN 接口未重配。

STM32 更新前再次确认 `CURRENT=A TARGET=B CONFIRMED=A PENDING=-`，
`ANALOG SAFE LATCHED=1 SD=0 MOE=0 FOC=0`。使用 ST-LINK HOTPLUG 无复位备份
原 B 槽和启动元数据至 `safety_backups/2026-09-29-motor-measurement/`；
原 B 槽 SHA-256 `71786806D882EC960004407B665867CE2D4E1A1503C614F06A5225B451F37F9F`，
与 9 月 28 日备份一致。升级脚本增加镜像复位向量与 A/B 目标槽一致性、
当前槽已确认、无待试镜像和安全锁存的通用保护；以 `-StageOnly` 将
216688 B、CRC32 `165F9984` 的 B 镜像写入非活动槽，不发送 `FW END`。
HOTPLUG 回读 216688 B 与构建镜像逐字节相同，SHA-256 均为
`BE1C9C726BB4981BA52B01DC1898A0B39421D8D3704512B6493892C4D21251BE`。

暂存期间 `ANALOG SAFE STATUS` 被 IAP 会话以 `FW_UPDATE_ACTIVE` 拒绝，因此
该次提交未执行。随后 HOTPLUG 无复位读数为 `VTOR=0x08008000`、
`GPIOC ODR=0`、`TIM1 BDTR=0x02002055`（MOE=0），并复核 IAP 大小、CRC、
目标及确认槽，才单次发送 `FW END`。设备试运行并自动确认 B 槽，最终
`CURRENT=B TARGET=A ACTIVE=0 CONFIRMED=B PENDING=- ATTEMPTS=0`。
复位清除了模拟安全锁存，立即重发 `ANALOG SAFE`；最终确认
`LATCHED=1 SD=0 MOE=0 FOC=0`、`MODE=IDLE FLT=0`。用户先前确认电机功率
或机械负载仍已物理隔离；本次没有发送电机运行命令。

鲁班猫 10 秒只读采集各收到 `0x180`、`0x181`、`0x182` 100 帧，首尾序号
`0x0484→0x04E7`，三类帧逐组序号一致，零缺帧。`can0` 为 500 kbit/s
ERROR-ACTIVE，RX 错误、丢包、bus-off、TX 均为 0。新 HMI 实况离屏图
`measurement-live-2026-09-29.png` 显示状态在线、相对角约 -0.04°、
转速 0.0 rpm、母线估算约 11.8 V；安全态 q 轴电流显示“—”，扭矩与曲线
仍空白。该截图证明业务解码和离屏渲染，不替代用户对本次 MIPI 实屏的确认。
HMI/CAN 服务均 active、enabled，HMI `NRestarts=0`；尚未做整机重启验收、
实体断线/恢复试验、扭矩标定或任何电机控制验收。`ANALOG SAFE` 仅在本次
STM32 运行周期有效，下次复位前仍须维持物理隔离并重新核对。

## 2026-09-29：只读实时角度/转速趋势

为推进上位机交互但不越过电机安全门槛，新增 30 秒内存环形趋势缓存与
Qt 绘图。仅当状态、角度、转速帧都新鲜、有效且三者序号相同时接受样本；
重复/倒退序号、单调时间倒退被拒绝，序号回绕可接受。状态或测量超过
500 ms 未更新即清空趋势，恢复后从新样本开始。总览和“曲线”页展示真实
相对角度/机械转速双轨趋势，明确不绘制未标定扭矩，亦不宣称数据可追溯。

Windows 与鲁班猫 ARM 的状态、测量、趋势缓存 3 个单元测试全部通过。
ARM 版在独立 `build_trend` 目录编译，离屏曲线预览为
`trend-preview-2026-09-29.png`。保留原 `build` 二进制，将 HMI systemd
drop-in 指向 `build_trend` 后重启 HMI；新进程 active、`NRestarts=0`，
`can0` 保持 500 kbit/s ERROR-ACTIVE，RX/TX 错误、丢包、bus-off、TX 均为 0。
未复位 STM32、未发送电机控制命令，也未做本次 MIPI 实屏人工确认或
整机重启自启验收。

## 2026-09-29：只读链路现场验收

用户确认新版总览可在 MIPI 实屏显示，触摸“曲线”可切换并看到实时双轨趋势。
STM32 仍为已确认 B 槽、`MODE=IDLE FLT=0`、
`ANALOG SAFE LATCHED=1 SD=0 MOE=0 FOC=0`；HMI/CAN 服务 active，
HMI `NRestarts=0`，DRM `video_port1` active 且挂载 1024×600 图层。
Windows/ARM 端 3 个单元测试均通过。

60 秒 `candump` 三类帧各 600 帧、三者 600 组序号配对，但序号首尾
14559→15159，显示每类各有一次共同跳号。随后发现鲁班猫 `can0` 的
bus-off 累计值由先前的 0 变为 2；当前接口已恢复 ERROR-ACTIVE，
RX/TX 错误与丢包仍为 0。30 秒带错误帧监视复测三类帧各 301 帧，
各自无跳号，错误帧 0，bus-off 累计值维持 2。一次共同跳号与两个
bus-off 事件的因果关系未证实；不能把这一轮签为“总线长期稳定”。
出于保存故障证据和避免 ACK 中断，本轮未做整机重启，也未试转电机。
完整通过/未通过清单见 `ACCEPTANCE_2026-09-29.md`。
