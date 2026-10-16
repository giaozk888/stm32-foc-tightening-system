# 电机控制 RPC 服务：接口已实现，远程运动未开放

日期：2026-10-08。本文记录本次源码与离线测试，不是上板验收报告。

## 现在能做什么

新增了独立服务 `foc.MotorControl`，挂到现有官方 `pw::rpc::Server`，没有把原来的
`foc.ReadOnly` 改成可写服务。配套 HMI 的“控制”页新增了状态查询按钮。

四个方法都有完整的请求解析、响应编码和主机往返测试。但当前 STM32 适配层明确返回
`DISABLED` 拒绝 Arm、StartTightening、Stop；GetOperationStatus 可查询状态和拒绝原因。
注册服务不等于授权电机动作。这次没有刷写、复位、操作真实 CAN/UART 或部署 HMI，
也没有解除 ANALOG SAFE、更改电流/电压/转速限幅。

| 方法 | 设计用途 | 当前板端实现 |
| --- | --- | --- |
| `Arm` | 检查当前会话、配方和联锁，建立短期一次性准备许可 | 拒绝远程准备，不使能 PWM，不解除锁存 |
| `StartTightening` | 消耗准备许可，提交现有拧紧作业 | 拒绝远程启动，不设置启动邮箱 |
| `Stop` | 提交软件停止请求，不要求先 Arm | 远程路径仍拒绝；不能把该接口当作实体急停 |
| `GetOperationStatus` | 读取当前/最后作业、软件故障、配方标识及缺项 | 可读；快照不是安全许可，也不是作业历史数据库 |

## 请求交给谁执行

服务回调只负责解析、检查和应答，不直接调用 PWM、功率级或 Flash。
以后经独立安全验收的本机适配层，才可把受理请求交给共用作业入口。

UART 的原 START/STOP 已改为调用 `MotorJob_QueueStart/Stop`。START 仍检查原来的
SAFE 锁存、APP 试运行、ADC/FOC 故障、忙状态、转子运动和启动自检；错误码和路由
回复来源保持不变。字段先写入、`__DMB()` 后发布请求标志。现有 `TighteningTask`
消费请求并再次检查，之后才执行作业。

这里是原有单槽邮箱，不是新建 MPSC 队列。UART 与 CAN unary RPC 都由唯一
`ProtocolTask` 处理，不能把共用入口搬到多个任务/ISR 随意调用。增加生产者时必须
重新设计排队、同步、背压和回复归属。RPC `QUEUED` 仅表示提交被接受，不证明电机
已经转动或实际停机；真实状态应另行查询。

## 准备、超时和重复请求

可移植逻辑位于 `motor_control.c`，允许在主机上用模拟端口测试：

- 每次动作携带非零 `operation_id`，START 使用同一启动会话的 `boot_id` 和当前
  `recipe_crc`。配方指纹从本机参数快照生成，客户端不能用请求覆盖配方。
- Arm 发出一次性关联 `arm_token`，有效期 5 秒。START 前再次检查本机状态，
  超时、会话改变、配方改变、故障或入队失败都会拒绝；尝试提交时消耗许可。
- 相同已受理 START 的 ID 与配方重发，返回 DUPLICATE，不再次启动。
  旧 ID 或相同 ID 搭配不同配方被拒绝。仅缓存最近一次 START；在同一 boot 会话
  中客户端 ID 必须单调推进，差值小于 uint32 半个范围，支持回绕。不是无限历史去重库。
- 已授权的 STOP 在模拟端口中不要求 Arm，也不受忙状态或采样故障阻挡；相同的
  最近 STOP ID 不重复提交。生产适配层的远程总禁用先于此规则，所以目前 STOP
  同样返回 DISABLED。不要依赖未开放的软件停止路径进行保护。
- HMI 客户端验证事务号、call ID、服务/方法、操作 ID、负载长度、业务决定和 RPC
  状态是否一致。5 秒整次超时，发送失败或协议异常显式失败，不自动重试动作。

`boot_id` 必须由可信本机的启动会话机制提供。当前机制未验收，因此生产适配层返回
`boot_id=0`，没有用时间戳伪装有效会话。`arm_token` 是关联码，CRC 是一致性检查，
二者都不是认证、签名或防攻击密钥。CAN ID 和物理接线也不等于用户授权。

## 为什么仍然锁定

本机快照固定报告缺少远程控制验收、实体急停回读、功率级可信回读、采样/保护资格、
启动会话资格和链路资格，并叠加当前 preflight、busy、SAFE。没有“打开一个宏就能
授权电机”的后门。后续必须实现并验收可信本机联锁适配器，才讨论开放动作。

不能用 SD 输出寄存器当成功率级反馈，不能用网络回执证明已停机，不能把板端电压
估算或软件电流限幅替代独立测量和电源限流。本次也没有依据电机资料中的最大 17 A
放宽已有测试限幅。

本构建继承正常 APP 的启动流程，**不是功率级硬隔离的诊断固件**。
“AdmissionLocked”只说明新的远程入口拒绝动作，不能据此认定普通启动/UART 路径
绝对无动作。上板前仍须核对硬件、固件配置、回退槽和现场授权。

## 协议与兼容性

CAN 仍用现有 `0x600` 请求、`0x601` 回复和有界分片，channel 为 2，包上限 128 B。
新服务不开放 Router、ESP32、云端或公网的电机控制通道；原 Router 白名单不变。
CAN FD 是否可用与该业务服务是两件事，本次没有切换 FD 或修改接口配置。

