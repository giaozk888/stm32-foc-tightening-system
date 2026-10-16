# ESP32 Wi-Fi、服务器上传与 Modbus TCP：实现及离线验收

日期：2026-10-01

## 当前结论

新增的联网观测代码已实现，STM32 A/B、ESP32-S3 均构建通过，服务器和通信协议离线测试通过。**本轮没有刷写、复位、操作电机、安装远端服务或完成实机联网验收。**

本阶段把原有 ESP32 UART/Router 往返扩展为数据出口，而不是网络运动控制入口。实体急停和独立功率反馈仍没有验收，HTTP 不提供 START/运动接口，Modbus TCP 不接受任何写功能。网络权限恒为锁定，既有本地控制、安全状态和固件启动行为不因这个数据出口而变成已验收安全系统。

## 数据链路与功能

```text
STM32 原有运行状态 / 终态结果
    → USART1、Router 文本包、NET1 CRC32
    → ESP32-S3
        ├─ Wi-Fi STA → HTTP(S) → SQLite → 网页查询 / 作业结果 / CSV
        └─ Modbus TCP :502、Unit 1、FC04 → PC / PLC 只读观测
```

### STM32

- 新选项 `ESP_NETWORK_OBSERVER` 默认 OFF，开启后在 MonitorTask 每秒发布观测，不在 FOC 中断做联网工作。
- 已接受的本地 START 分配 run，现有终态结果打印入口发送结果记录。联网本身不启动作业。
- 载荷包含序号、uptime、run、cycle、stage、outcome、flags、fault、角度、转速、Iq、母线估值及质量、接触角、接触后行程、记录类型。
- NET1 进行 CRC32、长度、整数范围、终态结果条件校验。通过有界 ESP UART 队列发送，不广播到本地控制控制台。
- ESP 入站仍使用原有握手/PONG 白名单，不新增网络命令到电机解析器。
- 观测任务丢包计数可通过本地 `NETSTATUS` 查询；不能将队列成功入队视为服务器落库成功。

### ESP32

- NVS 配置 Wi-Fi SSID/密码、上传 URL、API token；源码不嵌入现场密钥。缺配置时不启用网络，保留原 UART 链路。
- WPA2/WPA3 STA，获取 IP 后提供服务；Wi-Fi 断线退避重连。
- UART 接收与 HTTP 上传独立任务，遥测队列 64 项、结果队列 16 项；结果优先选取。队列满拒收新项，并记录 dropped。
- 上传失败保留队首重试；只有 HTTP 200/201 且准确返回 `X-Observation-Ack: session:seq` 才出队并增加 uploaded。
- HTTPS 校验服务端证书与主机名，先等 SNTP 时间，禁用自动重定向。明文 HTTP 必须显式选择受信局域网演示模式，不是公网生产方案。
- Modbus TCP 仅 FC04，提供 40 个输入寄存器。所有写功能返回异常 01，不转发到现有 Modbus RTU 继电器。
- 大于 3 秒无新观测，设备数据区读取返回异常 04；网关诊断区仍可读。支持 TCP 分段，限制报文、请求数及读取时间。

### 服务器与页面

- Python 标准库服务，Bearer 鉴权，严格验证版本、字段集合、整数类型、范围和结果条件。
- SQLite WAL / 同步提交，落库成功后才确认；键为设备 MAC、观测会话、序号，相同重传幂等，不同内容占同键返回 409，写失败返回 503 且不假确认。
- 页面显示落库统计、设备最近接收记录、作业结果；支持类型筛选、游标分页及 CSV 导出，适配电脑和手机。
- 页面不提供运动按钮；API token 只在页面内存保存。无效角度/转速/Iq、不可用或过期母线观测显示“不可用”。
- 记录服务器接收时间和 MCU uptime；离线回补记录不等于设备实时在线。

## 主要文件

| 范围 | 文件 |
| --- | --- |
| 共享协议与发布 | `firmware_common/network_v1.h/.c`、`firmware_common/network_observer.inc` |
| STM32 接入 | `foc2_app_a/Core/Src/main.c`、`foc2_app_b/Core/Src/main.c` 及各自 CMake |
| ESP 网关 | `esp32_s3_gateway/main/gateway.h/.c`、`modbus_ro.h/.c`、`main.c` |
| 服务器 | `network_server/schema.py`、`store.py`、`server.py` |
| 页面 | `network_server/index.html`、`app.js`、`style.css` |
| 构建及配置 | `tools/build_network_gateway.ps1`、`tools/provision_gateway.py` |
| 只读验收 | `tools/network_read_probe.py` |
| 自动化测试 | `tests/network_gateway_host`、`network_server/tests` |

详细启动方式、私密配置方法和 Modbus 寄存器表：`network_server/README.md`。

