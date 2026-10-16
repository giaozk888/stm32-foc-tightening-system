# CAN FD 告警排查与隔离复现（2026-10-07）

## 结论先说

后续经用户现场授权，已实际复现：在现有 B 槽 FD 固件的背景遥测/日志阶段，
鲁班猫控制器报告接收 CRC 错误，原始错误码为 `0x12010200`。不是仅有界面告警，
也不能把 Linux 显示的零错误计数解释为总线正常。具体数据见第 6 节。

这说明故障已定位到 CAN 控制器/帧校验层，但尚未唯一确定是 RK3568 的 FD
标准兼容性/控制器缺陷，还是物理层/时序问题；也不能把此次首个错误等同于之前全部告警的原因。
原 A 槽、经典 CAN、HMI、热点和云隧道均已恢复并验证。没有重新刷写应用或 bootloader，
没有直接写 Flash 元数据，没有强制确认，没有启用功率级或发送运动指令。

以下第 1–5 节保留首次只读检查时的证据和未知项，第 6 节补充后来获准的实机复现。

## 1. 首次只读检查：经典 CAN 链路实测正常

实际设备为 LubanCat-2H / RK3568，内核 `4.19.232 #25`，构建日期 2026-04-18。
can0 绑定 `rockchip_canfd`，当前 compatible 为 `rockchip,rk3568-can-2.0`。
经典 CAN 配置为 500 kbit/s、MTU 16、时钟 200 MHz、采样点 87.5%、restart-ms 100。

被动监听 20.058 秒：

| 观察项 | 结果 |
| --- | --- |
| 本次发送 CAN 帧 | 0 |
| 接收 ID 0x180 | 200 帧 |
| 接收 ID 0x181 | 199 帧 |
| 接收 ID 0x182 | 199 帧 |
| SocketCAN 错误帧 | 0 |
| 接口状态 | 前后均 ERROR-ACTIVE |
| TEC / REC | 前后均 0 / 0 |
| RX / TX errors、dropped、overrun | 前后均为 0 |
| error_warning / error_passive / bus_off | 前后均为 0 |
| 接口累计 RX packets | 42121 → 42743 |

598 是本次过滤器接收到的三个状态 ID 的合计；接口总 RX 增加 622 包还包括其他 ID，
不能将两者差额解释为丢包。三个 ID 计数相差一帧也不能据此断言丢帧，采集起止边界不同。
CAN0、HMI、云隧道服务均 active。本次内核和上一轮 FD 开机日志没有保留足以判断
CRC/位填充/ACK 等具体类型的告警记录。

## 2. 官方手册明确提示 FD 位填充差异

野火英文手册 CAN FD 节明确说明：RK3568 的 FD 位填充实现与标准协议存在差异，
不推荐使用 CAN FD。这是硬件/协议层面的风险，不是仅增加一个设备树开关就能修复。

“位填充”可以理解为控制器在线路上自动插入特定的辅助位；若两端处理规则不一致，
就可能在部分帧上出现互通问题。它与应用负载末尾的 CRC32 不是同一层校验。
不过，官方风险说明不能替代此次告警瞬间的实测证据，尚不能断言这 3 次告警就是位填充差异造成。

