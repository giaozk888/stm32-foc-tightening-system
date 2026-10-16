---
title: 鲁班猫作为 ESP32 热点：配置与验收
date: 2026-10-01
tags: [嵌入式, 鲁班猫, ESP32, WiFi, NetworkManager, 验收]
status: 真实上传与断网回补通过，云端后端及上传隧道已托管，运动控制锁定
---

# 鲁班猫作为 ESP32 热点

## 实际配置

ESP32/手机 → `wlan0` 热点 → 鲁班猫 NAT → `eth0` 网线 → 电脑共享网络 → 互联网。

| 项目 | 配置 |
| --- | --- |
| 热点名称 | `LubanCat-ESP32` |
| NetworkManager 配置名 | `codex-esp32-hotspot` |
| 配置 UUID | `cc77e1eb-0ee9-4c9e-8f98-c79fe2b36e0e` |
| 无线模式 | AP，2.4 GHz，配置频道 6 |
| 安全 | WPA2-Personal / RSN / CCMP，随机 32 字符密码 |
| 热点网关 | `192.168.50.1/24` |
| 客户端地址 | dnsmasq 自动 DHCP 分配，不手动假定 ESP32 地址 |
| 网络共享 | `ipv4.method shared`：DHCP、DNS、IPv4 转发与 NAT |
| 默认路由保护 | 热点 `ipv4.never-default yes` |
| IPv6 | 热点禁用，不代表系统其他接口禁用 |
| 重启行为 | 配置 `connection.autoconnect yes`，未做整机重启验收 |

原有有线默认路由仍是 `192.168.137.1`，metric 100。校园 Wi-Fi 的 `p2p0` 仍连接，默认路由 metric 600；其校园账号认证未完成，热点上网目前不依赖它。热点与校园站点当前能同时保持激活，但不据此宣称所有场景下并发无线模式稳定。

密码只存于鲁班猫的 root 管理 NetworkManager 配置，文件权限已检查为 `600 root`。没有打印到部署输出、保存到本笔记或写入项目源码。

在**自己的鲁班猫终端**查看密码，勿把结果发到聊天或截图中：

```bash
nmcli --show-secrets -g 802-11-wireless-security.psk connection show codex-esp32-hotspot
```

## 本次验证与边界

- `nmcli`：热点 `100 (connected)`；`iw dev wlan0 info`：`type AP`、正确 SSID。
- 热点地址 `192.168.50.1/24`；dnsmasq 的 UDP 53/67 已监听。
- `net.ipv4.ip_forward = 1`；NetworkManager 已建立 `192.168.50.0/24` 的 MASQUERADE 和 FORWARD 规则。
- 直接查询热点 DNS `192.168.50.1:53`：`rcode=0`，`cloud.tencent.com` 返回 4 条回答。这是主机侧 DNS 检查，不是客户端端到端上网验收。
- 有线 HTTPS 请求返回 200；腾讯云目标路由仍经 `eth0`。
- CAN 保持 `ERROR-ACTIVE`，错误计数 tx=0/rx=0；未改 CAN 参数、STM32 固件、HMI 或电机控制。
- 主机检查时没有无线客户端关联；**ESP32 尚未配网、刷写或验收云端上传**。
- 已撤销先前为校园认证添加的临时 `10.10.244.11/32` 主机路由；未放开临时 SSH 密钥的转发权限。

手机连接测试时建议暂时关闭手机移动数据，避免浏览器实际走移动网络造成“热点上网成功”的误判。确认连接 SSID、客户端获得 `192.168.50.x` 地址、网关/DNS `192.168.50.1`，再访问正常 HTTPS 网站。手机测试不等于 ESP32 的 DHCP、TLS、上传和重连测试已通过。

> [!warning] 项目边界
> 电脑的网络共享必须保持开启。电脑或有线出口断开后，ESP32 与鲁班猫的本地通信仍可工作，云端上传不能假定继续成功。热点不等于服务器 API 已部署、可访问或已完成身份认证，也不等于可开放运动控制。

## 后续 ESP32 验收顺序

