# CAN 作业控制 v0：执行仍关闭

## 当前事实与使用边界

当前已确认 APP B 的 FDCAN 发送 `0x180`–`0x182`，另外仅接收无动作诊断 ID `0x220`；其他数据帧及全部远程帧由过滤器拒绝。新增 `CAN_CONTROL_REJECT_ONLY` 可选构建仅接收 `0x200` 并回复 `0x280` 的 `REJECT_DISABLED`，但**尚未刷写上板**，当前设备仍不接受 `0x200`。鲁班猫 HMI 新增控制页并已独立部署，仅作本地协议预演和被动回执观察，不发送控制帧。不得使用 `cansend` 试验启动，也不能把离线单元测试解释成电机控制验收。独立的 `0x220/0x2A0` 无动作诊断见 [`CAN_SHADOW_DIAG.md`](CAN_SHADOW_DIAG.md)。现场此前观察到 `bus-off` 累计增加和 `ERROR-WARNING`，正式控制必须先解决通信可靠性。

## 经典 CAN 候选帧

均为 500 kbit/s、标准 11 位 ID、DLC=8、小端序；为未来实现预留，不与当前 `0x180`–`0x182` 只读帧混用。

| ID | 方向 | 字节布局 |
| --- | --- | --- |
| `0x200` | 鲁班猫→STM32 | `version:u8=1, opcode:u8, sequence:u16, session_token:u16, recipe_id:u16` |
| `0x280` | STM32→鲁班猫 | `version:u8=1, opcode:u8, sequence:u16, decision:u8, motor_mode:u8, session_token:u16` |

`opcode` 1=ARM、2=START、3=STOP。ARM/START 的 `recipe_id` 必须非零，STOP 的 `recipe_id` 固定零。`decision=9` 是 `REJECT_DISABLED`，拒绝所有三个操作（STOP 也不是急停）。其他 `decision` 仅为协议层意向或拒绝原因；`START_INTENT` **不等于**电机已启动，真实执行需要额外的状态回读和状态机确认。HMI 仅被动显示严格解析的 `0x280`，由于没有发出请求，不将任何回执视为本机命令成功。

## 离线状态机

- 每次 MCU 会话生成新的非零 `session_token`，仅在可信本地协商后提供给上位机；当前未设计该协商或令牌源。16 位令牌只可防偶发旧帧，不是认证或抗恶意注入机制。
- ARM 仅在急停释放、功率级状态回读有效、编码器/电流/母线有效、配方已校验、固件槽已确认、CAN 质量合格、电机空闲且转子静止、无故障及无 `ANALOG SAFE` 锁存时进入短暂预备态。所有证据必须来自 STM32 本机可信状态，不能直接相信 HMI 自报。
- START 必须在 ARM 后 500 ms 内，序号恰为 ARM+1（允许 16 位回绕）、令牌/配方相同且重新检查上述安全条件。任一条件失败即撤销预备态；成功只返回意向，不操控功率级。
- STOP 可在任何故障/总线状态下形成停机意向，并撤销预备态和当前令牌；重复 STOP 是幂等的。真正停机动作需要独立、经验证的低层执行路径。
- MCU 复位、CAN 断线/错误恶化、急停、故障、控制任务超时或电源状态变化时，都必须由未来集成代码清除预备态/令牌。仅靠本模块的按需 `Evaluate` 不构成持续联锁；STM32 现有 `ANALOG SAFE` 软件锁存复位后会消失。

## 已实现及未完成

`can_control_v0.h/.c` 是零 HAL 依赖的纯 C 编解码及意向评估模块。新增 `CanControlV0_EvaluateDisabled()` 永远撤销会话并返回拒绝；A/B 固件 CMake 仅在显式 `CAN_CONTROL_REJECT_ONLY=ON` 时编入，并将 `0x200` 过滤到 FIFO1，最多每个监控周期处理一帧，回 `0x280`，没有任何电机调用。当前 A/B 新镜像已构建但**未刷写**。HMI 编入同一编解码模块，但没有发送函数或控制发送代码。主机测试包含版本、ID、DLC、帧类型、大小端、序号回绕/重放、500 ms 超时、STOP 幂等、逐项安全条件缺失及锁定模式拒绝所有操作。命令：

```sh
cmake -S tests/can_control_v0_host -B tests/can_control_v0_host/build -G Ninja
cmake --build tests/can_control_v0_host/build
ctest --test-dir tests/can_control_v0_host/build --output-on-failure
```

进入上板阶段前还缺：真实急停输入及功率级状态回读、可信配方范围与版本、令牌/会话协商、命令超时和离线停机策略、回复与实际状态一致性、双 A/B 固件升级及回滚测试、扭矩标定、受控负载试验、CAN 可靠性复验。缺任一项均不开放 HMI“开始”或“配方下发”。

## 2026-09-29 锁定版构建与显示部署

主机协议测试、HMI 现有 5 项测试均通过；A/B 固件显式开启
`CAN_SHADOW_DIAG=ON`、`CAN_CONTROL_REJECT_ONLY=ON` 均构建成功，
但**没有向 STM32 刷写**。因此 `0x200/0x280` 的实物往返尚未验证，
不要预期当前 MCU 回复 `REJECT_DISABLED`。

HMI 在鲁班猫的独立目录 `/home/cat/lubancat_hmi_control_locked` 构建，
Qt/DRM 离屏截图为 1024×600；新 `zzz-control-locked.conf` 覆盖项指向
该目录。切换后 `lubancat-hmi.service` 和 `lubancat-can0.service` 均
active、HMI 自动重启次数 0、`can0` ERROR-ACTIVE；原 `build_preflight` 二进制及
`zz-preflight.conf` 保留。此检查仅证明进程启动与离屏渲染，MIPI 实屏
尚待现场确认。鲁班猫时钟在本次截图显示 2024 年，需另行校准，
不要用它作为作业时间证据。回退显示时移走新覆盖项并
`systemctl daemon-reload && systemctl restart lubancat-hmi.service`，
即可恢复 `zz-preflight.conf` 对应的旧构建。
