# LubanCat-2H MIPI 智能拧紧上位机（控制锁定）

面向 1024×600 DSI 触控屏，使用板上已有的 Qt 5 Widgets 和 SocketCAN。
HMI 不驱动电机、不写 STM32 Flash、不修改现有 `main_app` 服务。
2026-10-04 的本地新版本增加手动只读 CAN RPC，请求只走 `0x600`，
回复 `0x601`；不是运动控制帧。旧部署仍保持原状，本次没有部署或刷写。

## 2026-10-08：电机 RPC 服务接口（离线完成，运动仍锁定）

新增独立 `foc.MotorControl` 服务，包含 Arm、StartTightening、Stop、GetOperationStatus。
“控制”页新增“查询电机 RPC 服务（不执行动作）”，可读取缺项、作业状态与 SAFE 锁存。
ARM/START/STOP 按钮继续禁用；当前 MCU 适配层也明确拒绝全部远程动作。
新固件与新 HMI 均未部署，原固件不支持新方法时查询会超时。
实现、协议、测试及待验收事项见 [电机服务说明](../firmware_common/MOTOR_CONTROL_RPC_20261008.md)。

## 2026-10-07：CAN FD 已实测，日常切换未通过，已回退

已选择先用 500k、BRS 关闭的 CAN FD，配套 STM32 `CanFdReadOnly` 与 HMI
`--can-fd`。状态、日志及 RPC 仍保留原 ID/8 字节业务负载，不冒充 64 字节优化。
独立 Linux/Qt5 完整构建和 13 项测试通过；两板实际 FD 64 字节回显 20/20 通过。
持续状态流随后触发鲁班猫 3 次 ERROR-WARNING，业务健康门控拒绝继续，
未启动 FD RPC/Transfer 验收，也未保留 FD 自启动。
当前已恢复原 A、经典 CAN 与原日志触屏 HMI；独立新二进制和备份保留。
说明见 [CAN FD 通信配置](../CAN_FD_COMMUNICATION_20261007.md)。

## 本地新增：CAN RPC 与历史日志导出

“诊断”页增加 Ping、读状态、读18项参数、读诊断和 STM32 最近16条历史日志导出。
当前源码的历史导出已使用官方 Pigweed Transfer Client/TransferThread 与 V2
完成确认，只开放资源 3 的 Read，不包含固件上传。CAN 分片仍是项目适配层。
源码与旧日志触屏部署版本不同；不能把离线编译通过当作当前运行 HMI 已支持该导出。
需配套 A/B `CanRpcReadOnly` 固件；旧固件查询会超时，不应误判为设备故障。
使用方式、协议和测试证据见 [CAN_PIGWEED_RPC.md](../firmware_common/CAN_PIGWEED_RPC.md)。

## 已实现

- 总览、作业、控制、曲线、配方、链路诊断、诊断记录、设备日志八个触控页面。
- 新增 Pigweed 日志页：CAN 主链路、USB-TTL 115200/8N1 备用，只接收、无命令写入；
  支持 `[PW]` 文本及 `[PWT]` 压缩原文、级别筛选、暂停显示（接收继续）、
  历史文件导入、300 条缓存与 JSONL 原子导出。重连日志串口不会复位 MCU。
  此增量已在 Windows 和鲁班猫 Qt5 编译、导入真实 STM32 历史日志并测试；
  已部署到独立目录并切换 HMI 服务，DRM 确认 1024×600 界面层挂到 DSI。
  CAN 使用独立低优先级 ID、CRC 重组与限流，USB-TTL 已识别；具体实时验收状态见下文文档。
  详细链路、解码及部署边界见 [PIGWEED_LOGS.md](PIGWEED_LOGS.md)。
- 新增“控制”页：ARM/START/STOP 作业按钮保持禁用；可在本地预演
  `0x200` 的 8 字节编码，绝不写入 CAN；可被动严格解析 `0x280` 回执，
  但因本机从未发送请求，不把外部回执显示为作业成功。此页已在
  Windows 和鲁班猫离屏构建中验证，鲁班猫服务已切换到新构建；
  MIPI 实屏仍待现场确认。
