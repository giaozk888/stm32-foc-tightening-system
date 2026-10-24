# Pigweed 日志上位机增量 · 2026-09-30

2026-10-20 新增普通 `PW_LOG_*` token 化候选：`PW_LOG_TOKENIZED_DEFAULT=ON`，不再仅 LOGTOK 测试走压缩。现有 `[PWT]` 接收/导出格式不改，界面当前仍可能显示“待字典解码”，需用同版本 ELF 运行文末离线工具。START/STATUS 等机器协议不变。本轮只编译和离线验证，未部署鲁班猫或刷写 STM32；见 [构建与空间核验](../docs/pw-log-tokenized-default-20261020.md)。

## 链路与范围

按用户选择，改为 CAN 主链路，独立 USB-TTL 只读串口备用。
日志使用低优先级独立 ID、有界队列、CRC 和限流；不是安全认证或无损黑匣子。

STM32 `pw_log` → 非阻塞 CAN 日志队列 → 分片发送 → SocketCAN 重组 → 鲁班猫日志页。
原 UART DMA 日志出口保留，页面下拉框明确切换 CAN / USB-TTL，不静默自动切换。
只读接收器只打开显式配置的字符设备，不扫描端口、不发送串口/CAN 命令、不刷写、不复位。
原 START/ARM/STOP 控制锁定与安全门槛不变。

本机真实日志来自 PC 的 COM5，现已确认它是 STMicroelectronics STLink Virtual COM Port。
STM32 不需要自带 USB：鲁班猫不能直接打开 Windows COM5，可将对应 ST-Link VCP
接到鲁班猫 USB，或使用独立兼容电平 USB-UART 接 STM32 日志 TX 和 GND。
使用 RX 监听连接即可；不要为了日志将 USB-UART TX、DTR/RTS/复位线接到电机控制板。
现有固件日志使用 LPUART1，PA2=TX、PA3=RX，115200/8N1；不是 PB8/PB9 CAN 引脚。
可用 3.3V USB-UART 的 RX 监听 PA2 并共地，不接转换器的 TX/VCC/DTR/RTS/NRST。
若 ST-Link 还给 STM32 供电，不要直接拔掉它；须保持供电不变或用独立监听转换器。
不要同时让另一个串口终端消费同一日志口。非协作监听程序不一定遵守文件锁。

## 配置和部署

1. 板上 `ls -l /dev/serial/by-id/` 找到日志 USB 设备，优先用稳定的 by-id 路径。
2. 板上构建当前源代码，保留原程序目录。构建方法与原 MIPI HMI 相同，仍依赖
   原 `DrmUiPlane` 源文件，不替换 EGLFS/KMS/openvt 配置。
3. 给当前 `lubancat-hmi.service` 增加 drop-in 的环境变量，例如：

```ini
[Service]
Environment=LUBANCAT_HMI_LOG_PORT=/dev/serial/by-id/实际设备名
Environment=LUBANCAT_HMI_LOG_EXPORT_DIR=/home/cat/lubancat_hmi_logs/exports
```

默认 CAN 主链路，不打开备用串口；选择 USB-TTL 后空/未配置端口显示“未配置日志串口”。
波特率固定 115200、8N1，无硬件流控。运行用户须有读取设备的权限。
日志不是心跳，静默不等于设备掉线；页面显示“最近日志 N 秒前”，CAN 新鲜度独立判断。
STM32 复位但 USB 串口未断开时，日志序号会回到起点；点击“重新连接”建立
新接收会话。较小序号可能是旧历史 DUMP，接收器不会猜成重启。

首次部署应先离屏构建/测试，再通过新目录覆盖 ExecStart 并保留旧服务路径。
SSH 已通过原临时密钥恢复。新版已在
`/home/cat/lubancat_hmi_pigweed_20260930/build/lubancat_hmi` 编译并部署。
新增覆盖项 `systemd/zzzz-pigweed-logs.conf`，保留原有环境、SQLite、旧程序和覆盖配置。
以上目录是前一版 UART 日志页，保留作为回退。本次 CAN 版使用
`/home/cat/lubancat_hmi_can_logs_20260930/build/lubancat_hmi` 与
`systemd/zzzzz-can-logs.conf`；备用设备配置为
`/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`。
固件 `CAN_LOG_STREAM=ON` 需编译更新；此次经用户授权先从已确认 A 分区升级 B，
验证后将日志增量部署回 A，保留 A 原有长采样时间、安全通信启动与诊断能力，
B 保留为已验证的回退镜像。驱动先锁存关闭，保持机械隔离，不发送运动指令。
CAN 参数保持 500 kbit/s 不变。
原服务文件和 drop-in 备份在新目录的 `service-backup/`。
已有源代码包 `pigweed-logs-source-20260930.zip` 可用于上传；包里不含密钥或固件二进制。

