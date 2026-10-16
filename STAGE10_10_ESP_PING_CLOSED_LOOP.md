---
title: Stage 10.10 - 正式 APP 的 ESP PING/PONG 闭环
tags: [STM32G474, ESP32-S3, Router, UART, IAP]
date: 2026-09-26
status: B 槽已升级、自动确认；11 次真实 PING/PONG 成功，断线超时尚未实测
---

# Stage 10.10：正式 APP 的 ESP PING/PONG 闭环

## 目标与权限边界

此前的 SRAM 诊断程序已测到 ESP PONG，但正式 APP 的 ESP UART 只允许 `HELLO/ANNOUNCE` 发现帧。此步让 COM5 的 `ESP PING` 命令经 STM32 Router 发到节点 2，再把匹配的 `ESP32 PONG` 回显到 COM5。**ESP 仍不能下发电机、参数或 IAP 命令。**

## 实现

- A/B 源码新增 `Core/Inc/esp_ping.h`，严格解析正整数 1–65535 和完整载荷 `<ID> OK ESP32 PONG`；拒绝前后附加文本、超范围编号及其他载荷。
- `esp_link.c` 的入站白名单保留发现帧，只额外允许 `src=2,dst=1,type=PROTOCOL` 且载荷严格匹配 PONG 的 Router 帧。
- `ProtocolTask` 对所有 ESP 入站报文先走专用分支，**永不**把它们交给通用 `Protocol_HandleLine()`。PONG 还需与当前唯一待处理请求的 ID 和 2 秒期限匹配；无匹配则丢弃。
- `ESP PING` 只接受 COM5 原始 Protocol V2 命令，且请求号必须 1–65535。STM32 发 `TYPE=PROTOCOL`、载荷 `<ID> PING` 给节点 2；收到 PONG 后输出 `<ID> OK ESP32 PONG`。同一时间只允许一个待处理请求。
- B 槽 FreeRTOS 堆同步为已经在 A 槽验证过的 40 KiB，以容纳 ESP/Router 与 BootHealthTask；未改 FOC/PWM/ADC 路径。

## 构建与上板

`foc2_app_a` 与 `foc2_app_b` 构建通过；AS5047P 主机回归 4/4、TIM1/ADC 离线扫描通过。A 新源码仅离线编译，**没有**写入板上 A。B 新 BIN 为 **212872 B**，CRC32=`395DD27E`，静态 RAM 报告 **73528 B**。

升级前 COM5 确认 `CURRENT=A CONFIRMED=A PENDING=- GEN=241`、`MODE=IDLE FLT=0`、FOC 约 20 kHz、ESP 节点 2 在线。通过标准 IAP 把 B BIN 写入非活动 B：

```powershell
python -u 'D:\new project\foc2_app_a\iap_update.py' COM5 'D:\new project\foc2_app_b\build\Debug\foc2.bin'
```

IAP 写入 **212872/212872 B**，`FW END` 报 CRC `395DD27E` 并切换试运行。B 正常启动、BootHealthTask 创建成功，自动确认并重启；随后 `FW STATUS` 显示：

```text
CURRENT=B TARGET=A CONFIRMED=B PENDING=- ATTEMPTS=0 GEN=244
```

重启后 B `MODE=IDLE FLT=0`、`FOC/s≈20004`，Router 节点 2 已重新发现，`PARSE=0`。

## COM5 实测

```text
4203 ESP PING
4203 OK ESP PING SENT SEQ=26
4203 OK ESP32 PONG
```

接着 4300–4309 共 **10 次**连续请求，每次均收到自己的 `OK ESP PING SENT` 和同号 `OK ESP32 PONG`。边界值 `65535 ESP PING` 也收到 PONG；`65536` 与 `70000` 被拒绝，返回 `ERR 103 ESP_PING_COM5_ID_1_65535_ONLY`。合计 **12 次真实往返成功**。测试后仍为 `CONFIRMED=B`，Router `PARSE=0`、`RXQFULL=0`、`LOCALQFULL=0`。

同一批串口数据中连续发送 `4500 ESP PING`、`4501 ESP PING`：4500 获得 PONG，4501 返回 `ERR 101 ESP_PING_PENDING`，说明只有一个在途请求，不会把两个请求混配。

## 限制与下一步

- 此次证明的是正式 B APP 经真实 STM32↔ESP UART 的请求—回复闭环，以及请求号关联；**不是** Wi-Fi、Socket 或电机远程控制。
- 2 秒超时、ESP 断线与恢复、迟到/伪造 PONG 的负面路径已写入代码约束，但还没有通过物理断线或故障注入上板实测。
- 当前 A 是此前已确认的旧版回退镜像；本次没有把 PING 代码烧入 A。若未来要两槽同版，应先完成 B 的稳定性与异常路径验收，再从 B IAP 更新 A。

相关：[[第十章_ESP32-S3通信移植_Obsidian总结]]、[[STAGE10_9_A_NORMAL_TRIAL_HEAP]]。
