# 只读多设备 Router：使用说明

新增 Transfer 试验版（2026-10-06，**仅离线验证，未部署实机**）：类型9支持有界通用二进制包转发，端点使用官方 `pw_transfer`，只注册历史日志和带软件 CRC 的编码器快照下载。协议、限制和使用方法见 [Transfer 经 Router 转发](TRANSFER_ROUTING.md)；Docker/格式化见 [开发环境](../DEVELOPMENT_ENVIRONMENT.md)。以下实机结果都是此前版本的历史记录，不代表新增 Transfer 或 ADC 双缓冲已上板通过。

最新只读 RPC 试验版（2026-10-05）：类型8承载真正的 Pigweed Server，仅开放 STM32 节点1的 Ping/GetStatus/GetParams/GetDiagnostics。已更新 ESP32、通过 IAP 确认 STM32 A 槽（GEN=299）并重新安全锁存。首次 Wi-Fi 突发查询超时，修复仅 RPC 使用的串口排队背压后，同条件双客户端80次、USB40次查询通过。实体B保留首版RPC回退镜像；完整STM32回读和运行时栈余量待补。白话架构、失败复盘和使用说明见 [Router结合pw_rpc](../嵌入式实习面试笔记/16_Router结合pw_rpc_白话实现与验证.md)。旧 CAN/Transfer 保持独立。

此前 PING/STATUS 实机验收（历史记录）：修复 STM32 Router 栈耗尽后，已刷写并确认 A 槽，更新 ESP32 应用。**PC USB—STM32—UART—ESP32，以及 PC TCP—鲁班猫—Wi-Fi/TCP—ESP32—UART—STM32，均往返验收通过**；PC—鲁班猫入口两次断线自动重连通过。最终 STM32 全量 Flash 回读因 ST-Link USB 错误待补。节点5使用软件模拟工装，不是五块实体板验收。

详细记录：[Router 实机验收](../嵌入式实习面试笔记/15_Router实机验收_20261005.md)。全程未发送运动指令；复位后的正常启动仍有原来的 PWM/校准流程，已在确认后重新安全锁存关闭。

## 1. 先在电脑上看它工作

在项目根目录执行：

```powershell
cd 'D:\new project'
python -m router_network.demo
```

演示自动创建五个软件节点，通过真正的 `127.0.0.1` TCP socket 相连：

```text
主板模拟(1) ─ ESP32模拟(2) ─ 控制盒/鲁班猫模拟(3) ─ 电脑模拟(4)
                                      └─ 工装模拟(5)
```

看到 `result: PASS`、`directed_pairs: 20`、`ping_and_status_exchanges: 40` 表示所有不同节点之间都能做 PING 和路由状态查询。`hardware: false` 明确表示没有接触硬件。

## 2. 本次实际增加了什么

- 电脑/鲁班猫的独立 Router 进程：TCP、UART、USB 转串口三种适配器。
- ESP32 复用真实 STM32 Router 核心，增加一个 TCP 上游连接，与 UART 双向转发；原来的观测上传和只读 Modbus 保留。
- STM32 A/B 增加只读诊断端点，直接在 Router 任务内处理，不进入电机命令解析器。
- HELLO/ANNOUNCE 发现、来源反向学习、5 秒探测、15 秒路由老化、TTL 和重复包过滤。
- 主机端断线立即删除对应出口的路由，主动连接支持 1～30 秒退避重连。ESP32 在断线/新连接时切换代次，旧 TX 和排队 RX 不能混进新会话。
- 拆包/粘包、过长行和非法字节后的重同步、有界收发队列及限流。

这不是最短路径/链路状态路由协议，也不是可信身份认证。节点 ID 是协议地址，不是用户身份。相同节点号不能同时使用；类型7/8在重启但链路未断时的序号重用仍受 30 秒重复缓存窗口影响。新增类型9改用包 ID/偏移/CRC 去重，已做客户端进程重启回归，详见 Transfer 文档。

## 3. 为什么网络端只读

使用原有 ASCII R1 外壳：

```text
@R1 源节点 目标节点 类型 序号 TTL 载荷长度 载荷
@R1 4 1 7 12 8 7 PING 42
```

类型 **7** 专用于本次诊断；原有 4/5 的可靠事件/确认和 6 的日志不改变。

网络入口只接受：

| 类型 | 载荷 | 意义 |
| --- | --- | --- |
| 3 | `HELLO` / `ANNOUNCE` | 发现设备及学习回复出口 |
| 7 | `PING 请求号` / `PONG 请求号 节点号` | 检查完整往返 |
| 7 | `STATUS 请求号` | 查询 Router 计数，不是电机状态 |
| 7 | `INFO 请求号 节点号 RX TX 无路由 重复包` | 返回四个路由计数 |