1. 先验证手机/独立客户端接入、DHCP、DNS、NAT 和 HTTPS 上网。
2. 通过本地隐藏输入生成 ESP32 私密配置，SSID 使用 `LubanCat-ESP32`；上传 URL 必须是实际可达且已验证的接口，不能使用 ESP32 自己的 `127.0.0.1`。
3. 确认上传服务/隧道的接口监听范围，不能将热点网关地址本身当作已存在的上传 API。公网不得明文传输 API token；受信局域网 HTTP 演示需明确知悉其不等于端到端 TLS。
4. 另行备份 ESP32 NVS、核对固件与分区、获得刷写/复位授权；本次热点设置没有执行这些动作。
5. 验证 ESP32 分配地址、上传确认、服务器实际落库、断线重试和 Modbus TCP 只读。联网不解除运动安全锁定。

## 临时关闭与恢复

只关闭本次热点，保留密码和配置；不删除其他连接：

```bash
nmcli connection modify uuid cc77e1eb-0ee9-4c9e-8f98-c79fe2b36e0e connection.autoconnect no
nmcli connection down uuid cc77e1eb-0ee9-4c9e-8f98-c79fe2b36e0e
```

需要重新开启：

```bash
nmcli connection modify uuid cc77e1eb-0ee9-4c9e-8f98-c79fe2b36e0e connection.autoconnect yes
nmcli connection up uuid cc77e1eb-0ee9-4c9e-8f98-c79fe2b36e0e
```

项目脚本 `tools/setup_lubancat_esp_hotspot.sh` 对同名既有配置拒绝覆盖；失败回退只删除该次执行新建的 UUID。已有热点不要反复运行此初始化脚本来“重新配网”。

## ESP32 部署准备与本次进度

用户确认手机通过热点可上网，并选择继续给 ESP32 配网、同时恢复云上传。目标串口只使用 `COM9`（Espressif VID `303A` / PID `1001`，ESP32-S3、16 MB Flash、8 MB PSRAM），没有打开 STM32 的 `COM5`。

- 完整 Flash 备份 `16,777,216` 字节已读完；备份目录仅当前管理员与 SYSTEM 可访问。目录为 `esp32_s3_gateway/local_config/backup_20261001_171855/`，备份文件不上传、不分享。
- 完整备份 SHA256：`EA48BE574A83ECE806EA1050E9F6CAA70E8212798A53C88C6446DD44CB92E2FB`。
- 备份分区表与 `build_network/partition_table/partition-table.bin` 完全一致：NVS `0x9000/0x6000`，PHY `0xF000/0x1000`，factory APP `0x10000/0x100000`。板上原 APP 与历史 UART-only 构建逐字节匹配。
- 仅更新 APP `0x10000`，新镜像 `1,018,224` 字节；esptool 写后哈希校验通过，并仅复位 ESP32。未写 bootloader、分区表或 NVS；原串口版 APP 可从备份恢复，不宣称新固件已完成运行验收。
- 配网工具 6 项回归通过（含真实 NVS 生成器的合成凭据测试）；这不是现场凭据已生成。
- 被动 USB 日志采集未捕获启动摘要；一次不复位的 ROM 连接探测因正在运行的 USB 串口写超时结束，不据此认定 ESP32 固件崩溃。后续配网后仍需确认真实启动与 IP。
- 鲁班猫 `192.168.50.1:18089/health` 仍为连接拒绝，云上传隧道尚未恢复。
- **目前未写现场 Wi-Fi/API 凭据、未验证 ESP32 热点接入、未验证 Modbus TCP、未验证任何真实云端上传。**

需要用户在自己的鲁班猫终端恢复现有云端 SSH 密码登录，保持窗口开启（不把密码发给助手，不放开原有临时 Codex SSH 密钥权限）：

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 192.168.50.1:18089:127.0.0.1:18088 root@118.25.40.152
```

云端原后端必须仍监听 `127.0.0.1:18088`。健康接口验证通过后，在 Windows 本地双击 `tools/configure_esp32_hotspot_cloud.cmd`，工具预填 SSID 和私有热点上传地址；需要明确输入 `LAN` 接受局域网 HTTP 演示，再隐藏输入热点密码与**服务器 API token**（不是腾讯云 root 密码）。它只生成私密 NVS、不烧录、不复位；生成后再核对、刷写 NVS 并验收。用户明确要求同时恢复上传，因此没有擅自改为 Wi-Fi-only 或使用假 token/假上传地址。

### 云端链路恢复后的最新检查

2026-10-01，用户重新启动云端后端并保持鲁班猫隧道开启。助手从鲁班猫请求 `http://192.168.50.1:18089/health` 已返回 HTTP 200，服务器为 Python 3.8.10，正文 `{"v": 1, "control_enabled": false}`；隧道确实监听热点地址，热点仍为 connected。这覆盖前述“隧道未恢复”的历史状态，但不等于携带现场 API token 的鉴权已验收，也不等于 ESP32 已接入或真实遥测已落库。下一步仍是用户在本地交互工具生成现场私密 NVS，再执行授权写入与实测。

