# CAN FD 只读通信：实机回显通过，日常切换未通过

> 2026-10-07 最终状态：已恢复原 A 与经典 CAN 500k，旧 HMI、热点、云隧道正常。
> FD 64 字节回显 20/20 通过，但持续状态流出现 3 次 ERROR-WARNING。
> 业务健康门控拒绝继续；未发送业务 RPC，未启动历史 Transfer，未保留 FD 自启动。

## 这次选择

STM32G474 ↔ 鲁班猫 CAN0 使用 **CAN FD，500 kbit/s，BRS 关闭**。
保留经典 CAN 固件和启动配置作为回退，不将未验收的 2M BRS 设为默认。
这是隔离、控制锁定的通信配置，不是开放电机运行。

2026-10-06 的真实双节点 64 字节回显已通过 20/20；见
[上次验收](CAN_FD_EXPERIMENT_20261006.md)。上次结束时已恢复原 A 与经典 CAN。
本次已重新核对串口恢复、隔离、供电及临时 SSH 授权，实际完成两端切换及短测，
但可靠性门控未通过，最终完整回退。不能把回显成功当成日常 FD 通信成功。

## 通信和协议

| 链路/内容 | 配置与边界 |
| --- | --- |
| MCU 状态/测量、实时日志 | 原 ID 和原 8 字节负载不变，外层采用 FD 帧 |
| 只读 CAN RPC | 0x600 请求、0x601 回复；原 8 字节分片/CRC16 不变 |
| CAN 历史日志下载 | 官方 Transfer.Read 经原 CAN RPC 适配；本次未进入 FD 业务测试 |
| 64 字节回显 | 0x702/0x703；诊断测试，不是升级通道 |
| ESP32 ↔ STM32 / 鲁班猫 | 原 UART/TCP/Router 路径不变，不把 ESP32 原串口链路称为 CAN FD |

CAN FD 支持 64 字节不代表每个业务包都必须使用 64 字节。
本次先保持应用协议兼容，不改 RPC 分片、Router 或 Transfer 的资源与权限边界。
未新增 CAN FD 固件上传、参数写入或运动命令。网络 Transfer 与 CAN Transfer
是不同适配路径，不能拿另一条路径的验收代替本次 FD 上的下载验收。

## 本地构建

```powershell
# 仅编译 A/B，不打开串口、不刷写、不复位
.\tools\build_router_network.ps1 -CanFd
```

A/B 使用 `CanFdReadOnly`：显式 `CAN_FD_EXPERIMENT=ON`、
`CAN_FD_BIT_RATE_SWITCH=OFF`、`CAN_FD_ECHO_ONLY=OFF`；
状态、日志、只读 RPC 保留，功率级硬锁定条件保留。
不能使用 `CanFdEchoOnly` 来代替日常只读通信，它会屏蔽背景状态/日志/RPC 回复。
`-CanFd -Esp32` 会拒绝执行，避免误把 STM32 模式用在 ESP32 构建。

本次 A/B 编译均通过：A 为 196116 字节，B 为 195212 字节；
两槽 RAM 用量约 79.2%，在现有槽/链接器容量内。
构建成功不等于运行栈、并发、网络或模拟电流已验收。

## 鲁班猫配套文件（构建完成，未保留部署）

- `tools/can_fd_communication_setup.py`：默认只检查；`--apply` 只配置已经
  选择 FD 设备树且处于 DOWN 的 CAN0 为 500k/500k、FD、restart-ms 0。
  若已 UP 且模式/时序/错误状态不符，报错而不关闭或重配；配置失败则使接口 DOWN。
  不修改设备树或启动文件，不发送应用 CAN 帧；不自动改回经典模式。
- `lubancat_hmi/systemd/can-fd.conf`：CAN 服务覆盖模板。
- `lubancat_hmi/systemd/zzzzzzzzzz-canfd-communication-20261007.conf`：HMI 使用独立 Linux 构建目录，
  启动参数 `--can-fd`，不加 `--can-fd-brs`。保留现有 EGLFS/openvt 设置。

这些是部署模板，不要直接复制后重启：需要先核对当前板端服务覆盖项，
在独立目录完成 Linux/Qt5 构建，备份实际启动文件、旧二进制和非活动槽，
配置超时回退，再先使 FD 对端就绪、受控 IAP 切换 MCU，最后启用 HMI。
MCU 切换前不发送 FD 请求，避免旧经典 CAN 固件遇到 FD 帧。
成功与回退都要保持两端模式匹配，不能只让一端永久切换。

## 本次离线验证与待验收

CAN FD 设置/探针/回退/部署工具的 Python 回归 **30/30**，C++ wire 测试 **1/1** 通过。
HMI Windows 编译及主机测试 **12/12**，鲁班猫完整 Linux/Qt5 编译及测试 **13/13** 通过。
Windows 没有 SocketCAN，
不能代替本次新增设置脚本的 Linux 运行验收或真实 FD 业务通信验收。
新增设置测试覆盖：只读不修改、错误设备树拒绝、正确 live profile 不重配、
经典/错误 live profile 不打断、启动失败关闭接口、核验失败关闭接口。
主机测试不实际操作 CAN0。

重新确认现场后，需要验收 FD 状态帧、日志重组、Ping/读状态/读参数、
官方历史日志下载，检查错误计数、掉线表现、恢复与重启，再决定保留 FD 自启。
2M BRS、长时间压力和 FD 升级不在这次默认配置中。

## 现场授权后预检查

