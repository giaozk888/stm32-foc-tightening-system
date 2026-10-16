# CAN FD 改造与实机预检查（2026-10-06）

## 结论

**21:40 串口恢复通道就绪后的新结果：临时切换系统自带 FD 设备树并重启后，
500k/500k 和 500k/2M 两组 FD 配置均成功，MTU 变为 72。**
接口始终 DOWN，没有真实 FD 收发；随后已恢复原启动配置、重启回经典 CAN，
重新接收连续状态帧。下文“拒绝 fd on”记录是此前经典设备树下的历史结果，
不能推广为这块板子在所有设备树模式下都不能配置 FD。
本次验证的是软件配置能力，不是标准 ISO FD 互通能力，详见文末增补记录。

已增加可选择的 CAN FD 隔离测试版本，**没有把现有运行链路切换成 FD**。
实机预检查中，鲁班猫当前 Linux 4.19.232、`rockchip,rk3568-can-2.0` 驱动配置
拒绝 `fd on`，返回 `RTNETLINK answers: Operation not supported`。
使用完整参数设置 2 Mbit/s 数据段，以及完整参数设置 500 kbit/s 数据段
均被拒绝，因此不是仅凭一次高速时序设置失败下结论。
早先“仅设置 FD 开关”的检查缺少数据段参数，不能独立证明驱动不支持 FD；
已修正工具并用完整的 500k/500k 参数补测，旧记录保留但不作该结论的依据。

检查过程中只临时将 can0 置为 DOWN，从未让 FD 接口上线，从未发送测试帧。
finally 已恢复原始时序、MTU 16、500 kbit/s、restart-ms 100 和 UP 状态。
恢复后的 TEC/REC 为 0，历史 bus-off 计数仍为 8，没有新增；随后被动捕获
0x180、0x181、0x182 两组连续经典 CAN 状态帧，证明原链路继续接收。
详见 [完整参数补测证据](safety_backups/20261006-canfd/interface-valid-retest.json)。

**没有刷写或复位 STM32，没有改 bootloader、A/B 元数据、ESP32、参数或云端。**
不因驱动名字包含 canfd 就认定 FD 可用，也不在未经验证的情况下更改设备树、
安装内核、尝试非 ISO 模式或更换整个系统。

## 代码改动

- A/B 新增 `CanFdReadOnly` 和 `CanFdBrsReadOnly`，默认旧配置仍使用经典 CAN。
- FD 配置继承 `RouterTransferIsolated`，功率级硬锁定；CMake 拒绝未启用隔离配置的 FD 构建。
- 第一阶段：ISO CAN FD、仲裁段 500 kbit/s，BRS 关闭，帧内不切换速率。
- 第二阶段：仲裁段 500 kbit/s、数据段 2 Mbit/s，BRS 开启，并配置发送延迟补偿。
- PCLK1 必须是 170 MHz，否则 FD 初始化失败关闭，不使用错误的硬编码时序。
- 修正 HAL DLC 与长度的区别：DLC 15 是 64 字节，不是 15 字节。
- 原遥测、日志、RPC 和控制拒绝帧先保留八字节应用格式，只改变 FD 线格式。
  此次**没有声称 RPC/Transfer 已通过 64 字节分片加速**。
- 新增独立 64 字节只读回显：请求 ID 0x702、响应 ID 0x703，包含非零事务号及 CRC32。
  接收只允许标准数据 FD 帧、匹配的 BRS、固定长度、正确魔数和 CRC。
  仅一条待发送回复、500 ms 有效期、固定内存，无 Flash/电机调用。
- Qt HMI 新增 `--can-fd`、`--can-fd-brs`，启用 SocketCAN FD，使用 64 字节接收空间，
  按 CAN_MTU/CANFD_MTU 区分线格式，避免截断；旧参数不变。
- 主机探针不配置接口、不刷固件，必须明确 `--permit-read-only-test` 才打开 SocketCAN。

## 离线编译和使用

```powershell
cd 'D:\new project\foc2_app_a'
cmake --preset CanFdReadOnly
cmake --build --preset CanFdReadOnly
# 仲裁 500k / 数据 2M，必须先证明基础 FD 两端互通
cmake --preset CanFdBrsReadOnly
cmake --build --preset CanFdBrsReadOnly
```