服务端使用官方 RawUnaryResponder 和官方 RPC packet 编码；HMI `MotorClient`
是兼容现有 packet 的轻量客户端适配器，**不是官方 pw::rpc::Client**。
外层是 Pigweed RpcPacket protobuf，内层是项目固定布局的 raw 字节，不是生成的
protobuf 业务消息。共有头 `motor_rpc_wire.h` 定义唯一 ABI。

Arm/Start/Stop 的请求为 5 个小端 u32（20 B）：

```text
version=1, operation_id, boot_id, recipe_crc, arm_token
```

GetOperationStatus 请求无负载。响应为 15 个小端 u32（60 B）：

```text
version, decision, blockers, preflight, boot_id, recipe_crc, arm_token,
operation_id, job_id, job_state, mode, busy, fault_reason, safe_latched, uptime_ms
```

`operation_id` 回显此次请求；`job_id` 来自本机启动邮箱/当前作业 ID，不等于本次
查询的 RPC call ID。`fault_reason` 是现有 FOC 原因码，ADC 等状态还应结合
preflight/作业状态判断。不能把它解释成完整的独立硬件诊断报告。

decision：0 OK、1 ARMED、2 QUEUED、3 DUPLICATE、4 DISABLED、5 UNSAFE、
6 BAD_SESSION、7 BAD_RECIPE、8 NOT_ARMED、9 EXPIRED、10 BAD_TOKEN、
11 REPLAY、12 QUEUE_REJECTED、13 INVALID。0–3 对应 RPC OK，其余有效业务拒绝
对应 FailedPrecondition（9）。客户端传输层 Success 仅表示收到了合法完整响应，
仍需检查 decision，不能把 DISABLED 的正常响应解释成动作成功。

blockers 位 0–8 分别为：远程禁用、急停未验收、功率级回读未验收、采样未验收、
会话不可用、链路未验收、自检失败、忙、SAFE 锁存。
job_state 0–5 为：空闲、已排队、运行、完成、软件停止、故障。

原 CAN 回复以约 100 ms/帧的低优先级预算发送，一次完整调用可能需要数秒。
该通道不是实时运动控制或急停链路；5 秒 Arm 期限是本协议适配设计，不是工业安全参数。
旧 firmware/HMI 不会自动获得新功能：旧固件未注册此服务时，新查询会超时，原只读
Ping/Status/Params/Diagnostics/Transfer.Read 仍按各自原协议工作。

## 文件位置和离线复现

- `motor_control.h/.c`：无 HAL、无堆分配的会话/受理逻辑。
- `motor_rpc_wire.h`：服务、方法、请求/响应布局和严格白名单。
- `pw_motor_control_rpc.inc`：挂载官方 pw_rpc 的业务服务。
- `motor_job_port.inc`：A/B 共用 UART 作业入口、当前生产 RPC 拒绝式适配层。
- `../lubancat_hmi/src/rpc_motor_client.h`：有界请求/回复客户端。
- `../tests/motor_control_host`：逻辑、真实适配层源码和 UART 兼容测试。
- `../tests/can_rpc_host`：真实 A/B 官方 Server 与客户端的 CAN 队列往返测试。

`CAN_MOTOR_CONTROL_SERVICE` 默认 OFF。显式编译服务可分别在 A/B 目录执行：

```powershell
cmake --preset MotorRpcAdmissionLocked
cmake --build --preset MotorRpcAdmissionLocked -j 4
```

该 preset 继承 CanRpcReadOnly，仅注册新服务，**并不启用动作权限**。不要直接拿
这个正常启动镜像刷板测试。上位机已有 build_win 配置可离线构建，测试需 Qt/MinGW
DLL 在 PATH；主机测试也需要 MinGW 运行库。

```powershell
cmake --build tests/motor_control_host/build -j 4
ctest --test-dir tests/motor_control_host/build --output-on-failure
cmake --build tests/can_rpc_host/build -j 4
ctest --test-dir tests/can_rpc_host/build --output-on-failure
cmake --build lubancat_hmi/build_win -j 4
ctest --test-dir lubancat_hmi/build_win --output-on-failure
```

## 验证边界

离线测试结果：受理逻辑/真实适配层 2/2、CAN RPC/官方 Transfer 5/5、Qt 上位机 12/12，
合计 19/19 通过。1024×600 离屏截图检查后，控制页改为滚动布局，避免联锁说明被裁切。
A/B 新服务与原 CanRpcReadOnly 配置均编译通过。

新服务配置链接占用：A 槽 Flash 193120 B、静态 RAM 96824 B；B 槽 Flash 192216 B、
静态 RAM 96800 B。两槽各有 224 KiB Flash；这里 RAM 是链接区域占用，不是运行时余量。
编译器记录单函数栈帧：ProtocolTask 1176 B、服务 Handle 248 B、快照 88 B，
不是整条调用链峰值；ProtocolTask 原 1024 字（4096 B）栈预算未改，仍需上板水位验收。

本次已验证模拟端口的准备/启动/停止、重复 ID、旧 ID、uint32 回绕、期限、错误 token、
会话/配方改变、故障、入队失败，以及真实 MCU 适配层始终拒绝远程动作、UART 原门槛。
官方 A/B Server 与实际 HMI 客户端经项目 CAN 分片/队列往返，另验证非法 envelope、
错误事务/会话关联、非法业务响应、无自动重试和原只读服务不被扩权。

这里的 CAN 收发和联锁输入均为主机模拟，不是实物电机测试。RAM/Flash 与单函数
栈帧编译结果不能替代运行时栈水位、最坏时延、真实断线/故障、实体急停与带电验收。
实际开放远程运动仍需要另行实现可信安全适配器、通讯授权和失联策略，并获得现场测试许可。