## 页面与证据

- 2026-09-30 触屏修复：级别改为 4 个高 44 px 的直接选择按钮，链路也改为
  CAN / USB-TTL 两个按钮，不依赖独立弹窗。选中项高亮，重复点击不会取消选择。
  自动界面测试点击所有级别，验证 DEBUG/INFO/WARN/ERROR/CRITICAL/FATAL 的
  可见行数分别为 6/5/4/3，并验证链路切换不清空既有记录。
  本机 10 项测试通过，1024×600 截图已检查。此按钮修复尚未部署：
  远程工具审批额度限制，不能将本机测试宣称为现场触摸验收。
  可在项目根目录运行 `powershell -NoProfile -File tools/deploy_log_touch_fix.ps1`；
  独立目录构建，板上测试通过后才重启 HMI；不刷写或复位 STM32、不重启 CAN。
- 级别筛选、暂停显示不影响后台接收。保存导出全部保留的记录，不限于当前筛选结果。
- 缓存最多 300 条，覆盖计数可见；这不是无限持久化，也不是完整故障黑匣子。
- 导入 `.log` / `.txt` 最大 2 MiB，只接受合法 `[PW]` / `[PWT]`；
  同一次导入的倒序/重复序号被跳过，多次复位日志应拆成多个文件分别导入。
- JSONL 保留原文、级别、模块、来源、设备 tick、会话及历史标志。
  `received_at_utc` 对历史日志是导入时间，不是设备事件发生时间；
  `clock_verified=false`，不宣称上位机与 STM32 时钟已同步。
- 缺序号只说明接收记录存在间隙；不同过滤级别、未收到的记录等都可能导致，
  不是固件 `DROP_FULL` / `DROP_UART` 的直接测量。非日志回复、重复或倒序记录计入跳过。
- 实收文本历史样本见 `tests/fixtures/stm32-log-dump-20260930.log`，共 16 条，序号 8–23。
- 压缩记录在页面保留 token 并标“待字典解码”，当前未实现屏内实时反解码。
  不声称已完成多设备路由日志订阅。CAN 页显示队列满/过期丢弃计数，
  不等于 UART 全部 DROP_FULL / DROP_UART 计数。
- Linux 实时收到的合法新记录会向 syslog 发送 `PW_LOG_RX` 序号/tick/级别摘要，
  不含消息正文；可用 `journalctl _COMM=lubancat_hmi` 验证接收，不另开串口争抢数据。
  历史导入不会产生该标记；串口历史 DUMP 若作为输入仍可能产生接收标记，
  所以实测须发送新生成的日志而非仅重放 DUMP。

## 压缩日志离线解码

使用仓库已有 Google Pigweed 官方 Python 实现，不自行猜格式。
必须选择**产生日志的同一固件版本** ELF，不可只拿“最新” ELF。
工具保留 `raw` 与所有原始字段，增加解码结果、字典 SHA256；未知 token、
参数错误或歧义保持失败。字典匹配需要核实固件，成功查表本身不是匹配证明。

```powershell
python tools/detokenize_hmi_logs.py <导出的.jsonl> --elf <对应固件.elf> --output <新的-decoded.jsonl>
python tests/test_detokenize_hmi_logs.py
```

需 Python >=3.10，工具不会覆盖现有输出、不会访问串口。
`decoded_message` 是独立结果字段，不替换原 token；非零退出码表示解码/输入失败。

## CAN 日志 v1 协议

标准 11-bit ID，经典 CAN，DLC 必须为 8，禁止远程帧/扩展帧。
所有多字节字段均为小端。

| ID | 8 字节内容 |
| --- | --- |
| 0x680 | 版本 1、flags、record_id u16、长度 u8、CRC16 u16、保留 0 |
| 0x681 | record_id u16、分片索引 u8、原文 5 字节（末片零填充） |
| 0x682 | 版本 1、等待队列数、队列满丢弃 u16、过期丢弃 u16、完整入硬件队列记录数 u16 |

原文 1–192 字节，去除末尾 CR/LF；CRC16-CCITT 初值 0xffff、多项式 0x1021。
flags 仅 bit0 合法，标识本次启动第一条完整入队日志；接收成功后建立新会话。
标记丢失时不能保证自动识别复位，手动“重新连接”重置序号基线。
完整记录才进入 PW/PWT 严格解析；缺片、错序、CRC 错误、非零填充不显示成正常日志。
重组最多一条、超时 10 s，设备队列 8 条 + 当前待发 1 条，满/老化均丢弃并计数。
0x682 每秒尝试发送，计数饱和到 65535；完整入队不是收到 ACK 或上位机收到的证明。