### 配网输入错误后的工具改进

用户第一次/第二次配网未成功，截图明确显示 `Wi-Fi password must be 8..63 bytes`。此时没有生成现场 NVS，也没有烧录。实际热点密码为初始化脚本生成的 32 位随机十六进制字符串，不能把“输入不显示字符”误认为无需填写。

配网入口现使用 `--lubancat-hotspot`：通过原有主机密钥校验、BatchMode SSH 自动捕获**指定热点配置**的密码到本地进程，绝不显示原值；人工只需确认 `LAN` 并隐藏输入服务器 API token。工具随后通过加密 SSH stdin 传输 token，在鲁班猫上向私有热点上传入口执行只读鉴权检查，不将 token 放入 URL、命令行参数或工具输出。鉴权成功（HTTP 200）后才生成 NVS；失败不生成、不刷写。SSID 和上传地址固定限制为本项目热点及其接口，不能随意拿此开关读取其他 Wi-Fi 密码。

每次入口使用新的随机文件名 `private_hotspot/network_hotspot_nvs_*.bin`，旧文件保留，原来固定名称仅是历史描述；后续烧录必须确认最新一次成功生成的具体文件，不能盲目取旧文件。配网工具回归增至 10 项并全通过，包括自动捕获不显示密码、API 鉴权失败不生成、token 通过 SSH stdin 而非命令行、错误 Wi-Fi 密码在 API 提示前即拒绝。测试使用合成凭据，不等于现场 API token 已经验证。

### ESP32 接入与只读 Modbus TCP 实机验收

用户成功生成现场配置 `private_hotspot/network_hotspot_nvs_9742_16583.bin`，生成工具现场 API 鉴权已返回 HTTP 200。仅核实了文件元数据与哈希，没有显示私密字段。文件大小 `24,576` 字节，SHA256 为 `B7045F20D1941E4D1C3218EC8C8EEB742155B42327B2ECAC6ACA3F94E9D7F4ED`。

在核对完整备份仍存在且 COM9 仍为目标 ESP32 后，仅将这份配置写入 ESP32 NVS `0x9000..0xEFFF`；esptool 写后哈希校验通过，随后仅复位 ESP32。未更新 STM32、未发送运动命令。**本段覆盖前述“未写现场 NVS”的历史状态。**

实机结果：

- 热点关联表确认 ESP32 STA MAC `b8:1f:3f:c4:56:28`，信号约 -37 dBm，邻居表确认 IP `192.168.50.114`。此 IP 为当前 DHCP 分配值，不保证永久固定。
- 鲁班猫对 `192.168.50.114:502` 发 FC04 只读请求，返回 `schema=1, wifi=True, fresh=False, CONTROL=LOCKED, quality=0x13, age_ms=4294967295`。
- 上传/队列/丢弃/HTTP 错误/拒绝计数（输入寄存器 30..39 的五个 32 位值）均为 0；没有发送任何写线圈/写寄存器功能码。
- ESP32 真实运行摘要：`wifi=1 fresh=0 uploaded=0 queued=0 dropped=0 http_fail=0 rejected=0 control=LOCKED`。
- 使用官方 NVS 解析器仅在本地进程中取本次 token 并检查条目/字符串 CRC，token 经加密 SSH stdin 只读查询云端；只输出汇总 `samples=0, results=0, control_enabled=false`，不显示或另存 token。
- STM32 COM5 关闭 DTR/RTS 请求后，`FW STATUS`、`NET STATUS` 等只读查询未收到关联应答；随后 3 秒被动接收统计为 0 字节。不能据此单独判断 MCU 崩溃、串口断线或联网发布功能未编译，未执行 ST-LINK halt/复位或 Flash 读写。