请求号为 1～65535，回复必须与源节点、请求号和回复类型匹配。诊断禁止广播；TTL 为 1～8。

上面的表是上一版 `RouterNetworkReadOnly` 白名单。另行显式打开 RPC 开关的 `RouterRpcReadOnly` 才增加类型8，且只接受四个只读方法的严格原生包；不是任意 RPC 转发。`START`、参数保存、`FW BEGIN/END` 和旧 Protocol V2 仍不能从新 TCP 入口进入。STM32 原有本地串口权限未改，专用 ESP 入站仍保留原来精确匹配的 PONG 白名单。

**这是可信局域网明文诊断，不是公网服务。** 没有 TLS/认证，不放 Wi-Fi 密码/API token 到这些包里，不开放腾讯云端口。主机 CLI 默认仅监听回环；绑定指定私网地址需要显式 `--allow-lan`。ESP32 默认关闭 TCP Router。

## 4. 两个本地进程试用

终端一：

```powershell
python -m router_network.node --node 3 --listen 127.0.0.1:21000
```

终端二：

```powershell
python -m router_network.node --node 4 --connect 127.0.0.1:21000 --ping 3 --status 3
```

第二个进程发现节点、打印 PONG/INFO 后退出。第一个进程按 Ctrl+C 关闭。纯 TCP 演示仅使用 Python 标准库；真实串口适配器需要已有 `pyserial`。

## 5. 实机拓扑与当前验收范围

建议 `1=STM32`、`2=ESP32`、`3=鲁班猫/控制盒`、`4=电脑`、`5=工装`。没有实体控制盒/工装时，用软件节点代替并明确标注。

```text
电脑(4) ─ TCP ─ 鲁班猫(3) ─ TCP/Wi-Fi ─ ESP32(2) ─ UART ─ STM32(1)
                     └─ TCP/USB转串口 ─ 工装(5，尚需实际设备)
```

在鲁班猫项目根目录，以示例有线地址监听，同时主动连接 ESP32 在热点上的 IP：

```bash
python3 -m router_network.node --node 3 --listen 192.168.137.10:21000 --allow-lan --connect <ESP32实际IP>:21000
```

电脑：

```powershell
python -m router_network.node --node 4 --connect 192.168.137.10:21000 --ping 1 --status 2 --status 3
```

先确认实际地址、隔离状态、固件版本及设备稳定启动。不要把 `<ESP32实际IP>` 原样粘贴；实际地址由鲁班猫热点 DHCP 分配，本次为192.168.50.114。STM32 A 与 ESP32 已更新，鲁班猫 Python 3.8 前台桥接已实际运行验收。旧 `router-acceptance-20261005.zip` 只验证数字PING/STATUS；新 **`router-rpc-acceptance-20261005.zip`** 增加四个RPC检查，均不安装服务、不修改热点或云端。验收结束已停止临时桥接；再次使用时，在已隔离的鲁班猫终端运行 `python3 /root/router-rpc-acceptance-20261005.zip` 并保持窗口打开。它会按 ESP MAC 查找热点地址。

USB 转串口是另一个接入选择，不要求使用 TCP：

```powershell
python -m router_network.node --node 4 --usb-serial COM5 --ping 1
```

此前数字PING/STATUS验收在机械端隔离、获准刷写及复位后，实际打开了 COM5（STM32 ST-Link VCP）与 COM9（ESP32），并通过以下只读测试：

```powershell
python -m router_network.live_acceptance --usb-serial COM5 --target 1 --target 2 --rounds 20
```

得到 4 次初始回复和 80 次连续附加请求—回复；相同 PING 两次只回复一次，TTL=1 不会继续转发到下游 ESP32。不是 2M 测试，也没有测试物理 USB 插拔恢复。

Linux 使用 `--uart /dev/serial/by-id/实际设备` 或 `--usb-serial /dev/serial/by-id/实际设备`。UART 默认 115200。不要与现有串口日志程序抢读同一设备。即使先设置 DTR/RTS 为低，实际打开 USB 驱动仍可能发生硬件相关的线电平跳变，不能保证所有板都不自动复位。

这里的 USB 是 **USB 转串口/虚拟串口**，不是 STM32 原生 USB CDC。现有 Qt HMI 的 SocketCAN 状态/RPC/Transfer 链路继续独立工作；本次没有把 CAN 改成 Router 端口。

## 6. 编译与测试

```powershell
./tools/build_router_network.ps1
./tools/build_router_network.ps1 -Esp32
./tools/test_router_network.ps1
```

