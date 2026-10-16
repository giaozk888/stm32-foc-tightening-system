# ESP32 Wi-Fi / 上传服务器 / Modbus TCP

这是联网**观测与结果归档**链路，不开放网络运动控制。设备安全联锁尚未验收，不能用联网功能绕过锁定。旧 `upper_computer` 本机串口页面与鲁班猫 MIPI HMI 不受替换。

```text
STM32 一秒遥测 + 终态结果 → USART1 Router / NET1 CRC32 → ESP32
                                                        ├─ Wi-Fi HTTP(S) → 服务器 SQLite / 查询 / CSV
                                                        └─ Modbus TCP FC04 → PLC/PC 只读观测
网络命令 → 不进入 STM32 控制解析器；FC05/06/15/16 等一律拒绝
```

## 功能和限制

- ESP32 STA、WPA2/WPA3、Wi-Fi 断线退避重连；无配置时网络关闭，原 UART HELLO/PING 继续工作。不在源码、日志或构建配置中保存 Wi-Fi 密码/API token，改用独立 NVS 配置。
- STM32 `ESP_NETWORK_OBSERVER=ON` 才发送一秒一次遥测；实际 `START` 被本地控制流程接受时分配 run，现有结果打印入口发布终态结果（成功、停止、超时、终止、故障）。没有模拟作业自动上报，联网不会产生 START。
- `NET1` 为 16 个整数及 CRC32，独立校验格式、范围和载荷，承载角度、转速、Iq、阶段、结果及质量。**Iq 不是扭矩；母线估值始终未标定验收**。活动控制时原诊断母线采样不可用，会标不可用/过期，不能沿用旧数冒充实时值。
- HTTP Bearer 鉴权，HTTPS 使用证书链和主机名验证，禁止自动重定向，避免密钥发往其他地址。HTTPS 等待 SNTP 时间；DNS/NTP 不通时不能宣称 TLS 上传可用。局域网 HTTP 仅在显式允许后用于演示，不代表加密或工业网络安全验收。
- 上传工作与 UART 接收分任务；64 条遥测、16 条结果独立 RAM 队列，结果优先，满时拒绝新项并累计 `dropped`，不会无声覆盖。失败保留队首、指数退避；服务端提交 SQLite 后才回 `X-Observation-Ack: session:seq`，匹配准确 ACK 才出队。
- SQLite WAL、同步提交；事件键为 `gateway MAC + observation session + STM32 seq`，完全相同的重传幂等，不同内容复用同键返回 409。服务器重启后记录仍在。
- **ESP 队列仍是 RAM**，重启会丢失未确认数据；STM32→ESP 也是有界、尽力传输，不含端到端结果重传确认。因此这版不是零丢失审计系统。结果停电持久化/可靠转发应作为下一阶段。
- session 是观测会话：ESP 启动创建随机标识；检测 STM32 序号回退和运行时间明显回退时切换。不是可信设备身份、安全命令 nonce 或严格的 MCU 启动唯一编号。很短的复位与乱序边界需实机验收，后续可增加明确 MCU 启动标识。
- 网页可查询设备最近接收记录、按类型分页、查看作业结果和导出 CSV。延迟回补不等于在线；记录时间为**服务器接收时间**，不是经校准的作业发生时间。
- Modbus TCP 标准端口 502、Unit 1，仅 FC04。超过 3 秒无新设备观测时，读取设备数据区返回异常 04，网关诊断区仍可读。TCP 半包按 MBAP 长度读取，有大小、时间和请求次数限制。
- 1 Hz 观测不替代现有 CAN/MIPI 高频曲线记录，也不是完整高频拧紧曲线上传。没有把联网数据用于闭环电机控制或安全保护。

## 启动服务器

无需 pip 依赖，使用标准库。代码按 Python 3.8+ 兼容方式准备；本地静态语法和当前 Python 回归已通过，具体目标版本须先运行服务器测试。本次腾讯云 Ubuntu 20.04 / Python 3.8 的准备流程见 `cloud/README.md`，目标机尚未验收。从项目根运行，先在本地设置长随机 API token，不把 token 发在聊天里或放进 URL。示例用隐藏输入：