MonitorTask 是唯一 FDCAN 访问者；先发送 0x180/181/182，等 5 ms 后服务日志。
每 100 ms 最多 2 帧（含 0x682），硬件 FIFO 留一格；错误计数非零、警告、
error-passive、bus-off 或 FIFO 紧张时停止日志投递，不阻塞日志生产或电机控制。
20 帧/s 的最坏位数估算占 500 kbit/s 不足 0.62%，这是上限估算，不是现场测量。
因此日志适合工程诊断，密集突发会丢失；紧急故障仍优先使用现有状态帧。

只读离屏验收可用 `--log-source can|uart --log-capture-ms 20000 --log-export <目录>`；
捕获时间限制为 1–60 s，结束导出后退出，不发串口/CAN 命令、不复位 MCU。
可加 `--page 7 --screenshot <文件>` 保存真实接收页面。

## 验收状态

Windows Qt6 构建及 9 项 C++/Qt 测试、鲁班猫 Qt5.12.8 构建及 10 项测试通过。
覆盖 CRC、错片、丢片、超时、最大长度、末片填充、非法标志及帧类型；
Linux 伪串口测试验证分包、无命令写入、重连与断开（合成测试，不是实体拔插）。
Python 官方解码器的 4 项测试通过。

真实 CAN 验收：B 与最终 A 均新生成 `LOG TEST 3`、`LOG TOKEN TEST 1`，
上位机同一程序重组接收序号 24–27，文本 3 条、压缩 1 条，全部 `imported=false`、
`source=CAN can0`，缺序号 0、CRC 错误 0。对应 A ELF 官方字典解码成功，
消息为 `token burst index=0 value=-7`；屏内仍显示原 token 和“待字典解码”。
CAN 启动日志队列丢弃 15 条（23 条突发超出 8 条队列），如实显示，不宣称零丢包。

最终 A 固件 154568 字节，IAP CRC32 `0x53F735F9`，
BIN SHA256 `768d07b86596ea1a1315cbbc4b05a656faf3fbb264361bff2d61d5accdfcc459`，
ELF SHA256 `754b9ec2035f1ffd7468e21f4e29c065a9774aae0c6958e205ebbbbc41f3d6ed`。
`CURRENT=A CONFIRMED=A PENDING=- GEN=273`；驱动锁存 `LATCHED=1 SD=0 MOE=0 FOC=0`、
`BUSY=0 MODE=IDLE FLT=0`。没有发送运动指令，没有强制确认不健康试运行。
自动健康确认包含一次正常 bootloader 复位，跨该复位实际收到新启动日志。

持续遥测 10 秒实测：0x180、0x181、0x182 各 100 帧，0x180 缺序号 0；
CAN 保持 ERROR-ACTIVE，tx/rx 错误计数 0；历史 warn/passive/bus-off 3/1/3 未增加。
HMI 主实例 syslog 实收日志与离屏实例的 seq/tick 一致，HMI active/enabled、CAN TX 0。
最终实时数据与截图见 `evidence-can-a/`、`can-log-final-live.png`；
它是实际设备数据离屏渲染，不代替现场 MIPI 触摸验收。

USB-TTL 已识别且 115200/8N1 只读打开成功。用户确认转换器 RX 接 PA2，
但 20 秒原始字节探测（同时生成 3 条新日志）为 0 字节、0 换行；
备用物理收数尚未通过，不能把“设备可打开”当成“备用链路已通”。
探测工具 `tools/lubancat_uart_read_probe.py` 只读取，不发送数据/复位。
剩余验收：新日志页实屏触摸、USB-TTL 物理收数与实体拔插；CAN 主链路已验证。

## 回退

回退 CAN 日志页到前版 UART 页面（不回退 STM32 固件，不删除旧程序）：

```sh
mv /etc/systemd/system/lubancat-hmi.service.d/zzzzz-can-logs.conf /home/cat/lubancat_hmi_can_logs_20260930/zzzzz-can-logs.conf.disabled
systemctl daemon-reload
systemctl restart lubancat-hmi.service
```

恢复后的运行路径应为 `/home/cat/lubancat_hmi_pigweed_20260930/build/lubancat_hmi`。
若再回退旧 UART 日志页覆盖项 `zzzz-pigweed-logs.conf`，则恢复控制锁定版。
以上是回退说明，本轮未执行。