结论：ESP32 热点配网与 Modbus TCP 只读网络接口已实机通过；云端隧道和鉴权通过。**STM32 → ESP32 有效观测、真实样本上传/落库、完整拧紧结果上传均尚未通过。** 下一步先确认 STM32 供电、启动状态和 PA9↔GPIO18 / PA10↔GPIO17 / GND 的 UART 链路；如需要部署 STM32 的 NetworkObserver 镜像，须重新确认现场隔离和刷写/复位授权，核实当前 confirmed 槽后走非活动槽 IAP，不因联网而解除安全锁定。

### STM32 无网络观测的只读定位

用户随后确认 STM32 供电、现场隔离。此次只进行被动 CAN 接收、HOTPLUG 读内存和当前镜像回读，没有复位、停核、写 Flash 或发送运动指令。

- 鲁班猫 `can0` 为 `ERROR-ACTIVE`，发送/接收错误计数均为 0；持续收到 `0x180/0x181/0x182`，组序号递增，约 10 Hz。**STM32 并未停机；COM5 无数据不能解释成整个 MCU 崩溃。**
- 状态帧例如 `180#0100020700AAC500`：版本 1、IDLE、FAULT_LATCHED、原因 7；源码定义为 `FOC_FAULT_STARTUP_ZERO_CAL`。角度、电流使用无效哨兵，母线/速度有效位为 0，不将这些字段解释为有效零值。
- HOTPLUG：目标电压约 3.29 V，`VTOR=0x08008000`，当前 A 槽。元数据较新副本为 generation 273，confirmed A、pending none、attempts 0，A 大小 154568 B、CRC32 `53F735F9`。此处是当前证据，不能继续沿用历史 confirmed B 的结论。
- 读取的 A 镜像 SHA256 `768D07B86596EA1A1315CBBC4B05A656FAF3FBB264361BFF2D61D5ACCDFCC459`，与 `foc2_app_a/build/can-log-v1/foc2.bin` 一致，不是本次 NetworkObserver 构建。保存于 `safety_backups/2026-10-01-network-readonly-200846/active_a.bin`。
- 对照同哈希镜像的 ELF 读取故障变量为 7；保存的 U/V 零点变量均为 0。注意这可能表示校准在生成平均值之前已失败，**不能把变量 0 当成当前引脚实测 0 V，也不能仅据此区分未供电、断线或 ADC 错误**。
- `GPIOC ODR=0`、`TIM1 BDTR=0x02002055`（MOE=0），是内部关闭快照，不替代实体急停、外部电压测量或独立功率反馈。

与现场报文吻合的启动故障路径 `StartupZeroCalFaultCommsLoop()` 每 100 ms 只发布 CAN 故障与无效测量；不创建正常 Router/命令/ESP 观测任务。这解释了 CAN 仍有帧而 COM5 不回应、ESP `fresh=0`。另外，板上还是旧 CAN 日志固件，恢复正常启动后也需要按非活动 B 槽 IAP 部署 NetworkObserver，才具备该数据出口。

下一步先核实 PD6010B **采样侧所需供电**，不是只看 STM32 的 ST-Link USB 供电；按原有接线复核 AMP_IU→PA0、AMP_IV→PA1 和共地。不绕过校准或降低阈值。正常 APP 重新启动可能启桥并校准，即使没有 START 也不能保证无动作，因此只有在确认现场隔离及复位权限后才重新启动；之后先验证校准、命令链路和安全状态，再决定是否升级非活动槽。当前真实云端样本仍为 0，未用合成数据替代验收。

### 供电恢复后：网络观测 B 槽部署与真实上传验收

2026-10-01，用户确认驱动板供电并允许复位，随后明确批准非活动 B 槽刷写、试运行和自动确认复位，现场保持隔离。以下最新结果覆盖前述“真实云端样本为 0、网络固件未部署”的历史状态。