- 正式控制的软件门槛已抽成 `src/control_workflow.h`：要求同序号的新鲜
  状态/测量、空闲静止、无软件故障，还必须具备**独立**急停回读、功率级
  回读、已验收固件控制端与配方。当前后四项没有可信来源，默认均为假，
  控制页动态列出缺项并保持 START 锁定。命令事务模型区分匹配回执、
  回执超时、状态观察超时与遥测失联；START 未证实或失联时标出
  “需要 STOP”，但当前没有可用的固件执行端，因此不会虚构已停机。
  CAN ACK 不被当成实际启动或拧紧合格。
  `control_workflow_test` 覆盖这些联锁和回执匹配。此增量仅在 Windows
  离线编译/测试；没有向板上部署、发送控制帧或复位 STM32。
- 读取 `can0` 的启用状态、收发计数，非阻塞显示最近 80 条原始经典 CAN 帧。
  “已启用”只表示 Linux 接口 UP，不代表 STM32 在线或业务协议握手成功。
- 校验标准 ID `0x180` 的只读状态帧 v1：版本、帧类型、DLC、保留位及序号均须有效；
  500 ms 内无新帧则显示“状态已过期”。当前正常 APP B 已确认，每约 100 ms 的
  正式状态帧已由鲁班猫实收，HMI 诊断页显示“STM32 状态有效”。超时、
  重复序号、序号回绕及超时后恢复已有可控时钟单元测试；实体断线尚未测试。
- 已部署新版 `0x181` 相对机械角 / q 轴电流和 `0x182` 转速 / 母线估算
  的只读解码、有效性/序号/超时处理。STM32 B 槽已确认运行；鲁班猫实收
  三类帧并在界面显示角度、速度和母线电压。安全态下 q 轴电流保持无效，
  不显示成零扭矩。实况离屏图见 `measurement-live-2026-09-29.png`。
- 总览与“曲线”页显示内存中最近 30 秒的真实角度、转速趋势；仅接受
  `0x180`/`0x181`/`0x182` 同序号、有效且新鲜的数据，状态或测量超时即
  清空曲线。曲线页现可手动保存最多 30 秒的只读诊断快照到 SQLite，包含
  原始单位数值、相对时间、序号和缺序号数量；不是拧紧作业、扭矩曲线或
  合格判定。系统时钟尚未校验，记录显式标记 `clock_verified=0`。
- “记录”页只读列出最近 50 条快照，显示样本数、缺序号、时长和时钟风险；
  可将选中记录导出为包含原始单位及质量字段的 CSV。重复导出不会覆盖现有文件。
- “作业”页现显示只读启动前观察：状态帧新鲜度、模式、软件故障、编码器标志，
  以及同序号的角度、转速、母线估算和驱动 SD 输出状态。它始终显示“不可启动”；
  SD 是输出标志而非功率级回读，软件故障清零也不是物理急停验收。
- 未接入的扭矩、配方、合格判定明确显示为空；控制按钮禁用。
- 适配 1024×600；支持离屏截图进行视觉检查。