## 已执行的离线验证

| 项目 | 结果与范围 |
| --- | --- |
| STM32 A / B | 独立 NetworkObserver Release 构建通过；没有刷写 |
| ESP32-S3 | ESP-IDF 6.1 完整构建及增量复验通过；没有刷写 |
| C 协议契约 | CTest 1 个测试程序通过；CRC、整数边界、Router 往返、Modbus 全部非 FC04 拒绝、过期/越界、10,000 个随机报文输入 |
| 服务器与配置 | ESP-IDF Python 运行 15 个 unittest 全通过，包含鉴权、重复/冲突、并发、重启后持久化、磁盘失败不确认、CSV、配置保护 |
| 配置镜像 | 使用合成 SSID/密码/token 实际生成 0x6000 NVS 镜像并检查大小；临时目录随测试清理，未生成现场配置或刷入 |
| 旧上位机 | `upper_computer/tests` 7 项回归通过 |
| 页面 | 无头浏览器验证电脑/手机、筛选、CSV 下载、无横向页面溢出与 JS 错误；截图人工查看 |

页面测试截图 `network_server/test_artifacts/desktop.png`、`mobile.png` 使用**合成数据**，不能作为电机运行或真实联网的证据。桌面分页表在手机上有内部横向滚动，以保留完整字段。

### 构建产物

| 产物 | 字节数 | SHA256 |
| --- | ---: | --- |
| `foc2_app_a/build/NetworkObserver/foc2.bin` | 155872 | `25181C9D1994BAEC2EFA2FC096ACE7A94557A0C9B2CE0849CA641D9517462BC6` |
| `foc2_app_b/build/NetworkObserver/foc2.bin` | 154976 | `9046BCFCF5FB62D9A0E72F522964398015B5A0FEE0A5329C67599DC547B59006` |
| `esp32_s3_gateway/build_network/stm32_esp32_gateway.bin` | 1018224 | `11AF30C37E2F328BDD0240952EEED90F5BA3EA38382D5588CFB0BDC39753FB3A` |

ESP 应用分区现为 1 MiB，本次剩余 30352 字节，约 3%。虽然大小检查通过，后续添加功能之前必须规划容量与升级/回滚策略，当前没有 ESP OTA。分区迁移不是自动擦除或重刷的授权。

## 本轮解决的问题

1. ESP 原程序只有 UART 握手，没有数据出站：新增严格 NET1 观测协议和上传任务，保留原入站白名单。
2. HTTP 成功与真实落库确认可能混淆：服务端提交数据库后才返回准确事件 ACK，网关校验后出队。
3. 重试可能重复入库：使用设备、会话、序号唯一键，同内容重传去重，内容冲突拒绝。
4. 阻塞上传可能拖慢串口：拆为独立任务，UART 只执行有界入队；结果独立队列，溢出明确计数。
5. 过期观测可能伪装实时数据：Modbus 对过期设备区返回异常；页面区分有效字段与不可用观测，母线始终标未验收估值。
6. Windows ESP-IDF 构建的 bootloader 子 CMake 未继承编译器搜索目录：构建脚本传入明确、正斜杠的工具目录，并转交子构建。完整构建通过，没有修改本机 SDK 或覆写原已验证构建目录。

## 仍未完成与部署前提

- 尚未确定实际服务器位置，也没有现场 Wi-Fi 私密配置。建议服务器放鲁班猫，ESP32 与鲁班猫处于可互访的受信局域网；是否采用须由用户确定。
- 本轮没有读写任何硬件串口、STLINK、STM32 或 ESP Flash，没有 SSH 部署，更没有启动新的运动流程。
- STM32 正常 APP 复位仍可能启桥，不能盲刷。部署需重新核对现场隔离、当前 confirmed 槽，使用非活动槽 IAP；既有安全条件不能靠历史回答自动延续。
- NVS 镜像包含明文密钥，生成和备份需本地保护。真正写 NVS 会替换目标分区，必须先核对分区表和备份旧配置。
- 实机必须验收 Wi-Fi 获取 IP、串口观测序号增长、服务器实际落库、上传 ACK、断网恢复去重、Modbus FC04 实际读数、UART 断开后过期处理、队列溢出可观测；不得为测试发送运动命令。
- RAM 队列断电丢失、STM32→ESP 无端到端结果重传、会话复位识别边界尚存在。当前是联网观测版，不是零丢失工业追溯系统。
- 1 Hz 数据不等于完整拧紧曲线上传；Iq 不等于标定扭矩，母线估值未可信采样验收；不作为安全保护输入。
- 实体急停、独立功率反馈、可信采样和网络安全验收仍独立待完成。Modbus TCP 只读观察不能替代安全联锁。