B 槽使用对应 `foc2_app_b` 目录和相同 preset。
这些命令只生成镜像，不是刷写命令。后续只能将匹配地址的镜像写入当时非活动槽，
保留已确认回退镜像，再经试运行和健康确认，不能直接覆盖活动槽。

未来具备可靠 FD 对端并完成现场确认后，可以执行：

```sh
# 先由受控流程配置并验证 FD 接口，再启动测试；此工具不会替你改接口。
python3 can_fd_probe.py --interface can0 --permit-read-only-test
# 第二阶段仅在两端均已配置 500k/2M BRS 后执行
python3 can_fd_probe.py --interface can0 --brs --permit-read-only-test
```

HMI 参数与固件模式必须匹配；不能只给经典 CAN 的 can0 添加一个界面启动参数。
任何 CAN-only 节点也不能被假定能在同一总线上容忍 FD 帧。

## 本次验证范围

已通过：FD DLC/CRC/格式 CTest 1 项、Python 工具和恢复策略测试 6 项、
Qt HMI 回归 12 项、原 CAN RPC/官方 Transfer 回归 3 项；两种非法构建配置被拒绝。
A/B 的不切速 FD 镜像、A 的 500k/2M BRS 镜像及 A 的原经典 CAN 隔离镜像编译通过。
上述主机测试不等于真实 FD 收发、吞吐率或 BRS 电气波形通过。

经用户明确同意，仅把界面源码和公共协议头上传至鲁班猫专用
`/tmp/codex-canfd-hmi-syntax-20261006`，执行 `g++ -fsyntax-only`。
Linux/aarch64、Qt5Widgets/Qt5Sql 5.12.8 语法编译退出码为 0，输出
`LINUX_QT5_SYNTAX_PASS`；Qt5 系统头文件有 deprecated-copy 警告，
不声称无警告。没有链接、替换或启动界面，上传包不含密码、私钥或 API 配置。

编译后再次只读核对 can0：UP、MTU 16、500 kbit/s、ERROR-ACTIVE、
TEC/REC 均为 0，RX/TX errors 均为 0，历史 bus-off 仍为 8。
源码编译通过只证明接口在当前 Linux/Qt5 下可编译，不能替代真实 FD 收发。
当前镜像大小与 SHA256 见 [本次编译证据](safety_backups/20261006-canfd/build-verification.json)。

## 后续条件

### 2026-10-06 再次定位结果

板端只读核查确认：

- 当前内核：4.19.232，#25，构建日期 2026-04-18。
- can0 硬件节点：`can@fe580000`，绑定 `rockchip_canfd`。
- 当前 compatible：`rockchip,rk3568-can-2.0`；时钟 200 MHz。
- 当前启用 `rk3568-lubancat-can1-m0-overlay.dtbo`。
- CAN/CANFD 两个驱动配置均已编进内核，不是简单漏开 `CONFIG_CANFD_ROCKCHIP`。
- 自带的 FD overlay 选择 `rockchip,canfd-1.0`，时钟 100 MHz；文件存在
  不代表它与 STM32 的标准 FD 通信已经可靠，也不代表当前系统启用了它。
- 已安装 headers 不含完整驱动 `.c`，未把官方其他版本源码冒充当前编译版本。