## 板上构建与运行

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j2
QT_QPA_PLATFORM=offscreen build/lubancat_hmi --screenshot /tmp/lubancat-hmi.png
```

板上 Qt5 编译和离屏截图已通过。普通 EGLFS 窗口曾只有背光、没有界面；
现已在板上构建时复用原项目的 `DrmUiPlane`，DRM 状态确认第二个
1024×600 ARGB 界面图层挂到 DSI，实物显示已由用户确认可用。
该构建暂时依赖板上的
`/home/cat/lubanmao-cpp-rknn/qt_cabin_panel/src/drm_ui_plane.{h,cpp}`。
手动启动时需要原程序使用的虚拟终端与 EGLFS 环境：

```sh
export QT_QPA_PLATFORM=eglfs
export QT_QPA_EGLFS_INTEGRATION=eglfs_kms
export QT_QPA_EGLFS_KMS_ATOMIC=1
export QT_QPA_EGLFS_KMS_CONFIG=/home/cat/lubanmao-cpp-rknn/eglfs_kms_overlay.json
export QT_QPA_EVDEV_TOUCHSCREEN_PARAMETERS=/dev/input/event2
export XDG_RUNTIME_DIR=/run/user/0
openvt -f -c 1 -s -w -- ./build/lubancat_hmi
```

已在板上安装并启用 `systemd/lubancat-can0.service` 和
`systemd/lubancat-hmi.service`。前者只在 `can0` 关闭时配置为 500 kbit/s、
`restart-ms 100` 后启用；若接口已运行且参数正确，就不重配或中断总线；
若已运行但参数不符，会报错而不擅自关闭。后者依赖前者，并沿用已验证的
`openvt`、EGLFS/KMS 和触摸设备配置。当前板上已从临时服务切换到这两个
持久服务，均为 active，且已 enable。新版 HMI 由
`systemd/measurement.conf` drop-in 切换到独立 `build_trend` 构建目录，原 unit 和旧二进制
保留可回退；后续 `systemd/snapshot.conf` 又将运行路径切到独立
`/home/cat/lubancat_hmi_snapshot/build/lubancat_hmi`；随后
`systemd/zz-browser.conf` 指向独立 `build_browser`，
`systemd/zz-preflight.conf` 指向独立 `build_preflight`，原构建仍保留。
本轮新增 `systemd/zzz-control-locked.conf`，运行独立目录
`/home/cat/lubancat_hmi_control_locked/build/lubancat_hmi`，仅新增
锁定的控制协议页，不改变 `can0` 和 STM32；切换后服务均 active。
原 `build_preflight` 与覆盖项保留，需回退时移走新覆盖项、重载
systemd 并重启 HMI。鲁班猫本轮截图时间显示 2024 年，时钟不可信。
**尚未做整机重启验收**。
原 MIPI 摄像头服务保持禁用，HMI 与其互斥。`linuxfb` 对照测试期间板子
曾失去网络响应，不要改用该后端。维护命令：

```sh
systemctl status lubancat-can0.service lubancat-hmi.service
systemctl is-enabled lubancat-can0.service lubancat-hmi.service
ip -details -statistics link show can0
# 需要停止并撤销 HMI 自启时：
systemctl disable --now lubancat-hmi.service
```

板上 RTC 已手动校准，但 `ntpd` 因 DNS 不通仍未同步；在记录作业时间前需
修复网络/NTP 并验证重启后的时钟。STM32 的 `ANALOG SAFE` 锁存会在其复位
时清除，因此不能把目前电机功率级关闭状态当成永久联锁。

本机 Windows 视觉预览可使用 Qt 6 构建，然后执行
`lubancat_hmi.exe --page 0 --screenshot overview-preview.png`；
`--page` 可选 0–7，仅用于逐页截图检查。Windows 不提供 SocketCAN，
因此预览中的 `can0` 会显示未启用。

系统分层、待实现的业务帧草案和控制安全门槛见 [ARCHITECTURE.md](ARCHITECTURE.md)。
本轮现场验收结论见 [ACCEPTANCE_2026-09-29.md](ACCEPTANCE_2026-09-29.md)：
只读功能通过，但观察到一次三帧共同跳号及 `can0` bus-off 累计值 2，
可靠性和整机重启验收尚未完成。

后续只读快照实现记录见 [SNAPSHOT_2026-09-29.md](SNAPSHOT_2026-09-29.md)。
记录浏览与 CSV 导出增量见 [BROWSER_EXPORT_2026-09-29.md](BROWSER_EXPORT_2026-09-29.md)。

## 下一步协议边界

当前已完成只读状态帧 `0x180` 和测量帧 `0x181`、`0x182` 的正式 APP
持续发送、鲁班猫接收和 HMI 解码验证；不代表电机控制或扭矩测量业务已完成。此前双向通信也由
SRAM 诊断帧确认。状态字节布局见
[`../firmware_common/README.md`](../firmware_common/README.md)。
要开放作业和配方，需要双方约定版本、节点/报文 ID、序号、心跳与超时、
扭矩和角度的单位/标定、作业状态机、结果记录及安全联锁。HMI 应只发
受限的业务命令，由 STM32 独立完成参数校验和硬件保护，且不能由上位机
绕过急停、故障锁存或功率级使能条件。

## 可信采样/联锁第一阶段（2026-09-30，本地未部署）

新增独立 `SafetyLocked` 固件诊断预设，以及0x184质量/缺项、0x185/186原码观测。
“链路诊断”显示采集失败、三次不一致、未标定验收、过期和同序号原码；控制页
新增“采样标定/保护未验收”锁定项。这不是完整硬件安全功能，也不开放控制。
正常固件启动流程、板上应用与部署镜像仍保留。实现、测试与诊断版部署限制见
[`SAFETY_SENSING_PHASE1.md`](../firmware_common/SAFETY_SENSING_PHASE1.md)。