Windows PowerShell：

```powershell
$taskSecret = Read-Host 'Server API token (至少24字符)' -AsSecureString
$env:TIGHTEN_API_TOKEN = [System.Net.NetworkCredential]::new('', $taskSecret).Password
python -m network_server.server --bind 127.0.0.1 --port 8088
```

鲁班猫/ Linux：

```sh
read -r -s -p 'Server API token: ' TIGHTEN_API_TOKEN; echo
export TIGHTEN_API_TOKEN
python3 -m network_server.server --bind 0.0.0.0 --port 8088 --allow-lan-http
```

局域网演示需要 ESP32 能路由到服务器 IP:8088；不要开放到公网或自动改防火墙。正式远程部署应由 HTTPS 反向代理、访问限制和独立设备密钥保护，Python 开发服务器不是面向公网的生产入口。

打开 `http://服务器IP:8088/`，在页面输入 token。页面仅内存持有、不写 localStorage，不含控制按钮。数据在 `network_data/observations.sqlite3`；分页接口每次最多 500 条，可按 `after` 游标持续导出。需要自行规划磁盘容量与备份，磁盘写失败返回 503 而非假确认。

可选 systemd 模板在 `systemd/tightening-observations.service`，**未安装**。默认部署目录 `/home/cat/tightening_network`，运行用户 `cat`，准备 `network_data` 并使 `cat` 可写。`server.env` 只含 `TIGHTEN_API_TOKEN=...`，限制权限，勿提交仓库。此模板显式用于受信局域网 HTTP，不触碰 `can0`、HMI 或 `main_app`。

## 构建与私密配置

ESP32 使用独立 `build_network`，保留原已验证构建：

```powershell
./tools/build_network_gateway.ps1
```

两个 STM32 独立观测构建目录为 `foc2_app_a/build/NetworkObserver`、`foc2_app_b/build/NetworkObserver`；选项 `ESP_NETWORK_OBSERVER=ON`、`CAN_CONTROL_REJECT_ONLY=ON`、`CAN_LOG_STREAM=ON`、Release。新功能默认 OFF，不兼容 SafetyLocked/CanProbe 诊断启动。不会改变既有固件默认启动的安全性质；**正常 APP 的复位仍可能启桥，不能盲目刷写**。部署必须检查当前 confirmed 槽和新的现场隔离条件，使用非活动槽 IAP，不能直接覆盖已确认槽。

2026-10-01 的 ESP32 完整构建通过，但现有 1 MiB 应用分区只剩约 3% 空间。当前二进制能容纳，不应据此认为后续功能可以继续无上限添加。正式升级前需规划分区容量、回滚/OTA；修改分区表会影响部署，不能直接擦除重刷。当前版本不包含 ESP32 OTA。

ESP32 NVS 配置生成（不刷写）：

```powershell
& C:/Espressif/tools/python/v6.1/venv/Scripts/python.exe tools/provision_gateway.py `
  --ssid '你的2.4GHz Wi-Fi名称' `
  --url 'http://服务器IP:8088/api/v1/observations' --allow-lan-http
```

密码用隐藏输入；token 优先使用本地 `TIGHTEN_API_TOKEN`，否则隐藏输入。生成 `esp32_s3_gateway/local_config/network_nvs.bin`（0x6000），**文件含明文密钥**，不得分享；输出已存在时拒绝覆盖。不是 Flash 加密或 Secure Boot。NVS 模块不自动擦除失败分区。

不熟悉命令行时，在 Windows 双击 `tools/configure_cloud_gateway.cmd`，本地依次输入 SSID、上传 URL、密码及云端相同的 API token。交互模式始终重新隐藏询问 token，不沿用可能过期的环境变量。这个入口**只生成配置，不烧录也不复位**。不要在鲁班猫或腾讯云终端输入 Windows 文件路径。配置工具拒绝 loopback/localhost 上传地址和公网 HTTP；局域网 HTTP 限制为明确允许的 RFC1918 IPv4 地址。