官方 [LubanCat 驱动参考源码（6.1 分支）](https://github.com/LubanCat/kernel/blob/lbc-develop-6.1/drivers/net/can/rockchip/rockchip_canfd.c)
根据 compatible 选择不同模式，经典 CAN 路径不声明 FD 能力。
这是当前运行结果的参考解释，不作为运行中的 4.19 驱动逐行源码证明。

更关键的是，[主线 Linux 驱动](https://github.com/torvalds/linux/blob/master/drivers/net/can/rockchip/rockchip_canfd-core.c)
给 RK3568 v2/v3 标记 `RKCANFD_QUIRK_CANFD_BROKEN`，对应路径不开放 FD 能力；
[野火官方手册](https://doc.embedfire.com/linux/rk356x/quick_start/en/latest/quick_start/can/can.html)
也提示 RK3568 FD 位填充与标准不同、不推荐使用。
因此不能把“换成旧 FD overlay 后命令可能成功”当作“硬件标准兼容性已修复”，
也不能承诺升级到新内核就能解决。

此次已修复预检查工具的参数缺失，Python 回归 6/6 通过；实机完整 500k/2M
和 500k/500k 均返回不支持，已自动恢复原时序、UP、MTU 16、restart-ms 100。
之后被动捕获 0x180/0x181/0x182 两组连续状态帧，TEC/REC 和 RX/TX errors 为 0，
历史 bus-off 仍为 8。未发帧，未改启动配置，未重启鲁班猫，未刷写 STM32。

用户确认目前没有 USB-CAN FD 适配器或第二块 FD 控制板。
在没有标准 FD 对端的情况下，本次只完成根因排查、诊断修正和经典链路恢复确认，
**没有完成原生 FD 修复或真实 FD 验收**。外接标准控制器是后续路径，
但必须先确认具体型号、当前 Linux 驱动支持和现场接线，再另行实施。

继续真实 FD 收发，需要有已验证支持标准 ISO CAN FD 的对端，例如接到鲁班猫的
Linux/SocketCAN FD 控制器，或经确认可用的原生驱动方案。单纯换收发器不等于换控制器。
不能把本次内核拒绝推断成所有 RK3568 镜像永远不支持 FD，也不能把改内核当作无风险步骤。

源代码改动前备份在 `refactor_backups/20261006_canfd_before`。
本次临时 SSH 公钥限制来源 192.168.137.1，按鲁班猫本地时间 2026-10-06 22:36:36 到期；
私钥只在本机受限目录保存，不放入源码或上传包。

## 21:40 串口恢复下的临时 FD 设备树实测

用户新确认已通过串口登录，要求尝试。板端 `who` 确认 root 登录在 `ttyFIQ0`。
在提供串口恢复命令后，本次仅对鲁班猫执行一次临时切换和一次恢复重启。
没有刷写/复位 STM32，没有启用功率级，没有发送 CAN 或运动测试指令。

### 准备与保护

- 核实 `uEnv.txt` 是指向 `uEnvLubanCat2H.txt` 的符号链接，保留符号链接，
  只编辑已验证的真实文件。初次检查因保护条件停止，没有在错误路径写入。
- 原文件字节级备份后，仅将 CAN1-M0 的 classic overlay 行改为系统自带 FD overlay。
  CAN2、其他外设 overlay、内核镜像和内核参数保持不变。
- 给 CAN0 配置服务和只读 HMI 增加本次专用条件门控，确保 FD 试验开机时 CAN0 DOWN。
- 设置下一次开机后 300 秒自动恢复与重启。使用单调时钟，不依赖鲁班猫墙钟；
  自动恢复服务的配置与启动状态经过核查，本次在超时前主动恢复，
  **没有另行制造 SSH 失联来实测超时回退**。完全无法启动仍需串口人工处理。
- 临时工具的主机回归 6/6 通过，覆盖精确替换、不覆盖外部改动、接口 UP 时拒绝测试等。

板端保留备份与恢复工具：`/root/codex-canfd-overlay-test-20261006/`。
手动恢复命令（会重启鲁班猫）：

```sh
python3 /root/codex-canfd-overlay-test-20261006/controller.py restore --reboot
```

### 实际结果

| 项目 | 临时 FD 试验 | 恢复后的当前运行状态 |
| --- | --- | --- |
| compatible | `rockchip,canfd-1.0` | `rockchip,rk3568-can-2.0` |
| 控制器时钟 | 100 MHz | 200 MHz |
| FD 500k/500k 完整配置 | 返回 0，MTU 72 | 不保留 FD 模式 |
| FD 500k/2M 完整配置 | 返回 0，MTU 72 | 经典 CAN 500k |
| 接口状态 | 始终 DOWN/STOPPED | UP/ERROR-ACTIVE |
| 试验发帧 | 0 | 无测试发送 |
| 实际接收 | 未做 FD 接收 | 0x180、0x181、0x182 两组连续状态帧 |

恢复后 boot 文件 SHA256 与原备份相同：
`a41101b288afbe2527ca975c83eb2913ba866d13cc28c4120181239388f69c93`。
CAN0 TEC/REC 为 0，RX/TX errors 为 0，恢复这次开机的 bus-off 计数为 0；
重启会重置这些计数，不能拿它与先前开机的历史计数 8 直接比较。
热点与校园 Wi-Fi 均 connected；CAN0/HMI/NetworkManager/云隧道服务 active。
本次临时门控和回退服务文件已移除，专用工具与备份保留。

证据：[FD 配置记录](safety_backups/20261006-canfd/overlay-trial/probe.json)、
[原配置备份](safety_backups/20261006-canfd/overlay-trial/uEnv.original)、
[恢复操作记录](safety_backups/20261006-canfd/overlay-trial/restore.json)、
[恢复后验收](safety_backups/20261006-canfd/overlay-trial/recovery.json)。

### 能说明什么，不能说明什么

本板当前镜像确实能通过自带 FD overlay 开放 FD 配置入口；先前拒绝有设备树模式因素，
不能再简单描述为“该板完全无法开启 FD”。试验也没有触发内核中按 CPU 版本强制经典模式的分支。

`ip link set` 成功只证明驱动接受时序和模式，DOWN 状态尚未运行 FD 控制器，
因此不证明 FD 帧位填充、CRC、64 字节收发、BRS 切速、延迟补偿或稳定性通过。
没有据此消除前述 RK3568 标准兼容性风险，也没有宣称 CAN FD 升级、Router 或 Transfer 已通过。
当前保留经典 CAN，下一阶段应在重新确认隔离及总线节点后，分步验收标准 FD 对端互通，
先不切速 64 字节，只读回显通过后才试 2M BRS；任何经典 CAN-only 节点不能默认留在测试总线上。

## 22:00—22:12 双节点 64 字节 CAN FD 实机回显

**最新结论：本次 STM32G474 ↔ 鲁班猫在 500 kbit/s、不切速（BRS 关闭）的
64 字节 CAN FD 回显已通过。测试结束后已恢复原 A 固件和经典 CAN。
这不是 2 Mbit/s BRS、CAN FD 升级或长期稳定性验收。**

用户本次重新确认功率级/电机电气隔离、MCU 供电稳定，允许写非活动槽和复位、
临时切换设备树并重启，且总线只有 STM32 和鲁班猫。

### 固件与保护

- 测试前 `CURRENT=A CONFIRMED=A PENDING=- GEN=309`。
  原 A 为 195476 字节，CRC32 `547D67EE`；整片 Flash 私有备份已保存。
- 通过现有串口 A/B IAP 写入非活动 B，测试镜像为 `CanFdEchoOnly`，194644 字节，
  CRC32 `A2798E69`。正常 5 秒健康门控后确认 B，`GEN=312`，未强制确认。
- 隔离测试固件只允许 CAN 发送 ID `0x703`，屏蔽背景状态、日志和 RPC 发送。
  SD/MOE/FOC 保持 0，不开放电机控制。原 A、bootloader、KVS 和参数不写入。
- 鲁班猫使用独立试验目录及 900 秒单调时钟回退保护；只改 CAN1-M0 为自带 FD overlay。
  每轮探针无论成功或异常都将 can0 DOWN，未改 CAN2 或内核镜像。

### 测试与首次超时的原因

请求 ID `0x702`，回复 ID `0x703`；单帧 64 字节负载含 `CFD1`、随机非零事务号、
52 字节图案和 CRC32。接收必须是标准数据帧、长度 64、BRS/ESI 状态符合预期，
并与请求负载逐字节一致。未启用接收自身发送帧，也未启用控制器 loopback。

首次计划 20 帧仅发送第 1 帧就超时；后续一次单帧复验也超时。STM32 都实际接受并回复，
Linux RX 也增长，但探针的 `CAN_RAW_FILTER` 掩码误含 `CAN_ERR_FLAG`，使正常数据帧
没有交付给该 socket。临时只读全 ID 捕获后取得完整、正确的 `0x703` 帧，随后将掩码修正为
`CAN_EFF_FLAG | CAN_RTR_FLAG | CAN_SFF_MASK`（`0xC00007FF`），恢复精确过滤。
错误帧使用独立的 `CAN_RAW_ERR_FILTER`，不是往数据过滤掩码加入错误标志。
依据：[Linux SocketCAN 文档](https://docs.kernel.org/networking/can.html)、
[Linux 4.19 CAN 接收列表源码](https://github.com/torvalds/linux/blob/v4.19/net/can/af_can.c)。
严格回显验收条件没有放宽；两次超时原始记录保留。

| 阶段 | 实际发送 / 校验成功 | 结果 |
| --- | --- | --- |
| 原错误过滤，首次及复验 | 1/0、1/0 | 超时，立即停止 |
| 全 ID 只读诊断 | 1/1 | 完整 `0x703` 回显，无负载或帧标志差异 |
| 修正精确过滤，四种图案 | 4/4 | `00/FF/55/AA` 全通过 |
| 修正精确过滤，正式短测 | 20/20 | 64 字节负载逐字节一致，CRC 一致 |

正式短测用户态最大往返约 **85.73 ms**，包含 MCU 任务调度和主机软件延迟，
不是 CAN 线速时延或实时性保证。Linux TEC/REC、RX/TX errors、bus_error、bus_off
增量均为 0。STM32 累计收到 27 帧、入队回复 27 帧、发送完成 27 帧，
拒绝、丢包、FIFO 溢出、恢复、bus-off 均为 0；ECR=0，CFSR=0。
PSR 中 LEC/DLEC=7 表示 no change，未将它误记成错误码。

### 已完成恢复

用现有 bootloader 的 CRC 保护 `START_TRIAL` SRAM 请求返回原 A，APP 正常通过
5 秒健康门控，最终 `CURRENT=A CONFIRMED=A PENDING=- ATTEMPTS=0 GEN=315`。
未直接写 Flash 元数据、未强制确认、未再次刷写原 A。
整片读取比对确认原 A 全槽、bootloader、KVS、参数与测试前逐字节相同。
最终 `LATCHED=1 SD=0 MOE=0 FOC=0`，CFSR=0。

**非活动 B 当前保留本次 FD 回显测试镜像，不是原 B；原 B 可从测试前私有整片备份恢复，
本次没有擅自再刷一次恢复它。** 不要分享或提交包含私有配置的整片 Flash 备份。

鲁班猫原 boot 配置哈希与符号链接完全恢复，当前 `rockchip,rk3568-can-2.0`、
200 MHz、经典 CAN 500k、MTU 16、UP/ERROR-ACTIVE、restart-ms 100。
被动收到 `0x180/0x181/0x182` 两组连续状态帧；本次恢复开机 TEC/REC 与 RX/TX errors 为 0。
CAN0、HMI、NetworkManager、云隧道服务 active，热点和校园 Wi-Fi connected。
只移除本次专用门控/回退服务，工具与备份保留。

证据：
[正式 20 帧](safety_backups/20261006-canfd-wire/luban/wire-20.json)、
[首次失败](safety_backups/20261006-canfd-wire/luban/wire-20-filtered-failure.json)、
[STM32 计数](safety_backups/20261006-canfd-wire/stm32-fd-health.json)、
[原 A 恢复](safety_backups/20261006-canfd-wire/return-a/restore.json)、
[经典链路与服务恢复](safety_backups/20261006-canfd-wire/luban/recovery.json)。

本结果比前一阶段的“仅配置成功”更进一步，证明当前两块板、当前镜像和本次模式
确实完成了有限样本的真实 64 字节互通；不能推广为所有 RK3568 版本标准兼容、
所有负载/拓扑长期稳定，也没有消除已有驱动/官方手册提示的风险。
2M BRS、各种 DLC、长时间压力、Router/Transfer over FD、CAN FD 固件升级均未验收。

恢复后主机回归：Python 19/19，C++ CAN FD wire 测试 1/1 通过。