1. 先复位现有 A，采集真实启动日志：静态 U/V 零点平均值为 1560/1563，PWM 环境运行零点为 1563/1566，编码器启动读取 20/20 成功；正常任务建立，`STATUS` 为 IDLE、FLT=0、START_REQ=0。旧 A 对 `NET STATUS` 返回 UNKNOWN_COMMAND，与镜像核对一致。
2. `ANALOG SAFE` 锁存关闭，确认 `LATCHED=1 SD=0 MOE=0 FOC=0`；`ESP PING` 获得同请求号 PONG，实际 UART 双向链路恢复。此次没有发送 START、运动模式或继电器命令。
3. 备份非活动 B 整槽与元数据到 `safety_backups/2026-10-01-network-pre-iap/`；B 旧备份 SHA256 `6C01219D73B14322B252D5D71A7D858C48A316FA49D745308CED357A83816A24`，元数据备份 SHA256 `6155E2DE88A27D9806461C42FA7D6FCFE88562438524486B7FED12CB759F3BF7`。原 A 保留用于回退，没有覆盖活动 A。
4. `tools/iap_update.ps1 -StageOnly` 经 COM5 写入 B 网络观测镜像，大小 154976 B、CRC32 `1DE8A9B3`。HOTPLUG 回读 `staged_b_readback.bin` 与构建镜像 SHA256 完全一致：`9046BCFCF5FB62D9A0E72F522964398015B5A0FEE0A5329C67599DC547B59006`。
5. IAP ACTIVE=1 时普通 `ANALOG SAFE STATUS` 被命令白名单拒绝，返回 FW_UPDATE_ACTIVE；助手的提交前检查因此先停止，**没有误当成驱动开启或强制继续复位**。随后按匹配活动 A 镜像的 ELF，用 HOTPLUG 只读复核 SD=0、MOE=0、foc_enable=0、安全锁存=1，才提交 `FW END`。
6. B 试运行自动通过 5 秒健康窗口，并由 bootloader 确认后复位；没有手动强制确认。最终 `CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0 GEN=276 ACTIVE=0`。确认启动后立即重新执行 `ANALOG SAFE`，最终驱动关闭快照再次为 `LATCHED=1 SD=0 MOE=0 FOC=0`。

#### 端到端实机结果

| 检查项 | 真实结果与边界 |
| --- | --- |
| STM32 发布 | 最终 `NET RUN=0 SEQ=297 DROP=0 CONTROL=LOCKED`，约 1 Hz；没有开始作业 |
| ESP32 Wi-Fi / Modbus | `wifi=True fresh=True`，一次快照 age=708 ms、seq=102、flags=0x9、fault=0，控制权限寄存器为 0 |
| ESP 上传队列 | 一次快照 uploaded=106、queued=0、dropped=0、http_fail=0、rejected=0 |
| 腾讯云真实落库 | 样本从 43 增至 113，再增至 293；results=0、control_enabled=false；不是合成测试数据 |
| 逐字段一致性 | 读取 ESP32 seq=289 的 FC04 快照，与腾讯云记录 id=293 的同设备、同 seq、同 uptime 样本核对，15 个字段完全一致 |
| 原 CAN 遥测 | 仍约 10 Hz，can0 ERROR-ACTIVE，TEC/REC=0，错误/丢弃/总线关闭计数为 0 |

逐字段核对包括 seq、uptime、run、cycle、stage、outcome、flags、fault、位置、速度、Iq 原始字段、母线估值、母线质量、接触角、接触后行程；比对原始字段一致**不代表这些物理量均已有效或已标定**。

安全锁存样本 flags=0x9 表示编码器有效和 SAFE，Iq 有效位未置位，因此即使载荷保留旧 `iq_ma`，也必须显示“不可用”，不能用作实时电流。母线 quality=1 表示未验收的诊断估值，不是可信采样。`tools/network_read_probe.py` 已修正展示有效位，并新增 3 项回归覆盖 SAFE 旧 Iq、无效测量和过期样本；之前 22 项服务器/配网测试以及 C 协议契约测试已通过。

#### 尚未验收与使用注意

- 本次完成的是 **STM32 → UART → ESP32 → 热点 → SSH 隧道 → 腾讯云 SQLite** 的真实周期观测，以及 Modbus TCP FC04 只读接口；没有验证完整拧紧终态结果上传，results=0 与未运行作业一致。
- 未进行现场物理断网/断 UART、队列溢出、隧道重建、设备断电回补或服务重启持久化验收；相关离线测试不替代实机故障注入。
- 腾讯云后端和鲁班猫 SSH 隧道目前由用户前台窗口维持，窗口关闭可能中断上传；尚未配置 systemd 托管和开机恢复。热点客户端地址仍为 DHCP 分配。
- 网络运动接口持续锁定；实体急停、独立功率反馈和实机可信标定仍未验收。当前 `ANALOG SAFE` 是软件锁存，普通 APP 复位会退出它并重新启桥校准，不能称为永久安全启动或实体急停。
- 本段复位与 IAP 操作均在用户本轮明确批准及隔离条件下执行，不能将该授权自动延续到未来运动、复位或升级。