来源：[野火官方 CAN 手册，7.3 CAN FD](https://doc.embedfire.com/linux/rk356x/quick_start/en/latest/quick_start/can/can.html#can-fd)。

## 3. 核对到公开的同版本厂家驱动，而非仅拿新主线推断

野火 `stable-4.19-rk356x` 分支的 Makefile 版本为 4.19.232。
本次核查固定仓库提交：`b9dde710722b3caa8bd00bdb3d5ca393bf2d953e`。
驱动文件 blob SHA：`2e438c115979893d1f68fba415f5b18ed06bea05`。

注意：版本号相同不等于已经逐字节证明板上内核由这个提交编译。板上 headers 不含
完整驱动 C 源码，也未取得运行内核对应的确切构建提交；以下是同版本厂家公开源码的依据。

源码中的相关处理：

- `rockchip,canfd-1.0` 选择 FD 路径；当前 classic compatible 选择经典 CAN 路径。
  所以更换 overlay 能让配置命令接受 FD，但不能由此认定修复标准兼容性。
- 第 775–777 行按 `ERR_WARN_INT` 直接增加 `error_warning` 并设置软件状态为 WARNING，
  不要求当时读到的 TEC/REC 非零。计数不是损坏数据包数量，也不能等同三次独立故障。
- 对整个文件的核查只找到启动时设置 ERROR-ACTIVE，没有在正常收发后按硬件状态恢复
  WARNING 的完整处理。这意味着软件告警状态可能残留，不能仅凭后续状态确定异常仍持续。
- 错误函数未完整分类协议错误，也未累加 `can_stats.bus_error`。因此 `bus_error=0`
  不能单独排除真实总线错误；普通 RX/TX errors 为零同样不足以说明没有控制器告警。
- 读取 TEC/REC 使用硬件寄存器直读，没有新主线驱动的错误计数修正逻辑。

来源：[野火 4.19.232 驱动固定提交](https://github.com/LubanCat/kernel/blob/b9dde710722b3caa8bd00bdb3d5ca393bf2d953e/drivers/net/can/rockchip/rockchip_canfd.c#L751)。

主线驱动对 RK3568 v2/v3 标记 `CANFD_BROKEN`，并记录告警时两错误计数可能读成零、
需要缓存修正。这是独立交叉依据，不是当前板上驱动或升级后必定能用 FD 的证明。
来源：[Linux Rockchip 驱动](https://github.com/torvalds/linux/blob/master/drivers/net/can/rockchip/rockchip_canfd-core.c)。

## 4. 没找到明显的软件波特率 / BRS 配置冲突

核对实际 FD 构建的宏和发送代码：FD 开启、BRS 关闭，遥测/日志仍使用 8 字节应用格式；
独立只读回显使用 64 字节。STM32 仲裁段计算为
`170 MHz / [17 × (1 + 16 + 3)] = 500 kbit/s`，采样点 85%。
鲁班猫上次 FD 记录仲裁段也是 500 kbit/s、采样点 87%。采样点不必完全相同，
这个差异本身不是已确定的故障。没有测实际线路波形，因此未排除时钟误差和物理层裕量。

STM32 源码保留的 2 Mbit/s 数据段参数仅供 BRS 构建使用；本项目 HAL 仅在
`FDCAN_FRAME_FD_BRS` 时写入该数据时序。本次 BRS 关闭、帧内不切速，不能把这组
备用参数与鲁班猫 dbitrate=500k 的差异直接判定为本次错误原因。

源码依据：`firmware_common/can_wire_profile.h`、`firmware_common/can_status_tx.c`、
`foc2_app_b/Drivers/STM32G4xx_HAL_Driver/Src/stm32g4xx_hal_fdcan.c`，以及 FD 构建的 build.ninja。

## 5. 首次只读检查时的未知项（后续复现见第 6 节）

上次短测 20/20 64 字节回显通过，随后持续状态数据期间发现告警；RPC/Transfer
尚未开始就被健康检查拦住。因此没有证据将它们作为触发原因。

目前至少要区分：标准兼容性导致的真实总线异常、物理层/时序问题、告警状态残留
和硬件错误计数读回异常。这几类情况可能叠加，不应选一个猜测当成最终根因。

若进一步复现，需要另一次经过现场安全确认的隔离 FD 测试：先从控制器上线前开始
采集错误帧，记录告警时硬件状态/错误码以及 STM32 对应错误信息，并分别验证不同 DLC、
负载和背景遥测。旧驱动未提供完整错误类型，仅抓用户态错误帧也可能仍不够定位。
必要时需要有依据的诊断增强或标准 FD 对端交叉验证，不能通过屏蔽告警或改低验收门槛“通过”。

首次只读检查保留经典 CAN 正常工作，没有实施上述复现或驱动修改；
之后用户授权了临时 FD 启动、现有 B 槽试运行和复位，结果如下。

先前验收证据见 [CAN FD 通信验收记录](CAN_FD_COMMUNICATION_20261007.md)。

## 6. 后续隔离复现：捕获了帧级接收 CRC 错误

### 6.1 做了什么，没做什么

用户确认功率级/电机已电气隔离、供电稳定、总线只有 STM32 和鲁班猫、串口可恢复，
允许临时切换 FD 设备树并重启鲁班猫、让现有 B 槽正常试运行及必要复位，测试后恢复经典 CAN。

本轮保持 ISO FD、500 kbit/s、不启用 BRS。HMI 和原 CAN 启动服务被本次专用保护暂时拦住，
1200 秒超时保护可恢复原启动文件并重启，但保持 CAN/HMI 关闭，直到原 MCU A 槽确认后才释放。
这避免回退时经典 CAN 对端与仍在发送 FD 的 MCU 混接。

STM32 A/B 镜像先通过完整 CRC/SHA 校验；仅写入保留 SRAM 的 START_TRIAL 请求并复位，
由原 bootloader 验证 B，再由应用正常完成健康确认。B 确认时 `GEN=324`，
`LATCHED=1 SD=0 MOE=0 FOC=0`。隔离计算 bench 当时为 `ADC=47317 FOC=47317`，
`SD=0 MOE=0 CCER=0`；这不是带电运行电机。

采集程序只接收 CAN 数据，不发送应用 CAN 帧。只读映射控制器 MMIO 页，周期读取白名单寄存器；
可能读清的 ERROR_CODE 仅在首个错误时读取一次，然后关闭接口。
没有发送 64 字节回显请求，没有启动 Router RPC/Transfer 请求，更没有固件写入/运动命令。

### 6.2 首个有效故障证据

| 项目 | 实测值 |
| --- | --- |
| 界面上线至首个故障 | 23.730 秒 |
| 第一个 FD 帧至首个故障 | 11.871 秒 |
| 捕获 FD 帧 | 298 帧，全部为 8 字节背景遥测/日志 |
| 鲁班猫应用 TX | 0 帧 |
| 首个触发条件 | 硬件接收错误计数非零 |
| MMIO RXERRORCNT / TXERRORCNT | 9 / 0 |
| MMIO STATE | `0x8`，此瞬间未置 warning/bus-off 位 |
| ERROR_CODE（仅读一次） | `0x12010200` |
| 按官方寄存器定义解码 | TYPE=CRC，DIRECTION=RX，RX_CRC 段标志置位 |
| 同期 `ip` 软件状态 | ERROR-ACTIVE，TEC/REC=0/0，bus_error/error_warning 均 0 |
| SocketCAN 错误帧 | 本次未捕获到 |
| 后续动作 | 首错即停止 CAN，恢复原 A / 经典 CAN |

FD 帧由多个遥测/日志 ID 组成；程序没有逐帧记录应用负载，也未将错误码与某一失败 ID 关联，
因此不能声称已找到了特定坏数据包。本轮也没有完成 64 字节帧的当前验收。

读错误码后再次观察到 RXERRORCNT=0、STATE=0。它们是不同时间点，可能读清行为和总线继续变化叠加，
不能据此断言读取 ERROR_CODE 本身清空了全部错误计数，也不能说故障消失了。
它恰好说明只用后来一次 `ip` 查询的零计数，可能漏掉先前的瞬时硬件错误。

STM32 串口健康观察开始时，鲁班猫已经因首错关闭 CAN；这时 STM32 显示 TEC=132、REC=0、LEC=7。
这个采集点晚于停接口，不能拿它反推出首错前 STM32 的状态，更不能据此把初始 CRC 错误解释为 ACK 错误。
观察进程被提前停止，逐行 `mcu.jsonl` 已保存，未完成的 summary 文件不作为完整验收证据。

### 6.3 错误码不是应用包里的 CRC32

`0x12010200` 来自 CAN 控制器硬件错误寄存器，表示控制器报告帧级接收 CRC 异常。
Router 编码器包的 CRC32、文件下载的完整性校验属于上层；加这些校验不能修复控制器间的 FD 协议兼容性。

Linux 官方寄存器头文件的 ERROR_CODE 定义对应上述 TYPE、方向、接收 CRC 段标志。
本次固定核对提交 `b7d51d9b14eea0eb4f4cf3a8293b2f53539ca96f`，头文件 blob
`95bea9bfd8a2f9b3652177b2dae77fd7875779fa`。
同一源码也列出 RK3568 间歇 CRC/位填充等硬件勘误，且 v2/v3 均标记 `CANFD_BROKEN`；
CRC 勘误 3 在 v2 的适配中列出，不能仅凭此次错误码就断言本板恰好命中这一特定勘误。

来源：[Linux 官方寄存器定义与勘误](https://github.com/torvalds/linux/blob/b7d51d9b14eea0eb4f4cf3a8293b2f53539ca96f/drivers/net/can/rockchip/rockchip_canfd.h)，
[同提交芯片适配与 FD 限制](https://github.com/torvalds/linux/blob/b7d51d9b14eea0eb4f4cf3a8293b2f53539ca96f/drivers/net/can/rockchip/rockchip_canfd-core.c)。

目前最严谨的结论是：**本组合在背景 FD 通信阶段已出现真实的控制器 CRC 错误报告，不具备稳定 FD 验收条件。**
厂家风险说明与此次现象相容，但仍需线路波形或标准 FD 对端交叉验证，才能区分控制器兼容性问题与物理层/时序问题。
不能用忽略告警、切非 ISO 模式、屏蔽 CRC 或只提高重试次数来冒充解决。

### 6.4 初次采集失败另记，不冒充 CAN FD 故障

第一轮工具发生两处流程错误，保留了原始失败证据：

1. SRAM 切槽请求把当前槽也填成 B，形成 B→B。bootloader 按保护规则拒绝，STM32 仍在 A。
   修正为请求者 A、目标 B 后正常试运行；没有修改 bootloader 或降低验证门槛。
2. Socket 绑定在 DOWN 接口上，配置接口产生一个残留 ENETDOWN 通知。第一次采集错误退出。
   修正为仅在即时复查证实 FD 配置、硬件及软件计数都健康时，接受一次残留通知；实际 DOWN、
   重复通知或任何错误仍中止。第二轮在同一临时启动中保留到新文件 `monitor2*`，没有覆盖第一轮。

相关诊断/恢复离线测试共 **41 项通过**，包括 A→B 请求字段/CRC、零计数不抵消告警、
一次性错误码读取、实际 CRC 错误码解码，以及残留通知不能掩盖真正接口故障等。

### 6.5 已恢复并核验

- STM32 经原 bootloader 正常试运行回 A 并确认，`GEN=327 PENDING=- ATTEMPTS=0`。
- 功率关闭锁定仍生效：`LATCHED=1 SD=0 MOE=0 FOC=0`；bench 已停止。
- 原 A、bootloader、参数/KVS 等保护区逐字节一致；B 槽也未变化。
  正常槽切换由 bootloader 更新其管理的元数据，这不同于直接写元数据或重新刷写应用。
- 鲁班猫原启动文件 SHA256 恢复为
  `a41101b288afbe2527ca975c83eb2913ba866d13cc28c4120181239388f69c93`，原符号链接保持。
- compatible 恢复为 `rockchip,rk3568-can-2.0`，经典 CAN 500k、MTU16、ERROR-ACTIVE、TEC/REC=0。
- 0x180/0x181/0x182 六帧被动验收通过，未发送测试 CAN 帧。
- 原 CAN/HMI、NetworkManager、云隧道服务均 active；wlan0 热点、p2p0 校园网连接恢复。
- 云端隧道 `/health` 返回 HTTP 200，`control_enabled=false`。
- 本次专用启动保护/服务拦截已解除，无持久 FD 部署。

公开证据在 `safety_backups/20261007-canfd-diagnosis/`：
`luban/monitor2-summary.json`、`luban/monitor2.jsonl`、`luban/recovery.json`、
`start-b-retry/trial.json`、`mcu-observe/mcu.jsonl`。
完整 Flash/恢复底稿只保留在 ACL 受限的 `private-stm32` 子目录，不分享、不提交。