云端经 SSH 桥接的场景：先验证 ESP32 所连 Wi-Fi 能访问鲁班猫对应的局域网地址，随后让鲁班猫的 SSH 隧道监听该**明确接口地址**，而不是 `127.0.0.1` 或 `0.0.0.0`。只有局域网连通验证通过后，才可填 `http://鲁班猫局域网IP:18089/api/v1/observations`。此段 Wi-Fi HTTP 仍是明文演示，鲁班猫到云端部分由 SSH 加密，不等于端到端 HTTPS 或工业网络安全验收。

现有默认分区 NVS 为 0x9000 / 0x6000。真正配置写入会替换该分区（含旧 NVS 配置），应先备份并核对所用分区表；不要把本工具当作自动烧录。配置后只复位 ESP32，不连接或操作 STM32 复位线。当前源码保持 PA9↔GPIO18、PA10↔GPIO17、共地的既有 UART 接线，CAN 不变。

## Modbus 输入寄存器表

地址是 PDU **零基偏移**，不是 30001 的显示编号；32 位值高字在前、有符号值为二补码。

| 偏移 | 内容 |
| --- | --- |
| 0 | 协议版本 1 |
| 1 | 网关标志：bit0 Wi-Fi 有 IP，bit1 设备观测 ≤3 s |
| 2 | 网络控制权限，恒为 0 |
| 3 | 母线质量：1 未验收、2 不可用、16 过期（可组合） |
| 4–5 | 距最新接收的设备观测时间 ms |
| 6–7 / 8–9 / 10–11 | 序号 / MCU uptime ms / run |
| 12 / 13 / 14 | cycle / stage / outcome |
| 15 | 观测标志：1 编码器有效、2 Iq 可观测、4 busy、8 软件 SAFE、16 contact、32 SD 高、64 fault；不是安全许可 |
| 16 / 17 | 故障原因 / 保留 0 |
| 18–19 / 20–21 / 22–23 | 角度×100 / rpm×10 / Iq mA，均有符号 |
| 24–25 | 母线估值 mV，须结合质量使用 |
| 26–27 / 28–29 | 接触角×100 / 接触后行程×100，须结合 contact 标志 |
| 30–31 / 32–33 | 上传确认数 / 当前队列条数 |
| 34–35 / 36–37 / 38–39 | 队列拒收数 / HTTP 失败数 / NET1 无效载荷数 |

outcome：0 NONE、1 OK、2 STOPPED、3 RUNDOWN_TIMEOUT、4 STOP_TIMEOUT、5 ABORT、6 FAULT；stage 沿用 STM32 0–11，见 `main.c` 状态枚举。写功能返回异常 01，越界地址异常 02，错误数量/格式异常 03，设备数据过期异常 04。

## 验证

```powershell
python -m unittest discover -s network_server/tests -v
cmake --build tests/network_gateway_host/build
ctest --test-dir tests/network_gateway_host/build --output-on-failure
node --check network_server/app.js
# 配置及部署完成后，仅读取，不发控制命令：
python tools/network_read_probe.py --esp-ip ESP32的IP --server http://服务器IP:8088
```

实机验收需验证：Wi-Fi 获取 IP；新 STM32 观测序号增长；服务器 uploaded 增长且 SQLite 查到同设备/会话；断网恢复后同键重传无重复；FC04 数据/单位正确；断 UART 后设备数据读数报过期而非旧值；队列溢出可观测；无复位/动作输出变化。**尚未完成这些板上测试，不能把离线测试写成联网实机验收成功。**

实现、离线验证和部署边界记录见项目根目录 `STAGE12_1_NETWORK_OBSERVATION_20261001.md`。页面测试截图使用合成数据，不是实际电机作业记录。