### 断网回补与开机服务接管验收（2026-10-01）

本节覆盖上文“尚未断网验收、仍依赖前台窗口”的历史状态。没有复位 STM32/ESP32，没有运动或继电器写命令。

#### 热点短时中断与自动回补

先安排 12 秒后的 systemd 临时恢复任务，再仅关闭指定热点 UUID；保持 eth0、CAN 和控制器不变。12 秒是恢复任务延时，不是整个重连耗时保证。

- ESP32 日志确认 Wi-Fi 断开并安排重连；UART 观测仍持续入队。观察到 queued=34、随后 44，dropped=0；44 是观察值，不代表峰值。
- 热点自动恢复任务 Result=success；ESP32 自行联网，随后 uploaded=1306、queued=0、dropped=0。
- 云端同一设备和同一启动 session 的 500 条记录 seq=1097..1596 连续、无重复，覆盖断网和回补过程。
- 当前缓存是容量 64 的 RAM 队列，不能把此次成功外推成无限断网、溢出无损或断电保存。未验收 UART 断线、队列溢出、掉电回补。

#### 云端后端从前台迁移到 systemd

用户将 `tencent-autostart-20261001.zip` 上传至腾讯云 `/root` 并执行安装。用户截图确认 INSTALL PASS：后端 active/enabled、2048 条原记录保留、控制锁定。

- 服务 `tencent-observations.service`，运行用户 `tightening`，程序 `/opt/tightening-observations`。
- 数据库 `/var/lib/tightening-observations/observations.sqlite3`；原 API token 内部沿用，未输出。后端仍只监听 `127.0.0.1:18088`，未开放公网端口。
- 私密备份 `/root/tencent-observations-autostart-backup-20261001-205357` 保留原配置和一致性数据库快照，不分享备份。
- 原代码目录保留；不要再手动启动同端口旧服务或重复运行初始化安装包。

#### 鲁班猫上传隧道托管与故障恢复

先用专用密钥建立独立回环候选隧道，鉴权读取云端成功（2431 条），才停止已精确核对身份的旧手动隧道并启用新服务。

- 服务 `tightening-cloud-tunnel.service`：active、enabled，用户 `tightening-tunnel`，监听 `192.168.50.1:18089`，只转发云端 `127.0.0.1:18088`。
- 专用私钥只留鲁班猫受限目录；云端授权强制 `/bin/false`，转发目标受限，没有赋予交互 shell 或改 SSH daemon 配置。原助手临时密钥未放宽权限。
- systemd 配置 Restart=always、RestartSec=5，SSH 心跳用于发现失效连接；实际恢复时间还受网络与握手影响。
- 仅终止该服务主进程进行故障注入：PID 38712 → 38884、NRestarts=1；鉴权恢复，云端当次已有 2465 条。
- 最终 ESP32：wifi=True、fresh=True、queued=0、dropped=0、rejected=0；http_fail=4 是切换/故障注入后的累计请求失败数，不是丢弃计数。flags=0x9、safe=True、CONTROL=LOCKED。
- 最终云端汇总 2553 条、results=0、control_enabled=false。切换/重启覆盖窗口 255 条 seq=2296..2550 连续、无重复，设备启动 session 未改变。

上传已不依赖原云端后端/鲁班猫隧道前台窗口，可以关闭这些旧窗口。**电脑网络共享与有线出口仍需保持**；浏览器若通过另一条手动 PC SSH 隧道访问页面，关闭它仍会让该页面不可达，但不等于 ESP32 上传服务停机。

已配置开机启用，不等于实际整机重启验收：本轮没有重启云服务器或鲁班猫，也未对云后端主进程执行崩溃注入。云端服务迁移的数据保留、热点中断恢复、隧道进程自动重启是本次实测范围。实体急停、独立功率反馈、可信标定及完整作业结果上传仍未验收，不解除运动锁定。

只读运维检查（分别在对应机器执行，不打印私密 env）：

```bash
# 腾讯云
systemctl is-active tencent-observations.service
systemctl is-enabled tencent-observations.service
curl -i --max-time 5 http://127.0.0.1:18088/health
# 鲁班猫
systemctl is-active tightening-cloud-tunnel.service
systemctl is-enabled tightening-cloud-tunnel.service
systemctl show tightening-cloud-tunnel.service -p MainPID -p NRestarts
```