用户已重新确认电机电气隔离、供电稳定、总线只有两节点、串口可恢复，
并允许本次刷写、复位与 FD 启动配置切换。
串口只读检查得到 `CURRENT=A CONFIRMED=A PENDING=- ATTEMPTS=0 GEN=315`，
`LATCHED=1 SD=0 MOE=0 FOC=0`；BENCH 未运行。
整片 524288 字节 Flash 已备份到本次受限私有目录；不应分享或提交该备份。
原 A 大小及 CRC 与前次恢复相符。

本次公钥授权和主机指纹核对已完成。公钥限制电脑来源 192.168.137.1，
按鲁班猫本地时间 2026-10-07 15:00 到期。
私钥仅存在本机受限目录，不上传、不显示。

## 本次真实验收结果

1. 新 HMI 在独立 `/home/cat/lubancat_hmi_canfd/build-gcc10` 完整构建。
   GCC 9 不支持当前 Pigweed 的 constinit；并行安装 GCC 10，保留默认 GCC 9。
   GCC 10 的早期 std::span 存在兼容问题，使用官方 `PW_SPAN_ENABLE_ASSERTS=1`
   选择带边界断言的 pw::span，未修改上游头文件或删掉初始化检查。
2. 原 boot 文件及 CAN/HMI 服务配置备份，启用 1800 秒保护。超时会停止通信并
   恢复 boot，但保持 CAN/HMI 门控关闭，必须先恢复 MCU 原 A，再释放经典服务。
   此保护不能自行回退 MCU，不能宣称是双板原子回退。备份全部保留。
3. 鲁班猫先进入 FD 500k/500k、BRS 关闭、MTU 72。确认接口就绪后，IAP 只更新 B：
   195212 字节，CRC32 FB8BAC2E，SHA256
   `fc232ac7adbae15b8eeec7bda2896844ea06a5a02dd8a7d084afbf3e96402c83`。
   正常健康确认得到 `CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0 GEN=318`。
   整片读回核验 B 镜像一致，原 A、bootloader、KVS、参数逐字节未改，CFSR=0。
4. 固定 20 次 64 字节真实回显逐字节/CRC/帧标志校验均通过。
   最大用户态往返约 180.805 ms，包含任务调度与背景流，不是线速或实时保证。
   回显短测期间无新增错误；被动收到了 FD 状态/测量帧。
5. 随后、业务测试尚未发请求时，Linux 报告 `ERROR-WARNING`，累计 `error_warning=3`。
   当时 TEC/REC、RX/TX errors 读数为零、bus-off 为零，但不能忽略告警。
   健康门控按原标准拒绝继续，接口立即 DOWN。
   **四个 FD RPC、实时日志 CRC 重组、官方历史 Transfer 均未实机验收，不记作通过。**
6. 正常 bootloader START_TRIAL 返回 untouched 原 A，经过 5 秒健康门控自动确认：
   `CURRENT=A CONFIRMED=A PENDING=- ATTEMPTS=0 GEN=321`。
   未重刷 A、未直接写 Flash 元数据、未强制确认。
   最终 SD=0、MOE=0、FOC=0、BENCH ACTIVE=0、CCER=0、CEN=0。
7. 原 boot 文件哈希与符号链接完全恢复；本次门控/保护项撤销。
   经典 CAN MTU 16、500k、ERROR-ACTIVE、TEC/REC=0、错误告警/错误帧/bus-off=0，
   被动连续两组状态帧通过。旧 HMI、CAN、NetworkManager、云隧道均 active。
   热点及校园 Wi-Fi connected；实际热点端点
   `http://192.168.50.1:18089/health` 返回 `{"v":1,"control_enabled":false}`。
   隧道仅监听 192.168.50.1，因此访问 127.0.0.1:18089 被拒绝不是服务失效。

非活动 B 现在保留新的 FD 只读镜像，不是本次开始时的 FD EchoOnly 镜像；
两次原始私有备份均保留。不要分享或提交整片 Flash、私钥或配置备份。
新的 HMI 二进制仅留在独立目录，未替换正在运行的旧 HMI。

自动隔离计算夹具曾报告 30 秒、ADC/FOC 各 600123 次、SD/MOE/CCER=0。
这不是带功率级电机运行或 FD 完整并发业务验收，不能补足上述未执行的项目。

### 告警解释与限制

主线 Rockchip 驱动对 RK3568 V2/V3 标记 CANFD_BROKEN，并说明警告状态下两错误
计数可能读成零；零读数不能抵消警告。板端运行的是厂商 4.19，并非该主线驱动，
因此只能作为排查依据，尚不能证明此次告警的具体根因或承诺升级内核能解决。
依据：[Linux Rockchip CAN 驱动](https://github.com/torvalds/linux/blob/master/drivers/net/can/rockchip/rockchip_canfd-core.c)。
后续需标准 FD 对端交叉验证及实际驱动/位时序排查；当前不应将此配置用于日常 FD。

### 可分享证据

- [20 次真实回显](safety_backups/20261007-canfd-deploy/luban/echo20.json)
- [停止后保留的 3 次告警计数](safety_backups/20261007-canfd-deploy/luban/fd-stopped.json)
- [B 镜像与受保护区域读回核验](safety_backups/20261007-canfd-deploy/stm32-readback.json)
- [回退后经典 CAN/服务/热点核验](safety_backups/20261007-canfd-deploy/luban/recovery.json)
- [最终原 A 与安全锁存](safety_backups/20261007-canfd-deploy/final-classic-console/console.json)