只读 RPC 试验版用 `./tools/build_router_network.ps1 -Rpc` 和 `./tools/build_router_network.ps1 -Rpc -Esp32`，分别生成 `build/RouterRpcReadOnly` 与 `build_router_rpc`，不覆盖上一版。RPC两端开关默认关闭；测试脚本现在同时构建官方RPC主机测试及26项Python测试。

新固件与桥接已实机验证。先在鲁班猫启动上述RPC包并保持终端，再在电脑使用 `python -m router_network.rpc_client --tcp 192.168.137.10:21000 --node 4`，输出字段名和四项结果；也可独占COM5时使用 `--usb-serial COM5`。Python工具是原生包codec/unary适配，不是官方Python RPC引擎。同节点重复启动CLI可能碰上30秒序号去重窗口，不要让多个客户端共用节点号。

- STM32 新配置：`RouterNetworkReadOnly`，继承现有 `CanRpcReadOnly`；产物在两槽各自的 `build/RouterNetworkReadOnly`。
- ESP32 数字诊断配置：`build_router`、`sdkconfig.router.defaults`；RPC配置为`build_router_rpc`、`sdkconfig.router_rpc.defaults`，不改 `build_network`。两轮都仅更新应用，Bootloader、分区表、PHY回读一致，私有gateway配置值一致；上一轮初始化后NVS原始页变化，本次RPC前后回读则NVS原始字节一致，两个结论属于不同刷写轮次。
- C 主机测试工程：`tests/router_network_host`，使用 MinGW/Ninja 编译后运行 CTest。Python 测试会用其 `router_wire_probe.exe` 检查 C/Python 策略一致性；未构建时这一项会明确 skip。
- `ROUTER_READ_ONLY_NETWORK` 和 `CONFIG_GATEWAY_ROUTER_ENABLE` 默认关闭。关闭 STM32 新功能时，预处理后的 Router/ESP 入站代码与改造前一致。

所有构建脚本都 **只编译，不执行 flash、串口探测或 reset**。正常程序启动仍有原有 PWM/校准流程；只读网络不等于机械急停或独立功率切断。

## 7. 验收边界

离线已完成：26项Python测试、A/B真实Router核心2项C测试、A/B官方RPC Client/Server联调2项C++测试、旧UART8项、网络观测1项及CAN/RPC/Transfer3项主机回归。检查涵盖过长行、非法包、回复匹配、队列满、TTL、去重、老化、重连、旧会话隔离、四RPC方法和有界客户端容量。主机测试在Windows Python3.13执行；鲁班猫Python3.8已实际运行新桥接，不再属于待部署。

此前数字PING/STATUS实机记录：STM32非活动A槽确认（GEN=293），ESP应用更新与精确回读，USB/UART的80次附加往返、鲁班猫/Wi-Fi的120次附加往返及PC入口两次重连通过。节点5为SIM工装。Router原先512 words栈耗尽，功能打开时增到1024 words并禁止诊断内联；当时测到栈填充区剩1816 B、堆空闲9520 B、CFSR=0。**这些栈/故障寄存器结果不是新增RPC版的测量。**

新增RPC实机记录：先确认首版B（GEN=296），遇到双客户端第7轮超时；仅对RPC包增加最长30 ms的串口队列等待，不扩大4槽队列，其他包保持非阻塞，关闭功能路径不变。修复版A188892 B、CRC70272D59已确认（GEN=299），实体B仍是首版RPC187988 B回退，不是编译目录里的修复版B187996 B。Wi-Fi双软件客户端每轮并发8请求，10轮80次通过；USB另测10轮40次通过，无运动命令、无测试中复位、参数快照一致、安全锁存保持。最终堆空闲9520 B、最低4048 B；HMI运行、LAN云端隧道health200。临时鲁班猫RPC桥接已停止、21000关闭，未装自启。

未完成：最新RPC版STM32全量Flash回读及运行时栈余量/故障寄存器读取（ST-Link调试USB异常）、实体Wi-Fi掉线/重启恢复、五块实体设备、2M压力、原生USB CDC、CAN Router适配器、认证/TLS、任意二进制/Transfer路由及实机CAN历史日志导出。本次IAP上传CRC通过不代替完整Flash回读，不能宣称完整验收全部通过。没有安装鲁班猫Router开机自启服务。

路由发送成功只表示当前适配器接收/排队成功，不保证远端接收。队列满或链路错误会丢包；请求超时可以检测失败，本版没有通用可靠重传协议。Router 自身的包表示/RTOS队列和 Python socket 仍有复制；没有把它们宣传为端到端零拷贝。
